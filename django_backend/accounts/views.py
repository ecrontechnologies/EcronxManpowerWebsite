"""
API views for the Ecronx Manpower backend.

These implement the same routes the existing frontend already calls, so the UI
does not need to change, plus new endpoints for password change and recovery.
All authentication is DB-backed, all passwords go through Django's hashers, and
role checks are enforced per view.
"""

from __future__ import annotations

import csv
import io
import secrets

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .authentication import issue_token
from .models import (
    AttendanceRecord,
    AuthToken,
    BackupLog,
    CorrectionRequest,
    Enquiry,
    GalleryImage,
    Service,
    Site,
    SiteSettings,
    User,
)
from .permissions import IsAdministrator, IsEmployee
from .serializers import (
    AdminUserSerializer,
    AttendanceRecordSerializer,
    CorrectionRequestSerializer,
    EnquirySerializer,
    GalleryImageSerializer,
    ServiceSerializer,
    SiteCreateSerializer,
    SiteSerializer,
    SiteSettingsSerializer,
    UserSummarySerializer,
)
from .utils import (
    filtered_records,
    local_date,
    local_date_string,
    make_pdf,
    parse_iso_datetime,
    valid_date_string,
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def error(message: str, code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": message}, status=code)


def username_from_name(name: str) -> str:
    base = slugify(name)[:32] or "employee"
    candidate = base
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"ok": True, "service": "ecronx-django", "time": timezone.now()})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class EmployeeLoginView(APIView):
    """POST { username, password } -> { token, employee }"""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip().lower()
        password = str(request.data.get("password", ""))
        user = User.objects.filter(username=username).first()
        if (
            user is None
            or user.role != User.Role.EMPLOYEE
            or not user.is_active
            or len(password) > 256
            or not user.check_password(password)
        ):
            return error("Invalid username or password.", status.HTTP_401_UNAUTHORIZED)
        token = issue_token(user)
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return Response({"token": token.key, "employee": UserSummarySerializer(user).data})


class AdminLoginView(APIView):
    """POST { username, password } -> { token } for administrators only."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip().lower()
        password = str(request.data.get("password", ""))
        user = User.objects.filter(username=username).first()
        if (
            user is None
            or not user.is_administrator
            or not user.is_active
            or len(password) > 256
            or not user.check_password(password)
        ):
            return error("Invalid username or password.", status.HTTP_401_UNAUTHORIZED)
        token = issue_token(user)
        User.objects.filter(pk=user.pk).update(last_login=timezone.now())
        return Response({"token": token.key})


class LogoutView(APIView):
    """POST -> revoke the caller's bearer token."""

    def post(self, request):
        token = getattr(request, "auth", None)
        if isinstance(token, AuthToken):
            token.delete()
        return Response({"ok": True})


class MeView(APIView):
    """GET -> the signed-in employee with today's record and recent history."""

    permission_classes = [IsEmployee]

    def get(self, request):
        employee = request.user
        records = AttendanceRecord.objects.filter(employee=employee).order_by("-date")[:60]
        today = AttendanceRecord.objects.filter(
            employee=employee, date=local_date()
        ).first()
        site = employee.site
        return Response(
            {
                "employee": UserSummarySerializer(employee).data,
                "site": SiteSerializer(site).data if site else None,
                "today": AttendanceRecordSerializer(today).data if today else None,
                "records": AttendanceRecordSerializer(records, many=True).data,
            }
        )


class ChangePasswordView(APIView):
    """POST { currentPassword, newPassword, confirmPassword } for the signed-in user."""

    def post(self, request):
        try:
            services.change_password(
                user=request.user,
                current_password=str(request.data.get("currentPassword", "")),
                new_password=str(request.data.get("newPassword", "")),
                confirm=str(request.data.get("confirmPassword", "")),
            )
        except services.ResetError as exc:
            return error(str(exc))
        return Response(
            {
                "ok": True,
                "message": "Your password has been changed. Please sign in again.",
            }
        )


