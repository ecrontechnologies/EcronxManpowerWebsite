"""Root URL configuration for the Ecronx Django backend."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django admin keeps full CSRF protection (it is session/cookie based).
    path("django-admin/", admin.site.urls),
    # CSRF for /api/* is skipped by accounts.middleware.ApiCsrfExemptMiddleware,
    # because the JSON API is bearer-token based and is called by a separate
    # static frontend that holds no CSRF cookie. Authentication and role checks
    # are still enforced per view.
    path("api/", include("accounts.urls")),
]
