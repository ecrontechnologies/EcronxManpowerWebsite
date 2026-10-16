"""
Database models for the Ecronx Manpower project.

Every account, attendance record, site, correction request and piece of
website content lives here. Passwords are always stored as Django password
hashes (PBKDF2-SHA256 by default) - never as plain text, and there is no API
anywhere that can read an existing password back out.

The model/field names deliberately mirror the JSON contracts the existing
Node.js backend and static frontend already use, so the frontend does not need
to change shape. Each object also exposes a stable public UUID that is used as
the ``id`` in API responses.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

USERNAME_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9._-]{3,40}$",
    message=(
        "Username must be 3-40 characters using only lowercase letters, numbers, "
        "dots, underscores or hyphens."
    ),
)


# ---------------------------------------------------------------------------
# User + manager
# ---------------------------------------------------------------------------
class UserManager(BaseUserManager):
    """Manager for the single custom user model used by admins and employees."""

    use_in_migrations = True

    def _create_user(self, username, password, **extra_fields):
        if not username:
            raise ValueError("A username is required.")
        username = self.model.normalize_username(username.strip().lower())
        user = self.model(username=username, **extra_fields)
        user.set_password(password)  # Django hashing - never plaintext.
        user.full_clean(exclude=None, validate_unique=False)
        user.save(using=self._db)
        return user

    def create_user(self, username, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.EMPLOYEE)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, password, **extra_fields)

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self._create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """An administrator or employee account."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        EMPLOYEE = "employee", "Employee"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    username = models.CharField(max_length=40, unique=True, validators=[USERNAME_VALIDATOR])
    full_name = models.CharField("name", max_length=100, blank=True)
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    is_active = models.BooleanField(
        default=True,
        help_text="Uncheck to deactivate the account. Deactivated accounts cannot sign in.",
    )
    is_staff = models.BooleanField(
        default=False,
        help_text="Allows access to the Django admin panel.",
    )
    site = models.ForeignKey(
        "Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Client/site the employee is allocated to.",
    )
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["role", "username"]
        verbose_name = "account"
        verbose_name_plural = "accounts"

    def __str__(self) -> str:
        return f"{self.full_name or self.username} ({self.get_role_display()})"

    # --- Convenience helpers -------------------------------------------------
    @property
    def is_administrator(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    def save(self, *args, **kwargs):
        self.username = self.username.strip().lower()
        if self.role == self.Role.ADMIN:
            self.is_staff = True
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Sites and attendance
# ---------------------------------------------------------------------------
class Site(models.Model):
    """A client / site an employee can be allocated to."""

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    client = models.CharField(max_length=120)
    name = models.CharField("site name", max_length=120)
    address = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["client", "name"]

    def __str__(self) -> str:
        return f"{self.client} / {self.name}"


class AttendanceRecord(models.Model):
    """One attendance row for one employee on one date."""

    class Status(models.TextChoices):
        PRESENT = "Present", "Present"
        LEAVE = "Leave", "Leave"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance_records"
    )
    # Denormalised snapshot so history survives a rename (matches JSON output).
    employee_name = models.CharField(max_length=100, blank=True)
    username = models.CharField(max_length=40, blank=True)
    site = models.ForeignKey(
        Site, null=True, blank=True, on_delete=models.SET_NULL, related_name="attendance_records"
    )
    site_name = models.CharField(max_length=120, blank=True)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)

    check_in_at = models.DateTimeField(null=True, blank=True)
    check_in_latitude = models.FloatField(null=True, blank=True)
    check_in_longitude = models.FloatField(null=True, blank=True)
    check_in_accuracy = models.FloatField(null=True, blank=True)
    check_in_address = models.CharField(max_length=250, blank=True)

    check_out_at = models.DateTimeField(null=True, blank=True)
    check_out_latitude = models.FloatField(null=True, blank=True)
    check_out_longitude = models.FloatField(null=True, blank=True)
    check_out_accuracy = models.FloatField(null=True, blank=True)
    check_out_address = models.CharField(max_length=250, blank=True)

    correction_approved = models.BooleanField(
        default=False, help_text="True when a check-in/out time came from an approved correction."
    )
    source = models.CharField(max_length=40, blank=True, help_text="gps, admin-correction, admin-leave")
    leave_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employee_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "date"], name="unique_attendance_per_employee_per_date"
            )
        ]
        indexes = [models.Index(fields=["date"]), models.Index(fields=["status"])]

    def __str__(self) -> str:
        return f"{self.date} - {self.employee_name or self.username} ({self.status})"

    # --- Derived helpers used by the API/serializers -------------------------
    @property
    def working_minutes(self):
        if not self.check_in_at or not self.check_out_at:
            return None
        delta = self.check_out_at - self.check_in_at
        return max(0, round(delta.total_seconds() / 60))

    @property
    def is_open(self) -> bool:
        return bool(self.check_in_at and not self.check_out_at)

    @property
    def effective_username(self) -> str:
        return self.username or (self.employee.username if self.employee_id else "")

    def save(self, *args, **kwargs):
        if self.employee_id:
            self.employee_name = self.employee_name or self.employee.full_name
            self.username = self.username or self.employee.username
            if self.site_id is None and self.employee.site_id:
                self.site = self.employee.site
        super().save(*args, **kwargs)


