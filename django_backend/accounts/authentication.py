"""
Database-backed bearer-token authentication for the JSON API.

The existing frontend sends ``Authorization: Bearer <token>``. Tokens are now
rows in the ``AuthToken`` table (not server memory), so they survive a restart
and carry an explicit expiry plus the owning user's role.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import AuthToken


class BearerTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate ``Authorization: Bearer <key>`` against the AuthToken table."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != self.keyword.lower().encode():
            return None  # Not our scheme - let Django session auth try (admin panel).
        if len(header) == 1:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")
        if len(header) > 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")

        try:
            key = header[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Invalid token encoding.") from exc

        token = (
            AuthToken.objects.select_related("user")
            .filter(key=key)
            .first()
        )
        if token is None:
            raise exceptions.AuthenticationFailed("Your session has expired. Please log in again.")
        if token.is_expired:
            token.delete()
            raise exceptions.AuthenticationFailed("Your session has expired. Please log in again.")
        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("This account is no longer active.")

        # Refresh the token so active users are not logged out mid-shift.
        token.expires_at = timezone.now() + timezone.timedelta(
            hours=int(__import__("django.conf", fromlist=["settings"]).settings.TOKEN_TTL_HOURS)
        )
        token.save(update_fields=["expires_at"])
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword


class CsrfExemptSessionAuthentication(authentication.SessionAuthentication):
    """
    Session auth for the Django admin *without* CSRF enforcement.

    The JSON API is consumed by a separate static frontend that authenticates
    with a bearer token, not a session cookie, so CSRF does not apply. The
    Django admin panel keeps full CSRF protection through Django's own
    middleware (CsrfViewMiddleware), which is unaffected by this class.
    """

    def enforce_csrf(self, request):
        return None


def issue_token(user) -> AuthToken:
    """Create a fresh token for a user, replacing any previous tokens."""
    from django.conf import settings
    import secrets

    AuthToken.objects.filter(user=user).delete()
    return AuthToken.objects.create(
        key=secrets.token_hex(32),
        user=user,
        expires_at=timezone.now() + timezone.timedelta(hours=settings.TOKEN_TTL_HOURS),
    )
