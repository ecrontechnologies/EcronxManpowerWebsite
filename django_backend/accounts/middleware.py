"""
Middleware that skips CSRF enforcement for the JSON API.

Why this is safe:
* The ``/api/*`` endpoints authenticate with an ``Authorization: Bearer`` token
  stored in the ``AuthToken`` table - not with a browser session cookie. CSRF
  attacks rely on a browser silently attaching credentials (cookies) to a
  cross-site request; a token that the attacker cannot read is not sent that way.
* The Django admin panel (``/django-admin/``) keeps the full
  ``CsrfViewMiddleware`` protection because it *is* session/cookie based.
* All API views still enforce authentication and role checks individually.

If you later switch the frontend to cookie-based sessions, remove this
middleware and send ``X-CSRFToken`` from the client instead.
"""

from __future__ import annotations

from django.conf import settings


class ApiCsrfExemptMiddleware:
    """Mark every request whose path starts with the API prefix as CSRF-exempt."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/api/"):
            # Setting this flag is exactly what django.views.decorators.csrf
            # .csrf_exempt does for a single view.
            request._dont_enforce_csrf_checks = True  # noqa: SLF001
        return self.get_response(request)