class PasswordResetRequestView(APIView):
    """
    POST { username, role } -> emails a time-limited verification code.

    Always returns the same message so it cannot be used to discover which
    usernames exist.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        username = str(request.data.get("username", "")).strip()
        role = str(request.data.get("role", "admin")).strip().lower()
        purpose = (
            "employee_reset" if role == "employee" else "admin_reset"
        )
        from .models import PasswordResetCode

        try:
            services.request_reset(username=username, purpose=purpose)
        except services.ResetError as exc:
            return error(str(exc))
        except Exception:  # SMTP failure - do not leak details.
            return error(
                "The verification email could not be sent. Check the email "
                "settings or contact another administrator."
            )
        return Response(
            {
                "ok": True,
                "message": (
                    "If that account exists and has a recovery email on file, a "
                    "6-digit verification code has been sent. It expires in "
                    f"{settings.PASSWORD_RESET_CODE_TTL_MINUTES} minutes."
                ),
            }
        )


class PasswordResetVerifyView(APIView):
    """POST { username, code } -> { ticket } after verifying the emailed code."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        try:
            ticket = services.verify_reset_code(
                username=str(request.data.get("username", "")).strip(),
                code=str(request.data.get("code", "")).strip(),
            )
        except services.ResetError as exc:
            return error(str(exc))
        return Response({"ok": True, "ticket": ticket})


