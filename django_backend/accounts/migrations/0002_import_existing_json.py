"""
One-off data migration: import the existing JSON data files into the database.

This preserves the accounts, attendance records, sites, corrections and
website content that already exist under ``backend/data`` so nothing is lost
when Django becomes the system of record.

Notes
-----
* Existing scrypt password hashes **cannot** be converted to Django hashes
  (hashes are one-way). Imported employees keep their username and history but
  are flagged ``needs_password_reset`` in their ``full_name`` suffix? No - that
  would corrupt names. Instead, imported employees receive an *unusable*
  password, which means they cannot sign in until an administrator sets a new
  password (Django admin "Reset password", or the API endpoint). This is the
  secure choice: we never invent or store a plaintext password.
* The migration is idempotent and safe to run on an empty database.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from django.db import migrations
from django.utils import timezone

DATA_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "backend" / "data",
    Path(__file__).resolve().parents[3] / "django_backend" / "seed_data",
)

# Django's marker for an account that has no usable password (cannot sign in
# until an administrator sets a new one). Kept as a literal here so the
# migration does not depend on the current Django version's internals.
UNUSABLE_PASSWORD_PREFIX = "!" + "legacy-scrypt-import" + "!" + "unusable"


def _load(name: str):
    for base in DATA_DIR_CANDIDATES:
        path = base / name
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except (json.JSONDecodeError, OSError):
                return None
    return None


def _parse_dt(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt.timezone.utc)
    return parsed


def _parse_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def import_data(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Site = apps.get_model("accounts", "Site")
    AttendanceRecord = apps.get_model("accounts", "AttendanceRecord")
    CorrectionRequest = apps.get_model("accounts", "CorrectionRequest")
    SiteSettings = apps.get_model("accounts", "SiteSettings")
    Service = apps.get_model("accounts", "Service")
    GalleryImage = apps.get_model("accounts", "GalleryImage")
    Enquiry = apps.get_model("accounts", "Enquiry")

    # ---- Sites -----------------------------------------------------------
    site_map: dict[str, Site] = {}
    for item in _load("attendance-sites.json") or []:
        site, _ = Site.objects.get_or_create(
            uuid=item.get("id"),
            defaults={
                "client": (item.get("client") or "")[:120],
                "name": (item.get("name") or "")[:120],
                "address": (item.get("address") or "")[:250],
                "created_at": _parse_dt(item.get("createdAt")) or timezone.now(),
            },
        )
        site_map[item.get("id")] = site

    # ---- Employees -------------------------------------------------------
    employee_map: dict[str, User] = {}
    for item in _load("attendance-employees.json") or []:
        username = (item.get("username") or "").strip().lower()
        if not username or User.objects.filter(username=username).exists():
            if username:
                employee_map[item.get("id")] = User.objects.get(username=username)
            continue
        employee = User.objects.create(
            uuid=item.get("id"),
            username=username,
            full_name=(item.get("name") or "")[:100],
            role="employee",
            site=site_map.get(item.get("siteId")) if item.get("siteId") else None,
            is_active=item.get("active", True) is not False,
            date_joined=_parse_dt(item.get("createdAt")) or timezone.now(),
        )
        # Legacy scrypt hash cannot be re-used by Django: lock the account
        # until an administrator sets a new password via the admin panel.
        # (Historical models have no helper methods, so we write the
        # "unusable password" marker directly.)
        employee.password = UNUSABLE_PASSWORD_PREFIX
        employee.save(update_fields=["password"])
        employee_map[item.get("id")] = employee

    # ---- Attendance ------------------------------------------------------
    for item in _load("attendance-records.json") or []:
        employee = employee_map.get(item.get("employeeId"))
        date_value = _parse_date(item.get("date"))
        if employee is None or date_value is None:
            continue
        check_in = item.get("checkIn") or {}
        check_out = item.get("checkOut") or {}
        AttendanceRecord.objects.get_or_create(
            uuid=item.get("id"),
            defaults={
                "employee": employee,
                "employee_name": (item.get("employeeName") or employee.full_name)[:100],
                "username": (item.get("username") or employee.username)[:40],
                "site": site_map.get(item.get("siteId")) if item.get("siteId") else None,
                "site_name": (item.get("siteName") or "")[:120],
                "date": date_value,
                "status": item.get("status") or "Present",
                "check_in_at": _parse_dt(check_in.get("timestamp")),
                "check_in_latitude": check_in.get("latitude"),
                "check_in_longitude": check_in.get("longitude"),
                "check_in_accuracy": check_in.get("accuracy"),
                "check_in_address": (check_in.get("address") or "")[:250],
                "check_out_at": _parse_dt(check_out.get("timestamp")),
                "check_out_latitude": check_out.get("latitude"),
                "check_out_longitude": check_out.get("longitude"),
                "check_out_accuracy": check_out.get("accuracy"),
                "check_out_address": (check_out.get("address") or "")[:250],
                "correction_approved": bool(
                    check_in.get("correctionApproved") or check_out.get("correctionApproved")
                ),
                "source": (item.get("source") or "")[:40],
                "leave_note": (item.get("leaveNote") or "")[:300],
            },
        )

    # ---- Corrections -----------------------------------------------------
    for item in _load("attendance-corrections.json") or []:
        employee = employee_map.get(item.get("employeeId"))
        date_value = _parse_date(item.get("date"))
        if employee is None or date_value is None:
            continue
        CorrectionRequest.objects.get_or_create(
            uuid=item.get("id"),
            defaults={
                "employee": employee,
                "employee_name": (item.get("employeeName") or employee.full_name)[:100],
                "date": date_value,
                "requested_check_in": _parse_dt(item.get("requestedCheckIn")),
                "requested_check_out": _parse_dt(item.get("requestedCheckOut")),
                "note": (item.get("note") or "")[:1000],
                "status": item.get("status") or "Pending",
                "submitted_at": _parse_dt(item.get("submittedAt")) or timezone.now(),
                "reviewed_at": _parse_dt(item.get("reviewedAt")),
                "review_note": (item.get("reviewNote") or "")[:500],
            },
        )

    # ---- Website content -------------------------------------------------
    content = _load("content.json") or {}
    settings = content.get("settings") or {}
    if settings and not SiteSettings.objects.exists():
        SiteSettings.objects.create(
            company_name=(settings.get("companyName") or "Ecronx Technologies Pvt Ltd")[:150],
            tagline=(settings.get("tagline") or "")[:200],
            phone=(settings.get("phone") or "")[:40],
            whatsapp=(settings.get("whatsapp") or "")[:40],
            email=(settings.get("email") or "")[:254],
            address=(settings.get("address") or "")[:250],
        )
    for item in content.get("services") or []:
        lookup = _uuid_lookup(item.get("id")) or {"name": (item.get("name") or "Service")[:120]}
        Service.objects.get_or_create(
            **lookup,
            defaults={
                "name": (item.get("name") or "Service")[:120],
                "description": (item.get("description") or "")[:1000],
                "image": (item.get("image") or "")[:500],
                "active": item.get("active", True) is not False,
            },
        )
    for item in content.get("gallery") or []:
        lookup = _uuid_lookup(item.get("id")) or {"title": (item.get("title") or "Gallery image")[:120]}
        GalleryImage.objects.get_or_create(
            **lookup,
            defaults={
                "title": (item.get("title") or "Gallery image")[:120],
                "category": (item.get("category") or "General")[:80],
                "image": (item.get("image") or "")[:500],
            },
        )
    for item in content.get("enquiries") or []:
        lookup = _uuid_lookup(item.get("id")) or {
            "name": (item.get("name") or "Website enquiry")[:100],
            "mobile": (item.get("mobile") or "")[:30],
        }
        Enquiry.objects.get_or_create(
            **lookup,
            defaults={
                "name": (item.get("name") or "Website enquiry")[:100],
                "email": (item.get("email") or "")[:254],
                "mobile": (item.get("mobile") or "")[:30],
                "service": (item.get("service") or "")[:100],
                "message": (item.get("message") or "")[:1000],
                "created_at": _parse_dt(item.get("date")) or timezone.now(),
            },
        )


def _uuid_lookup(value):
    """Return ``{"uuid": value}`` when value is a real UUID, else ``{}``."""
    import uuid as uuid_module

    try:
        return {"uuid": uuid_module.UUID(str(value))}
    except (ValueError, TypeError, AttributeError):
        return {}


def noop(apps, schema_editor):
    """Reverse migration is intentionally a no-op (imported data is kept)."""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(import_data, noop),
    ]
