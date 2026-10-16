"""
Serializers producing the exact JSON shapes the existing frontend consumes.

These are deliberately written by hand (instead of ModelSerializer with nested
source mapping) so the ``id`` fields are the stable UUIDs the frontend already
uses for employees, sites, records and corrections.
"""

from __future__ import annotations

from datetime import timezone as dt_timezone

from django.utils import timezone
from rest_framework import serializers

from .models import (
    AttendanceRecord,
    CorrectionRequest,
    Enquiry,
    GalleryImage,
    Service,
    Site,
    SiteSettings,
    User,
)


def iso(value):
    """ISO-8601 string with 'Z' (matching ``new Date().toISOString()``) or None."""
    if value is None:
        return None
    # NOTE: django.utils.timezone.utc was removed in Django 5; use stdlib UTC.
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class UserSummarySerializer(serializers.ModelSerializer):
    """Public, non-sensitive employee summary (never exposes password fields)."""

    id = serializers.UUIDField(source="uuid", read_only=True)
    name = serializers.CharField(source="full_name", read_only=True)
    siteId = serializers.SerializerMethodField()
    active = serializers.BooleanField(source="is_active", read_only=True)
    createdAt = serializers.DateTimeField(source="date_joined", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "name", "siteId", "active", "createdAt"]

    def get_siteId(self, obj) -> str:
        return str(obj.site.uuid) if obj.site_id else ""


class AdminUserSerializer(UserSummarySerializer):
    """Admin listing that also shows role and sites."""

    role = serializers.CharField(read_only=True)
    siteName = serializers.SerializerMethodField()
    lastLogin = serializers.DateTimeField(source="last_login", read_only=True)
    email = serializers.EmailField(read_only=True)

    class Meta(UserSummarySerializer.Meta):
        fields = UserSummarySerializer.Meta.fields + ["role", "siteName", "lastLogin", "email"]

    def get_siteName(self, obj) -> str:
        return f"{obj.site.client} / {obj.site.name}" if obj.site_id else ""


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------
class SiteSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Site
        fields = ["id", "client", "name", "address", "createdAt"]


class SiteCreateSerializer(serializers.Serializer):
    client = serializers.CharField(max_length=120, trim_whitespace=True)
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    address = serializers.CharField(
        max_length=250, required=False, allow_blank=True, default="", trim_whitespace=True
    )

    def validate_client(self, value):
        if not value.strip():
            raise serializers.ValidationError("Client name is required.")
        return value.strip()

    def validate_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Site name must be at least 2 characters.")
        return value.strip()


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
def location_payload(
    timestamp, latitude, longitude, accuracy, address
):
    if timestamp is None and latitude is None and longitude is None:
        return None
    payload = {"timestamp": iso(timestamp)}
    if latitude is not None and longitude is not None:
        payload.update(
            {
                "latitude": latitude,
                "longitude": longitude,
                "accuracy": accuracy,
                "address": address or None,
            }
        )
    return payload


class AttendanceRecordSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    employeeId = serializers.SerializerMethodField()
    employeeName = serializers.CharField(source="employee_name", read_only=True)
    username = serializers.CharField(read_only=True)
    siteId = serializers.SerializerMethodField()
    siteName = serializers.CharField(source="site_name", read_only=True)
    date = serializers.DateField(format="%Y-%m-%d", read_only=True)
    checkIn = serializers.SerializerMethodField()
    checkOut = serializers.SerializerMethodField()
    leaveNote = serializers.CharField(source="leave_note", read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = [
            "id", "employeeId", "employeeName", "username", "siteId", "siteName",
            "date", "status", "checkIn", "checkOut", "source", "leaveNote",
        ]

    def get_employeeId(self, obj) -> str:
        return str(obj.employee.uuid) if obj.employee_id else ""

    def get_siteId(self, obj) -> str:
        return str(obj.site.uuid) if obj.site_id else ""

    def get_checkIn(self, obj):
        return location_payload(
            obj.check_in_at,
            obj.check_in_latitude,
            obj.check_in_longitude,
            obj.check_in_accuracy,
            obj.check_in_address,
        )

    def get_checkOut(self, obj):
        return location_payload(
            obj.check_out_at,
            obj.check_out_latitude,
            obj.check_out_longitude,
            obj.check_out_accuracy,
            obj.check_out_address,
        )


class CorrectionRequestSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    employeeId = serializers.SerializerMethodField()
    employeeName = serializers.CharField(source="employee_name", read_only=True)
    date = serializers.DateField(format="%Y-%m-%d", read_only=True)
    requestedCheckIn = serializers.SerializerMethodField()
    requestedCheckOut = serializers.SerializerMethodField()
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    reviewedAt = serializers.DateTimeField(source="reviewed_at", read_only=True)
    reviewNote = serializers.CharField(source="review_note", read_only=True)

    class Meta:
        model = CorrectionRequest
        fields = [
            "id", "employeeId", "employeeName", "date", "requestedCheckIn",
            "requestedCheckOut", "note", "status", "submittedAt", "reviewedAt", "reviewNote",
        ]

    def get_employeeId(self, obj) -> str:
        return str(obj.employee.uuid) if obj.employee_id else ""

    def get_requestedCheckIn(self, obj):
        return iso(obj.requested_check_in)

    def get_requestedCheckOut(self, obj):
        return iso(obj.requested_check_out)


# ---------------------------------------------------------------------------
# Website content
# ---------------------------------------------------------------------------
class SiteSettingsSerializer(serializers.ModelSerializer):
    companyName = serializers.CharField(source="company_name")
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = SiteSettings
        fields = ["companyName", "tagline", "phone", "whatsapp", "email", "address", "updatedAt"]


class ServiceSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)

    class Meta:
        model = Service
        fields = ["id", "name", "description", "image", "active"]


class GalleryImageSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)

    class Meta:
        model = GalleryImage
        fields = ["id", "title", "category", "image"]


class EnquirySerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="uuid", read_only=True)
    date = serializers.DateTimeField(source="created_at", read_only=True)
    service = serializers.CharField()
    mobile = serializers.CharField(max_length=30)

    class Meta:
        model = Enquiry
        fields = ["id", "name", "email", "mobile", "service", "message", "date"]
