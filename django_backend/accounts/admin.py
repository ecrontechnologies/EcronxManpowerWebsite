"""
Django Admin configuration.

Administrators can view, search, add, update and delete employee accounts,
attendance records, sites, corrections and website content here. Passwords are
never displayed; use the built-in "reset password" action which re-hashes the
new password with Django's security hashers.
"""

from __future__ import annotations

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm, ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import (
    AttendanceRecord,
    AuthToken,
    BackupLog,
    CorrectionRequest,
    Enquiry,
    GalleryImage,
    PasswordResetCode,
    Service,
    Site,
    SiteSettings,
    User,
)


# ---------------------------------------------------------------------------
# Forms (never expose the raw password hash)
# ---------------------------------------------------------------------------
class UserCreationForm(forms.ModelForm):
    """Create a user with a securely hashed password."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, min_length=12)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, min_length=12)

    class Meta:
        model = User
        fields = ("username", "full_name", "email", "role", "site", "is_active", "is_staff")

    def clean_password2(self):
        p1, p2 = self.cleaned_data.get("password1"), self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("The two passwords do not match.")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])  # Django hashing.
        if commit:
            user.save()
        return user


class UserChangeForm(forms.ModelForm):
    """Edit a user; the password is shown as an unreadable hash with a change link."""

    password = ReadOnlyPasswordHashField(
        label="Password",
        help_text=(
            "Passwords are stored only as salted hashes and cannot be viewed or "
            'retrieved. Use "Reset password" to set a new one.'
        ),
    )

    class Meta:
        model = User
        fields = "__all__"


# ---------------------------------------------------------------------------
# User admin (administrators + employees)
# ---------------------------------------------------------------------------
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    change_password_form = AdminPasswordChangeForm
    model = User

    list_display = ("username", "full_name", "role", "site", "email", "is_active", "is_staff", "last_login")
    list_filter = ("role", "is_active", "is_staff", "site")
    search_fields = ("username", "full_name", "email")
    ordering = ("role", "username")
    readonly_fields = ("uuid", "date_joined", "last_login", "password")
    actions = ("activate_accounts", "deactivate_accounts")

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Profile", {"fields": ("full_name", "email", "role", "site")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined", "uuid")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username", "full_name", "email", "role", "site",
                    "password1", "password2", "is_active", "is_staff",
                ),
            },
        ),
    )

    @admin.action(description="Activate selected accounts")
    def activate_accounts(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} account(s) activated.", messages.SUCCESS)

    @admin.action(description="Deactivate selected accounts")
    def deactivate_accounts(self, request, queryset):
        updated = queryset.update(is_active=False)
        AuthToken.objects.filter(user__in=queryset).delete()
        self.message_user(request, f"{updated} account(s) deactivated and signed out.", messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        # Creating/editing via admin uses the form's hashing; ensure admins are staff.
        if obj.role == User.Role.ADMIN:
            obj.is_staff = True
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# Attendance, sites, corrections, backups
# ---------------------------------------------------------------------------
@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("client", "name", "address", "created_at")
    search_fields = ("client", "name", "address")
    ordering = ("client", "name")
    readonly_fields = ("uuid", "created_at")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "date", "employee_name", "username", "status", "site",
        "check_in_at", "check_out_at", "hours_display",
    )
    list_filter = ("status", "date", "site")
    search_fields = ("employee_name", "username", "employee__username")
    date_hierarchy = "date"
    list_select_related = ("employee", "site")
    raw_id_fields = ("employee",)
    readonly_fields = ("uuid", "created_at", "updated_at")

    @admin.display(description="Hours")
    def hours_display(self, obj):
        minutes = obj.working_minutes
        return "—" if minutes is None else f"{minutes / 60:.2f} h"


@admin.register(CorrectionRequest)
class CorrectionRequestAdmin(admin.ModelAdmin):
    list_display = ("date", "employee_name", "status", "submitted_at", "reviewed_at", "reviewed_by")
    list_filter = ("status", "date")
    search_fields = ("employee_name", "employee__username", "note")
    date_hierarchy = "date"
    raw_id_fields = ("employee", "reviewed_by")
    readonly_fields = ("uuid", "submitted_at")
    actions = ("approve_requests", "reject_requests")

    @admin.action(description="Approve selected correction requests")
    def approve_requests(self, request, queryset):
        from django.utils import timezone

        count = 0
        for correction in queryset.filter(status=CorrectionRequest.Status.PENDING):
            record, _ = AttendanceRecord.objects.get_or_create(
                employee=correction.employee,
                date=correction.date,
                defaults={
                    "employee_name": correction.employee_name,
                    "username": correction.employee.username,
                    "status": AttendanceRecord.Status.PRESENT,
                    "source": "admin-correction",
                },
            )
            if correction.requested_check_in:
                record.check_in_at = correction.requested_check_in
            if correction.requested_check_out:
                record.check_out_at = correction.requested_check_out
            record.correction_approved = True
            record.status = AttendanceRecord.Status.PRESENT
            record.save()
            correction.status = CorrectionRequest.Status.APPROVED
            correction.reviewed_at = timezone.now()
            correction.reviewed_by = request.user
            correction.save()
            count += 1
        self.message_user(request, f"{count} correction request(s) approved.", messages.SUCCESS)

    @admin.action(description="Reject selected correction requests")
    def reject_requests(self, request, queryset):
        from django.utils import timezone

        count = 0
        for correction in queryset.filter(status=CorrectionRequest.Status.PENDING):
            correction.status = CorrectionRequest.Status.REJECTED
            correction.reviewed_at = timezone.now()
            correction.reviewed_by = request.user
            correction.save()
            count += 1
        self.message_user(request, f"{count} correction request(s) rejected.", messages.SUCCESS)


@admin.register(BackupLog)
class BackupLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "date_from", "date_to", "format")
    list_filter = ("format",)
    readonly_fields = ("created_at", "date_from", "date_to", "format")

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# Tokens & recovery codes (audit)
# ---------------------------------------------------------------------------
@admin.register(AuthToken)
class AuthTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created", "expires_at", "is_expired")
    list_filter = ("created",)
    search_fields = ("user__username",)
    raw_id_fields = ("user",)
    readonly_fields = ("key", "user", "created", "expires_at")
    actions = ("revoke_tokens",)

    @admin.action(description="Revoke (sign out) selected sessions")
    def revoke_tokens(self, request, queryset):
        deleted, _ = queryset.delete()
        self.message_user(request, f"{deleted} session(s) revoked.", messages.SUCCESS)


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "purpose", "created_at", "expires_at", "attempts", "consumed")
    list_filter = ("purpose", "consumed")
    search_fields = ("user__username",)
    raw_id_fields = ("user",)
    # Hashes are never shown; codes are single-use and expire quickly anyway.
    exclude = ("code_hash", "ticket_hash")

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# Website content
# ---------------------------------------------------------------------------
@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("company_name", "phone", "email", "updated_at")

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("name", "description")
    readonly_fields = ("uuid", "created_at")


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "created_at")
    list_filter = ("category",)
    search_fields = ("title",)
    readonly_fields = ("uuid", "created_at")


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("created_at", "name", "mobile", "service")
    list_filter = ("service",)
    search_fields = ("name", "mobile", "email", "message")
    readonly_fields = ("uuid", "created_at")

    def has_add_permission(self, request):
        return False


admin.site.site_header = "Ecronx Manpower Administration"
admin.site.site_title = "Ecronx Manpower"
admin.site.index_title = "Manage accounts, attendance and website content"
