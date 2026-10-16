"""
URL routes for the accounts API.

Paths intentionally mirror the existing Node.js routes so the current frontend
keeps working unchanged. New password endpoints are added alongside them.
"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("health", views.HealthView.as_view(), name="health"),

    # --- Authentication ----------------------------------------------------
    path("admin/login", views.AdminLoginView.as_view(), name="admin-login"),
    path("admin/logout", views.LogoutView.as_view(), name="admin-logout"),
    path("attendance/employee/login", views.EmployeeLoginView.as_view(), name="employee-login"),
    path("attendance/employee/logout", views.LogoutView.as_view(), name="employee-logout"),
    path("attendance/me", views.MeView.as_view(), name="employee-me"),

    # --- Password change / recovery ----------------------------------------
    path("password/change", views.ChangePasswordView.as_view(), name="password-change"),
    path("password/reset/request", views.PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password/reset/verify", views.PasswordResetVerifyView.as_view(), name="password-reset-verify"),
    path("password/reset/confirm", views.PasswordResetConfirmView.as_view(), name="password-reset-confirm"),

    # --- Employee attendance ------------------------------------------------
    path("attendance/check-in", views.CheckInView.as_view(), name="check-in"),
    path("attendance/check-out", views.CheckOutView.as_view(), name="check-out"),
    path("attendance/corrections", views.CorrectionRequestView.as_view(), name="corrections"),

    # --- Administrator attendance management --------------------------------
    path("attendance/admin/dashboard", views.AdminDashboardView.as_view(), name="admin-dashboard"),
    path("attendance/admin/employees", views.AdminEmployeeCreateView.as_view(), name="admin-employee-create"),
    path(
        "attendance/admin/employees/<uuid:uuid_value>",
        views.AdminEmployeeDetailView.as_view(),
        name="admin-employee-detail",
    ),
    path(
        "attendance/admin/employees/<uuid:uuid_value>/password",
        views.AdminEmployeePasswordResetView.as_view(),
        name="admin-employee-password",
    ),
    path("attendance/admin/sites", views.AdminSiteCreateView.as_view(), name="admin-site-create"),
    path("attendance/admin/leave", views.AdminLeaveView.as_view(), name="admin-leave"),
    path(
        "attendance/admin/corrections/<uuid:uuid_value>",
        views.AdminCorrectionReviewView.as_view(),
        name="admin-correction-review",
    ),
    path("attendance/admin/backup", views.AdminBackupView.as_view(), name="admin-backup"),
    path("admin/enquiries", views.AdminEnquiriesView.as_view(), name="admin-enquiries"),

    # --- Website content ----------------------------------------------------
    path("content", views.ContentView.as_view(), name="content"),
    path("enquiries", views.EnquiryView.as_view(), name="enquiries"),
]
