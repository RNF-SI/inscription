import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, True),
)

environ.Env.read_env(os.path.join(BASE_DIR, ".env"), overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-change-in-production")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "inscriptions",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

_default_sqlite = f"sqlite:///{(BASE_DIR / 'db.sqlite3').as_posix()}"
DATABASES = {"default": env.db("DATABASE_URL", default=_default_sqlite)}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
APPLICATION_IMAGES_DIR = env(
    "APPLICATION_IMAGES_DIR",
    default=str(MEDIA_ROOT / "application-images"),
)

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:4200", "http://127.0.0.1:4200"],
)
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "inscriptions.authentication.KeycloakJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
}

KEYCLOAK_BASE_URL = env("KEYCLOAK_BASE_URL", default="http://localhost:8080").rstrip("/")
# django-environ ne gère pas les commentaires en fin de ligne (# …)
KEYCLOAK_REALM = env("KEYCLOAK_REALM", default="master").split("#", 1)[0].strip()
KEYCLOAK_ADMIN_CLIENT_ID = env("KEYCLOAK_ADMIN_CLIENT_ID", default="admin-cli")
KEYCLOAK_ADMIN_CLIENT_SECRET = env("KEYCLOAK_ADMIN_CLIENT_SECRET", default="").strip()
KEYCLOAK_APP_CLIENT_ID = env("KEYCLOAK_APP_CLIENT_ID", default="inscription-spa")
KEYCLOAK_APP_CLIENT_SECRET = env("KEYCLOAK_APP_CLIENT_SECRET", default="").strip()

KEYCLOAK_GROUP_ORGANISMES = env("KEYCLOAK_GROUP_ORGANISMES", default="organismes")
KEYCLOAK_GROUP_RESERVES = env("KEYCLOAK_GROUP_RESERVES", default="reserves")
KEYCLOAK_GROUP_APPLICATIONS = env("KEYCLOAK_GROUP_APPLICATIONS", default="applications")

KEYCLOAK_SYNC_ENABLED = env.bool("KEYCLOAK_SYNC_ENABLED", default=bool(KEYCLOAK_ADMIN_CLIENT_SECRET))

FRONTEND_PUBLIC_URL = env("FRONTEND_PUBLIC_URL", default="http://localhost:4200")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
SUPERADMIN_NOTIFY_EMAILS = env.list("SUPERADMIN_NOTIFY_EMAILS", default=[])

LEGACY_DATABASE_URL = env("LEGACY_DATABASE_URL", default="").strip()

if LEGACY_DATABASE_URL:
    DATABASES["legacy"] = env.db_url_config(LEGACY_DATABASE_URL)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "inscriptions.keycloak": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
