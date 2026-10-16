"""
Secure, time-limited password recovery and password-change services.

Security properties:
* A reset is never allowed from a username alone - the user must be able to
  receive a code at an email address on file, or (for employees) have their
  password reset by an administrator.
* The emailed code is stored only as a salted Django password hash. It is
  single-use, expires after ``PASSWORD_RESET_CODE_TTL_MINUTES`` and is burned
  after ``PASSWORD_RESET_MAX_ATTEMPTS`` wrong guesses.
* Verifying a code returns a short-lived opaque *ticket* (also stored hashed).
  Only a valid, unexpired ticket may set a new password.
* Plaintext passwords are never written to the database or to any log.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils import timezone

from .models import AuthToken, PasswordResetCode, User


class ResetError(Exception):
    """Raised with a user-safe message when a reset step cannot proceed."""


def _hash(value: str) -> str:
    from django.contrib.auth.hashers import make_password

    return make_password(value)


def _verify(value: str, hashed: str) -> bool:
    from django.contrib.auth.hashers import check_password

    return bool(value) and check_password(value, hashed)


def _send_code_email(user: User, code: str, purpose: str) -> None:
    ttl = settings.PASSWORD_RESET_CODE_TTL_MINUTES
    portal = "administrator" if purpose == PasswordResetCode.Purpose.ADMIN_RESET else "employee"
    subject = "Ecronx attendance password reset code"
    body = (
        f"Hello {user.full_name or user.username},\n\n"
        f"A password reset was requested for your Ecronx {portal} account "
        f"({user.username}).\n\n"
        f"Your verification code is: {code}\n\n"
        f"This code expires in {ttl} minutes and can be used once. If you did "
        f"not request a reset, ignore this email and your password will stay "
        f"unchanged.\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)


def request_reset(*, username: str, purpose: str = PasswordResetCode.Purpose.ADMIN_RESET) -> None:
    """
    Begin a reset by emailing a code. Always succeeds silently for unknown
    usernames so the endpoint cannot be used to enumerate accounts.
    """
    user = User.objects.filter(username=username.strip().lower(), is_active=True).first()
    if user is None:
        return
    if purpose == PasswordResetCode.Purpose.ADMIN_RESET and not user.is_administrator:
        return
    if not user.email:
        # No email on file: caller shows a helpful message, nothing is leaked.
        raise ResetError(
            "No recovery email is on file for this account. Ask another "
            "administrator to reset the password, or add an email in Django admin."
        )

    # Invalidate earlier outstanding codes for this purpose.
    PasswordResetCode.objects.filter(user=user, purpose=purpose, consumed=False).update(
        consumed=True
    )

    code = f"{secrets.randbelow(1_000_000):06d}"
    PasswordResetCode.objects.create(
        user=user,
        purpose=purpose,
        code_hash=_hash(code),
        expires_at=timezone.now() + timezone.timedelta(
            minutes=settings.PASSWORD_RESET_CODE_TTL_MINUTES
        ),
    )
    _send_code_email(user, code, purpose)


def verify_reset_code(
    *, username: str, code: str, purpose: str = PasswordResetCode.Purpose.ADMIN_RESET
) -> str:
    """Verify an emailed code and return a one-time reset ticket."""
    user = User.objects.filter(username=username.strip().lower(), is_active=True).first()
    record = (
        PasswordResetCode.objects.filter(user=user, purpose=purpose, consumed=False)
        .order_by("-created_at")
        .first()
        if user
        else None
    )
    if record is None or record.is_expired:
        raise ResetError("That code is invalid or has expired. Request a new code.")

    if record.attempts >= settings.PASSWORD_RESET_MAX_ATTEMPTS:
        record.consumed = True
        record.save(update_fields=["consumed"])
        raise ResetError("Too many incorrect attempts. Request a new code.")

    if not _verify(code.strip(), record.code_hash):
        record.attempts += 1
        record.save(update_fields=["attempts"])
        remaining = max(0, settings.PASSWORD_RESET_MAX_ATTEMPTS - record.attempts)
        raise ResetError(f"That code is incorrect. {remaining} attempt(s) remaining.")

    ticket = secrets.token_urlsafe(32)
    record.ticket_hash = _hash(ticket)
    record.ticket_expires_at = timezone.now() + timezone.timedelta(
        minutes=settings.PASSWORD_RESET_TICKET_TTL_MINUTES
    )
    record.save(update_fields=["ticket_hash", "ticket_expires_at"])
    return ticket


def set_password_with_code(
    *, username: str, code: str, ticket: str, new_password: str, confirm: str
) -> None:
    """Complete a reset: re-check the code, verify the ticket, then set the password."""
    if new_password != confirm:
        raise ResetError("The two passwords do not match.")

    user = User.objects.filter(username=username.strip().lower(), is_active=True).first()
    record = (
        PasswordResetCode.objects.filter(user=user, purpose=PasswordResetCode.Purpose.ADMIN_RESET)
        .order_by("-created_at")
        .first()
        if user
        else None
    )
    if record is None or record.consumed:
        raise ResetError("This reset request is no longer valid. Please start again.")
    if not record.ticket_hash or not record.ticket_expires_at:
        raise ResetError("Verify the emailed code before setting a new password.")
    if timezone.now() >= record.ticket_expires_at:
        raise ResetError("Your verification has expired. Please request a new code.")
    if not _verify(ticket, record.ticket_hash):
        raise ResetError("Your verification is invalid. Please verify the code again.")
    if not _verify(code.strip(), record.code_hash):
        raise ResetError("That code is incorrect. Please request a new code.")

    _apply_new_password(user, new_password)
    record.consumed = True
    record.ticket_hash = ""
    record.save(update_fields=["consumed", "ticket_hash"])


def _apply_new_password(user: User, new_password: str) -> None:
    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise ResetError(" ".join(exc.messages)) from exc
    user.set_password(new_password)  # Django hashing.
    user.save(update_fields=["password"])
    # Force a fresh sign-in everywhere after a password change.
    AuthToken.objects.filter(user=user).delete()


def change_password(*, user: User, current_password: str, new_password: str, confirm: str) -> None:
    """Self-service password change for a signed-in user."""
    if not user.check_password(current_password):
        raise ResetError("Your current password is incorrect.")
    if new_password != confirm:
        raise ResetError("The two passwords do not match.")
    if new_password == current_password:
        raise ResetError("Choose a password different from your current one.")
    _apply_new_password(user, new_password)


def admin_reset_employee_password(*, admin: User, employee: User, new_password: str) -> None:
    """An administrator sets a new password for an employee."""
    if not admin.is_administrator:
        raise ResetError("Only an administrator can reset an employee password.")
    if employee.role != User.Role.EMPLOYEE:
        raise ResetError("Use password recovery for administrator accounts.")
    _apply_new_password(employee, new_password)