class PasswordResetConfirmView(APIView):
    """POST { username, code, ticket, newPassword, confirmPassword } -> password set."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        try:
            services.set_password_with_code(
                username=str(request.data.get("username", "")).strip(),
                code=str(request.data.get("code", "")).strip(),
                ticket=str(request.data.get("ticket", "")).strip(),
                new_password=str(request.data.get("newPassword", "")),
                confirm=str(request.data.get("confirmPassword", "")),
            )
        except services.ResetError as exc:
            return error(str(exc))
        return Response({"ok": True, "message": "Your password has been reset. You can sign in now."})


# ---------------------------------------------------------------------------
# Employee attendance
# ---------------------------------------------------------------------------
def _employee_record_today(employee):
    return AttendanceRecord.objects.filter(employee=employee, date=local_date()).first()


class CheckInView(APIView):
    permission_classes = [IsEmployee]

    def post(self, request):
        location = request.data.get("location") or {}
        lat, lng, acc = location.get("latitude"), location.get("longitude"), location.get("accuracy")
        if not all(isinstance(v, (int, float)) for v in (lat, lng, acc)) or not (-90 <= lat <= 90) or not (-180 <= lng <= 180) or acc < 0:
            return error("A valid GPS location and accuracy are required to check in.")
        employee = request.user
        with transaction.atomic():
            if AttendanceRecord.objects.filter(employee=employee, date=local_date()).exists():
                return error("An attendance entry already exists for today.", status.HTTP_409_CONFLICT)
            record = AttendanceRecord.objects.create(
                employee=employee,
                employee_name=employee.full_name,
                username=employee.username,
                site=employee.site,
                date=local_date(),
                status=AttendanceRecord.Status.PRESENT,
                check_in_at=timezone.now(),
                check_in_latitude=lat,
                check_in_longitude=lng,
                check_in_accuracy=acc,
                check_in_address=(location.get("address") or "")[:250],
                source="gps",
            )
        return Response(
            {"ok": True, "record": AttendanceRecordSerializer(record).data},
            status=status.HTTP_201_CREATED,
        )


class CheckOutView(APIView):
    permission_classes = [IsEmployee]

    def post(self, request):
        location = request.data.get("location") or {}
        lat, lng, acc = location.get("latitude"), location.get("longitude"), location.get("accuracy")
        if not all(isinstance(v, (int, float)) for v in (lat, lng, acc)) or not (-90 <= lat <= 90) or not (-180 <= lng <= 180) or acc < 0:
            return error("A valid GPS location and accuracy are required to check out.")
        record = _employee_record_today(request.user)
        if record is None or record.check_in_at is None:
            return error("You must check in before checking out.", status.HTTP_409_CONFLICT)
        if record.check_out_at is not None:
            return error("You have already checked out today.", status.HTTP_409_CONFLICT)
        record.check_out_at = timezone.now()
        record.check_out_latitude = lat
        record.check_out_longitude = lng
        record.check_out_accuracy = acc
        record.check_out_address = (location.get("address") or "")[:250]
        record.save()
        return Response(
            {
                "ok": True,
                "record": AttendanceRecordSerializer(record).data,
                "workingMinutes": record.working_minutes,
            }
        )


class CorrectionRequestView(APIView):
    permission_classes = [IsEmployee]

    def post(self, request):
        date_str = str(request.data.get("date", ""))
        if not valid_date_string(date_str):
            return error("Provide a valid date (YYYY-MM-DD).")
        check_in = parse_iso_datetime(request.data.get("checkIn"))
        check_out = parse_iso_datetime(request.data.get("checkOut"))
        if check_in is None and check_out is None:
            return error("Provide at least one requested check-in or check-out time.")
        if check_in and local_date(check_in) != date_str:
            return error("The requested check-in time is not on the selected date.")
        if check_out and local_date(check_out) != date_str:
            return error("The requested check-out time is not on the selected date.")
        if check_in and check_out and check_out < check_in:
            return error("The requested check-out cannot be before check-in.")
        note = str(request.data.get("note", "")).strip()[:1000]
        if not note:
            return error("Please explain the correction request.")
        correction = CorrectionRequest.objects.create(
            employee=request.user,
            employee_name=request.user.full_name,
            date=parse_date(date_str),
            requested_check_in=check_in,
            requested_check_out=check_out,
            note=note,
            status=CorrectionRequest.Status.PENDING,
        )
        return Response(
            {"ok": True, "request": CorrectionRequestSerializer(correction).data},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Administrator attendance management
# ---------------------------------------------------------------------------
class AdminDashboardView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        date_str = request.query_params.get("date") or local_date_string()
        if not valid_date_string(date_str):
            return error("Use a valid date filter in YYYY-MM-DD format.")
        date_value = parse_date(date_str)

        active_employees = User.objects.filter(role=User.Role.EMPLOYEE, is_active=True)
        today_records = AttendanceRecord.objects.filter(date=date_value).select_related("employee", "site")
        present = [r for r in today_records if r.status == AttendanceRecord.Status.PRESENT]
        on_leave = [r for r in today_records if r.status == AttendanceRecord.Status.LEAVE]

        try:
            records = filtered_records(
                AttendanceRecord.objects.select_related("employee", "site").all(),
                from_date=request.query_params.get("from", ""),
                to_date=request.query_params.get("to", ""),
                employee_uuid=request.query_params.get("employeeId", ""),
                month=request.query_params.get("month", ""),
            )
        except ValueError as exc:
            return error(str(exc))

        last_backup = BackupLog.objects.order_by("-created_at").first()
        return Response(
            {
                "employees": UserSummarySerializer(active_employees, many=True).data,
                "sites": SiteSerializer(Site.objects.all(), many=True).data,
                "records": AttendanceRecordSerializer(records[:1000], many=True).data,
                "today": AttendanceRecordSerializer(today_records, many=True).data,
                "corrections": CorrectionRequestSerializer(
                    CorrectionRequest.objects.filter(status=CorrectionRequest.Status.PENDING)
                    .select_related("employee"),
                    many=True,
                ).data,
                "counts": {
                    "employees": active_employees.count(),
                    "present": len(present),
                    "leave": len(on_leave),
                    "absent": max(0, active_employees.count() - len(present) - len(on_leave)),
                    "checkedIn": len([r for r in present if r.is_open]),
                },
                "lastBackup": (
                    {
                        "createdAt": last_backup.created_at,
                        "from": last_backup.date_from.isoformat(),
                        "to": last_backup.date_to.isoformat(),
                        "format": last_backup.format,
                    }
                    if last_backup
                    else None
                ),
                "date": date_str,
            }
        )


class AdminEmployeeCreateView(APIView):
    """POST { name?, username?, password, siteId, email? } -> create an employee account."""

    permission_classes = [IsAdministrator]

    def post(self, request):
        name = str(request.data.get("name", "")).strip()[:100]
        raw_username = str(request.data.get("username", "")).strip().lower()
        password = str(request.data.get("password", ""))
        email = str(request.data.get("email", "")).strip()[:254]
        site_uuid = str(request.data.get("siteId", "")).strip()

        if len(name) < 2:
            return error("Enter the employee's full name (at least 2 characters).")
        if not raw_username:
            raw_username = username_from_name(name)
        if not (3 <= len(raw_username) <= 40) or not all(
            c.islower() or c.isdigit() or c in "._-" for c in raw_username
        ):
            return error(
                "Username must be 3-40 characters using lowercase letters, numbers, "
                "dots, underscores or hyphens."
            )
        if User.objects.filter(username=raw_username).exists():
            return error("That username is already in use.", status.HTTP_409_CONFLICT)

        site = None
        if site_uuid:
            site = Site.objects.filter(uuid=site_uuid).first()
            if site is None:
                return error("Select a valid client/site.")

        try:
            validate_password(password)
        except ValidationError as exc:
            return error(" ".join(exc.messages))

        try:
            employee = User.objects.create_user(
                username=raw_username,
                password=password,
                full_name=name,
                email=email,
                role=User.Role.EMPLOYEE,
                site=site,
            )
        except IntegrityError:
            return error("That username is already in use.", status.HTTP_409_CONFLICT)
        return Response(
            {"ok": True, "employee": UserSummarySerializer(employee).data, "generatedUsername": raw_username if not request.data.get("username") else None},
            status=status.HTTP_201_CREATED,
        )


class AdminEmployeeDetailView(APIView):
    """PATCH/DELETE an employee: activate, deactivate, update, or delete."""

    permission_classes = [IsAdministrator]

    def _get(self, uuid_value):
        return User.objects.filter(uuid=uuid_value, role=User.Role.EMPLOYEE).first()

    def patch(self, request, uuid_value):
        employee = self._get(uuid_value)
        if employee is None:
            return error("Employee not found.", status.HTTP_404_NOT_FOUND)
        updated = []
        if "active" in request.data:
            employee.is_active = bool(request.data["active"])
            updated.append("is_active")
        if "name" in request.data and str(request.data["name"]).strip():
            employee.full_name = str(request.data["name"]).strip()[:100]
            updated.append("full_name")
        if "email" in request.data:
            employee.email = str(request.data["email"]).strip()[:254]
            updated.append("email")
        if "siteId" in request.data:
            site_uuid = str(request.data["siteId"]).strip()
            if site_uuid:
                site = Site.objects.filter(uuid=site_uuid).first()
                if site is None:
                    return error("Select a valid client/site.")
                employee.site = site
            else:
                employee.site = None
            updated.append("site")
        if updated:
            employee.save(update_fields=updated)
            if "is_active" in updated and not employee.is_active:
                AuthToken.objects.filter(user=employee).delete()
        return Response({"ok": True, "employee": AdminUserSerializer(employee).data})

    def delete(self, request, uuid_value):
        employee = self._get(uuid_value)
        if employee is None:
            return error("Employee not found.", status.HTTP_404_NOT_FOUND)
        employee.delete()
        return Response({"ok": True})


class AdminEmployeePasswordResetView(APIView):
    """POST { newPassword } -> administrator sets a new password for an employee."""

    permission_classes = [IsAdministrator]

    def post(self, request, uuid_value):
        employee = User.objects.filter(uuid=uuid_value, role=User.Role.EMPLOYEE).first()
        if employee is None:
            return error("Employee not found.", status.HTTP_404_NOT_FOUND)
        new_password = str(request.data.get("newPassword", ""))
        try:
            services.admin_reset_employee_password(
                admin=request.user, employee=employee, new_password=new_password
            )
        except services.ResetError as exc:
            return error(str(exc))
        return Response({"ok": True, "message": "The employee password has been reset."})


class AdminSiteCreateView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request):
        serializer = SiteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        site = Site.objects.create(**serializer.validated_data)
        return Response({"ok": True, "site": SiteSerializer(site).data}, status=status.HTTP_201_CREATED)


class AdminLeaveView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request):
        date_str = str(request.data.get("date", ""))
        if not valid_date_string(date_str):
            return error("Choose a valid leave date.")
        employee = User.objects.filter(
            uuid=str(request.data.get("employeeId", "")), role=User.Role.EMPLOYEE, is_active=True
        ).first()
        if employee is None:
            return error("Employee not found.", status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            record = AttendanceRecord.objects.filter(
                employee=employee, date=parse_date(date_str)
            ).first()
            if record and record.check_in_at is not None:
                return error(
                    "An employee who has checked in cannot be marked on leave.",
                    status.HTTP_409_CONFLICT,
                )
            if record is None:
                record = AttendanceRecord.objects.create(
                    employee=employee,
                    employee_name=employee.full_name,
                    username=employee.username,
                    site=employee.site,
                    date=parse_date(date_str),
                )
            record.status = AttendanceRecord.Status.LEAVE
            record.leave_note = str(request.data.get("note", "")).strip()[:300]
            record.source = "admin-leave"
            record.save()
        return Response({"ok": True, "record": AttendanceRecordSerializer(record).data})


class AdminCorrectionReviewView(APIView):
    permission_classes = [IsAdministrator]

    def post(self, request, uuid_value):
        decision = str(request.data.get("decision", "")).lower()
        if decision not in {"approve", "reject"}:
            return error("Choose approve or reject.")
        correction = CorrectionRequest.objects.select_related("employee").filter(uuid=uuid_value).first()
        if correction is None:
            return error("Correction request not found.", status.HTTP_404_NOT_FOUND)
        if correction.status != CorrectionRequest.Status.PENDING:
            return error(
                "This correction request has already been reviewed.", status.HTTP_409_CONFLICT
            )
        with transaction.atomic():
            if decision == "approve":
                record = AttendanceRecord.objects.filter(
                    employee=correction.employee, date=correction.date
                ).first()
                if record is None:
                    record = AttendanceRecord.objects.create(
                        employee=correction.employee,
                        employee_name=correction.employee_name,
                        username=correction.employee.username,
                        date=correction.date,
                        status=AttendanceRecord.Status.PRESENT,
                        source="admin-correction",
                    )
                proposed_in = correction.requested_check_in or record.check_in_at
                proposed_out = correction.requested_check_out or record.check_out_at
                if proposed_in and proposed_out and proposed_out < proposed_in:
                    return error(
                        "The requested checkout is before check-in; reject this request "
                        "or correct the submitted times.",
                        status.HTTP_409_CONFLICT,
                    )
                if correction.requested_check_in:
                    record.check_in_at = correction.requested_check_in
                if correction.requested_check_out:
                    record.check_out_at = correction.requested_check_out
                record.correction_approved = True
                record.status = AttendanceRecord.Status.PRESENT
                record.save()
                correction.status = CorrectionRequest.Status.APPROVED
            else:
                correction.status = CorrectionRequest.Status.REJECTED
            correction.reviewed_at = timezone.now()
            correction.reviewed_by = request.user
            correction.review_note = str(request.data.get("note", "")).strip()[:500]
            correction.save()
        return Response({"ok": True, "correction": CorrectionRequestSerializer(correction).data})


class AdminBackupView(APIView):
    """GET ?from&to&format=json|csv|pdf -> downloadable attendance report."""

    permission_classes = [IsAdministrator]

    def get(self, request):
        date_from = request.query_params.get("from", "")
        date_to = request.query_params.get("to", "")
        fmt = request.query_params.get("format", "json")
        if not valid_date_string(date_from) or not valid_date_string(date_to) or date_from > date_to:
            return error("Select a valid date range.")
        if fmt not in {"json", "csv", "pdf"}:
            return error("Choose JSON, CSV or PDF format.")

        records = filtered_records(
            AttendanceRecord.objects.select_related("employee", "site").all(),
            from_date=date_from,
            to_date=date_to,
        )
        sites = list(Site.objects.all())
        filename = f"attendance_{date_from}_to_{date_to}.{fmt}"

        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(
                [
                    "Date", "Employee", "Username", "Site", "Status", "Check-in time",
                    "Check-in latitude", "Check-in longitude", "Check-in accuracy (m)",
                    "Check-in address", "Check-out time", "Check-out latitude",
                    "Check-out longitude", "Check-out accuracy (m)", "Check-out address",
                    "Working hours", "Overtime hours",
                ]
            )
            site_names = {s.uuid: s.name for s in sites}
            for r in records:
                minutes = r.working_minutes
                writer.writerow(
                    [
                        r.date.isoformat(), r.employee_name, r.username,
                        site_names.get(r.site.uuid, r.site_name) if r.site_id else r.site_name,
                        r.status, r.check_in_at or "", r.check_in_latitude or "",
                        r.check_in_longitude or "", r.check_in_accuracy or "",
                        r.check_in_address or "", r.check_out_at or "", r.check_out_latitude or "",
                        r.check_out_longitude or "", r.check_out_accuracy or "",
                        r.check_out_address or "",
                        "" if minutes is None else f"{minutes / 60:.2f}",
                        "" if minutes is None else f"{max(0, minutes - 480) / 60:.2f}",
                    ]
                )
            payload = ("\ufeff" + buffer.getvalue()).encode("utf-8")
            content_type = "text/csv; charset=utf-8"
        elif fmt == "pdf":
            site_names = {s.uuid: s.name for s in sites}
            lines = [
                "Ecronx Technologies - Attendance report",
                f"Date range: {date_from} to {date_to}",
                f"Records: {len(records)}",
                "",
            ]
            for r in records:
                minutes = r.working_minutes
                lines.append(
                    f"{r.date.isoformat()} | {r.employee_name} ({r.username}) | {r.status} | "
                    f"Site: {site_names.get(r.site.uuid, '-') if r.site_id else '-'}"
                )
                lines.append(
                    f"  In: {r.check_in_at or '-'} @ "
                    f"{f'{r.check_in_latitude}, {r.check_in_longitude} +/-{r.check_in_accuracy}m' if r.check_in_at else '-'}"
                )
                lines.append(
                    f"  Out: {r.check_out_at or '-'} @ "
                    f"{f'{r.check_out_latitude}, {r.check_out_longitude} +/-{r.check_out_accuracy}m' if r.check_out_at else '-'}"
                    f" | Hours: {'-' if minutes is None else f'{minutes / 60:.2f}'}"
                )
            payload = make_pdf(lines)
            content_type = "application/pdf"
        else:
            import json

            data = {
                "formatVersion": 2,
                "createdAt": timezone.now().isoformat(),
                "dateRange": {"from": date_from, "to": date_to},
                "employees": [
                    {
                        # Never include password hashes in a backup payload by default.
                        "id": str(u.uuid), "username": u.username, "name": u.full_name,
                        "role": u.role, "active": u.is_active, "email": u.email,
                        "siteId": str(u.site.uuid) if u.site_id else "",
                        "createdAt": u.date_joined.isoformat(),
                    }
                    for u in User.objects.filter(role=User.Role.EMPLOYEE)
                ],
                "attendance": AttendanceRecordSerializer(records, many=True).data,
                "sites": SiteSerializer(sites, many=True).data,
                "correctionRequests": CorrectionRequestSerializer(
                    CorrectionRequest.objects.filter(
                        date__gte=date_from, date__lte=date_to
                    ),
                    many=True,
                ).data,
            }
            payload = (json.dumps(data, indent=2) + "\n").encode("utf-8")
            content_type = "application/json; charset=utf-8"

        BackupLog.objects.create(
            date_from=date_from, date_to=date_to, format=fmt
        )
        response = HttpResponse(payload, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["Cache-Control"] = "no-store"
        return response


# ---------------------------------------------------------------------------
# Website content + enquiries (keeps the marketing site working)
# ---------------------------------------------------------------------------
class ContentView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        settings_row = SiteSettings.objects.order_by("-updated_at").first()
        return Response(
            {
                "settings": SiteSettingsSerializer(settings_row).data if settings_row else {},
                "services": ServiceSerializer(Service.objects.filter(active=True), many=True).data,
                "gallery": GalleryImageSerializer(GalleryImage.objects.all(), many=True).data,
            }
        )


class EnquiryView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        mobile = str(request.data.get("mobile", "")).strip()
        service_name = str(request.data.get("service", "")).strip()
        if not name or not mobile or not service_name:
            return error("Name, mobile and service are required.")
        enquiry = Enquiry.objects.create(
            name=name[:100],
            email=str(request.data.get("email", "")).strip()[:254],
            mobile=mobile[:30],
            service=service_name[:100],
            message=str(request.data.get("message", "")).strip()[:1000],
        )
        settings_row = SiteSettings.objects.order_by("-updated_at").first()
        return Response(
            {
                "ok": True,
                "enquiry": EnquirySerializer(enquiry).data,
                "settings": SiteSettingsSerializer(settings_row).data if settings_row else {},
            },
            status=status.HTTP_201_CREATED,
        )


class AdminEnquiriesView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        return Response(EnquirySerializer(Enquiry.objects.all(), many=True).data)
