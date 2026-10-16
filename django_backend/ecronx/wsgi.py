"""WSGI entry point for the Ecronx Django backend."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ecronx.settings")

application = get_wsgi_application()
