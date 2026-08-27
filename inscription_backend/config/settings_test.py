"""Configuration Django pour les tests (SQLite, Keycloak désactivé par défaut)."""

from pathlib import Path

from .settings import *  # noqa: F401,F403

BASE_DIR = Path(__file__).resolve().parent.parent

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Les tests ne doivent JAMAIS joindre un vrai Keycloak : settings.py lit le .env du
# développeur, et un test qui active KEYCLOAK_SYNC_ENABLED sans patcher tous les points
# d'entrée partait sinon sur le serveur réel (30 s de timeout, résultats dépendant de
# l'ordre d'exécution). Hôte non routable + timeout court = échec immédiat et déterministe.
KEYCLOAK_BASE_URL = "http://127.0.0.1:9"
KEYCLOAK_HTTP_TIMEOUT = 1
KEYCLOAK_SYNC_ENABLED = False
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SUPERADMIN_NOTIFY_EMAILS = ["admin@test.local"]

APPLICATION_IMAGES_DIR = str(BASE_DIR / "media" / "application-images")

# Évite les avertissements sur les mots de passe faibles en tests.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Realm lu depuis .env — en dev local, pointez KEYCLOAK_REALM vers votre realm de test.
_FORBIDDEN_TEST_REALMS = {"rnf", "si-rnf", "master", "production", "prod"}
if KEYCLOAK_REALM.lower() in _FORBIDDEN_TEST_REALMS:
    import warnings

    warnings.warn(
        f"KEYCLOAK_REALM={KEYCLOAK_REALM!r} ressemble à un realm de prod. "
        "Les tests unitaires n'appellent pas Keycloak, mais évitez ce réglage en local.",
        stacklevel=1,
    )

LOGGING = {
    "version": 1,
    "disable_existing_loggers": True,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}