class CorrectionRequest(models.Model):
    """An employee request to correct a check-in/out time, reviewed by an admin."""

    class Status(models.TextChoices):
        PENDING = "Pending", "Pending"
        APPROVED = "Approved", "Approved"
        REJECTED = "Rejected", "Rejected"

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="correction_requests"
    )
    employee_name = models.CharField(max_length=100, blank=True)
    date = models.DateField()
    requested_check_in = models.DateTimeField(null=True, blank=True)
    requested_check_out = models.DateTimeField(null=True, blank=True)
    note = models.TextField(max_length=1000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_corrections",
    )
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.employee_name or self.employee_id} - {self.date} ({self.status})"


class BackupLog(models.Model):
    """Record of a downloaded attendance backup (JSON/CSV/PDF)."""

    created_at = models.DateTimeField(default=timezone.now)
    date_from = models.DateField()
    date_to = models.DateField()
    format = models.CharField(max_length=10)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.format} {self.date_from} -> {self.date_to}"


# ---------------------------------------------------------------------------
# Website content (mirrors backend/data/content.json)
# ---------------------------------------------------------------------------
class SiteSettings(models.Model):
    """Singleton-ish website settings (only the latest row is used)."""

    company_name = models.CharField(max_length=150, default="Ecronx Technologies Pvt Ltd")
    tagline = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    whatsapp = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=250, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "website settings"
        verbose_name_plural = "website settings"

    def __str__(self) -> str:
        return self.company_name


class Service(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=1000, blank=True)
    image = models.CharField(max_length=500, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class GalleryImage(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=120)
    category = models.CharField(max_length=80, default="General")
    image = models.CharField(max_length=500)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "gallery image"

    def __str__(self) -> str:
        return self.title


class Enquiry(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=30)
    service = models.CharField(max_length=100)
    message = models.TextField(max_length=1000, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "enquiries"

    def __str__(self) -> str:
        return f"{self.name} - {self.service}"


# ---------------------------------------------------------------------------
# API tokens (bearer tokens held in the database, not in browser storage)
# ---------------------------------------------------------------------------
class AuthToken(models.Model):
    """A database-backed API token with role + expiry, replacing in-memory sessions."""

    key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_tokens"
    )
    created = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created"]

    def __str__(self) -> str:
        return f"{self.user.username} (expires {self.expires_at:%Y-%m-%d %H:%M})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


# ---------------------------------------------------------------------------
# Password recovery (administrators)
# ---------------------------------------------------------------------------
class PasswordResetCode(models.Model):
    """
    A time-limited, single-use verification code emailed to an administrator.

    The code itself is never stored in the clear: only a salted hash is kept,
    exactly like a password. The code can be verified once (producing a
    short-lived ``ticket``) before a new password may be set.
    """

    class Purpose(models.TextChoices):
        ADMIN_RESET = "admin_reset", "Administrator password reset"
        EMPLOYEE_RESET = "employee_reset", "Employee password reset"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reset_codes"
    )
    purpose = models.CharField(
        max_length=32, choices=Purpose.choices, default=Purpose.ADMIN_RESET
    )
    code_hash = models.CharField(max_length=256)
    ticket_hash = models.CharField(max_length=256, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    consumed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ticket_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user.username} code ({'used' if self.consumed else 'active'})"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at
