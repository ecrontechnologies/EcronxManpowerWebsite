"""
Django settings for the Ecronx Manpower backend.

The Django backend is the system of record for employee/admin accounts,
attendance, sites, correction requests and website content. Configuration is
read from a .env file (see django_backend/.env.example) or real environment
variables. No secret is ever hard-coded here.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load django_backend/.env first, then the repository-root .env if present.
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env")


def env_str(name: str, default: str = "") -> str:
    """Read a string setting, treating missing OR blank values as unset."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --- Core -------------------------------------------------------------------
# In production set DJANGO_SECRET_KEY to a long random value and keep it secret.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me-before-deploying",
)
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Correctly detect secure HTTPS requests behind a proxy/tunnel.
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:4173,http://127.0.0.1:4173",
)

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
]

# WhiteNoise serves collected static files directly from the WSGI app so the
# Django admin looks correct in production without a separate web server.
try:
    import whitenoise  # noqa: F401

    _HAS_WHITENOISE = True
except ImportError:  # local dev without the prod extra installed
    _HAS_WHITENOISE = False

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Must sit directly below SecurityMiddleware per WhiteNoise docs.
    *(["whitenoise.middleware.WhiteNoiseMiddleware"] if _HAS_WHITENOISE else []),
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Must sit ABOVE CsrfViewMiddleware so the flag is set before it runs.
    "accounts.middleware.ApiCsrfExemptMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ecronx.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ecronx.wsgi.application"

# --- Database ---------------------------------------------------------------
# Default is SQLite so the project runs out of the box. Point DJANGO_DB_ENGINE
# at postgresql/mysql for a production database (see README-DJANGO.md).
#
# On hosts like Render/Railway/Heroku a DATABASE_URL is injected automatically;
# when present it takes precedence so no per-variable DB config is needed.
DB_ENGINE = env_str("DJANGO_DB_ENGINE", "sqlite").lower()
DATABASE_URL = env_str("DATABASE_URL", "")

if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=not DEBUG,
        )
    }
elif DB_ENGINE in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "ecronx"),
            "USER": os.environ.get("DJANGO_DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DJANGO_DB_PORT", "5432"),
            "OPTIONS": {
    "ssl": {"ca": os.environ.get("DJANGO_DB_SSL_CA")}
    if os.environ.get("DJANGO_DB_SSL_CA")
    else {},
},
        }
    }
elif DB_ENGINE in {"mysql", "mariadb"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DJANGO_DB_NAME", "ecronx"),
            "USER": os.environ.get("DJANGO_DB_USER", "root"),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("DJANGO_DB_PORT", "3306"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env_str("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }

# --- Authentication ---------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Django hashes passwords with PBKDF2-SHA256 by default. Password hashing is
# never configurable to "none"; plaintext passwords are never stored.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# --- REST framework (API) ---------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.BearerTokenAuthentication",
        "accounts.authentication.CsrfExemptSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "accounts.exceptions.api_exception_handler",
    "UNAUTHENTICATED_USER": None,
    # Our API uses ?format=json|csv|pdf as a *report* selector for the backup
    # endpoint. DRF's URL_FORMAT_OVERRIDE would otherwise hijack that query
    # parameter for content negotiation and fail with 404 "Not found.".
    "URL_FORMAT_OVERRIDE": None,
}

# --- Sessions & token lifetime ---------------------------------------------
# API bearer tokens (their own model) and Django admin sessions.
TOKEN_TTL_HOURS = int(os.environ.get("TOKEN_TTL_HOURS", "12"))
SESSION_COOKIE_AGE = TOKEN_TTL_HOURS * 60 * 60

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # admin JS reads the token
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- CORS -------------------------------------------------------------------
# Only the existing frontend origins may call these APIs.
CORS_ALLOWED_ORIGINS = env_list(
    "DJANGO_CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:4173,http://127.0.0.1:4173",
)
CORS_ALLOW_CREDENTIALS = True

# --- Email (administrator password recovery) --------------------------------
# Password recovery sends a time-limited 6-digit code. Configure real SMTP
# credentials in .env for production; the console backend is a local fallback.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(os.environ.get("DJANGO_EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL", "Ecronx Attendance <no-reply@ecronxtechnologies.com>"
)

# How long an emailed verification code stays valid (minutes).
PASSWORD_RESET_CODE_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_CODE_TTL_MINUTES", "15"))
# How long a verified reset ticket stays valid (minutes).
PASSWORD_RESET_TICKET_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_TICKET_TTL_MINUTES", "15"))
# Max code verification attempts before a code is burned.
PASSWORD_RESET_MAX_ATTEMPTS = int(os.environ.get("PASSWORD_RESET_MAX_ATTEMPTS", "5"))

ATTENDANCE_TIME_ZONE = os.environ.get("ATTENDANCE_TIME_ZONE", "Asia/Kolkata")

# --- Localisation -----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

# --- Static & media ---------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# WhiteNoise: compress and cache-bust static files in production.
if _HAS_WHITENOISE:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    WHITENOISE_MAX_AGE = 31536000

# Trust the proxy headers set by the hosting platform (Render/Railway).
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Logging ----------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}
