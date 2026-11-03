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
    # Fail-safe : une vue sans permission_classes explicite exige un JWT Keycloak.
    # Les vues publiques (register, keycloak-config, catalogue…) déclarent
    # `authentication_classes = []` + `permission_classes = []`.
    "DEFAULT_PERMISSION_CLASSES": [
        "inscriptions.permissions.IsKeycloakAuthenticated",
    ],
    # Seule la route de contact est limitée (scope "contact"), via ScopedRateThrottle.
    "DEFAULT_THROTTLE_RATES": {
        "contact": env("CONTACT_THROTTLE_RATE", default="10/hour"),
        # Route publique : limiter freine autant le harcèlement d'une boîte mail
        # que la recherche d'adresses valides.
        "password_reset": env("PASSWORD_RESET_THROTTLE_RATE", default="5/hour"),
    },
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
KEYCLOAK_GROUP_SUPER_ADMIN = env("KEYCLOAK_GROUP_SUPER_ADMIN", default="super-admin")

KEYCLOAK_SYNC_ENABLED = env.bool("KEYCLOAK_SYNC_ENABLED", default=bool(KEYCLOAK_ADMIN_CLIENT_SECRET))
# Délai des appels HTTP vers Keycloak, sur le chemin synchrone des requêtes API.
KEYCLOAK_HTTP_TIMEOUT = env.int("KEYCLOAK_HTTP_TIMEOUT", default=10)

# Tolérance d'écart d'horloge à la validation des jetons, en secondes. Le défaut
# doit rester celui d'authentication.DEFAULT_KEYCLOAK_LEEWAY (60 s), qui porte
# l'arbitrage et sert de repli ; c'est aussi celui de RADIS, qui valide les mêmes
# jetons. Lu sans env.int() : une valeur illisible ne doit pas empêcher Django de
# démarrer, get_keycloak_leeway() retombe sur le défaut.
KEYCLOAK_LEEWAY = env("KEYCLOAK_LEEWAY", default=60)

FRONTEND_PUBLIC_URL = env("FRONTEND_PUBLIC_URL", default="http://localhost:4200")

# Durée de validité d'un lien de réinitialisation de mot de passe.
PASSWORD_RESET_TTL_MINUTES = env.int("PASSWORD_RESET_TTL_MINUTES", default=60)
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
SUPERADMIN_NOTIFY_EMAILS = env.list("SUPERADMIN_NOTIFY_EMAILS", default=[])

# Prévenir les référents d'une réserve qu'un membre vient de la rejoindre (notification
# in-app + e-mail). Coupé par défaut le temps de la bascule : chaque compte repris de
# la base historique rejoint ses réserves, et un référent de réserve très peuplée
# recevrait la pile d'un coup. À rallumer quand le parcours sera éprouvé — le jour où
# ces notifications ne concerneront plus que de vraies arrivées.
RESERVE_NEW_MEMBER_NOTIFY_ENABLED = env.bool("RESERVE_NEW_MEMBER_NOTIFY_ENABLED", default=False)

# Formulaire de contact mutualisé (toutes les apps home-rnf).
# Liste blanche des destinataires acceptés : le client indique l'adresse voulue
# (boîtes Zammad), mais une adresse hors de cette liste est refusée — sans quoi
# la route serait un relais SMTP ouvert vers n'importe quelle adresse.
CONTACT_ALLOWED_RECIPIENTS = [
    email.strip().lower() for email in env.list("CONTACT_ALLOWED_RECIPIENTS", default=[]) if email.strip()
]

LEGACY_DATABASE_URL = env("LEGACY_DATABASE_URL", default="").strip()

if LEGACY_DATABASE_URL:
    DATABASES["legacy"] = env.db_url_config(LEGACY_DATABASE_URL)
    # La base historique n'a aucune table Django : son schéma appartient à
    # geonature_global, et toutes les écritures passent par du SQL brut.
    #
    # Sans ce réglage, le lanceur de tests de Django y applique quand même les
    # migrations de l'app — il crée une base de test par alias, et faute de
    # DATABASE_ROUTERS rien ne l'en dissuade. La migration de données 0003 échoue
    # alors : elle interroge « default », déjà migrée jusqu'au bout, avec un modèle
    # historique de l'état 0003 qui attend encore la colonne decided_by_id.
    # C'est ce qui empêchait test_legacy_integration de démarrer.
    #
    # En production la question ne se pose pas : « manage.py migrate » sans
    # --database ne migre que « default ».
    DATABASES["legacy"].setdefault("TEST", {})["MIGRATE"] = False

# Écriture miroir vers la base historique (schémas utilisateurs / complement_rnf).
# Tant que les applications RNF lisent leurs comptes dans cette base, toute mutation
# faite ici doit y être répercutée, sinon l'inscription ne produit plus rien pour elles.
# Désactivable pour diagnostiquer sans écrire ; sans LEGACY_DATABASE_URL il n'y a de
# toute façon pas de connexion "legacy".
LEGACY_WRITE_ENABLED = env.bool("LEGACY_WRITE_ENABLED", default=bool(LEGACY_DATABASE_URL))

# utilisateurs.t_roles porte deux colonnes de mot de passe : pass_plus (bcrypt, utilisée
# par les versions récentes de pypnusershub) et pass (md5, héritée). Vérifier côté base
# si le parc en dépend encore avant d'activer :
#   SELECT count(*) FROM utilisateurs.t_roles WHERE pass IS NOT NULL;
# Les comptes récents de la base de production portent presque tous un md5 : la
# colonne est toujours alimentée aujourd'hui, pas un résidu. Ne pas l'écrire ferait
# diverger les comptes créés ici de ceux créés par UsersHub.
LEGACY_WRITE_PASS_MD5 = env.bool("LEGACY_WRITE_PASS_MD5", default=True)

# Groupes (utilisateurs.cor_roles) auxquels tout compte créé est rattaché.
# Sur l'installation RNF, 69 est « Grp_all », que porte la quasi-totalité des comptes
# actifs : l'omettre priverait les nouveaux inscrits de ce que ce groupe confère.
LEGACY_DEFAULT_GROUP_IDS = [
    int(v) for v in env.list("LEGACY_DEFAULT_GROUP_IDS", default=["69"]) if str(v).strip()
]

# utilisateurs.t_applications.id_application de la plateforme d'inscription.
# Désactivé par défaut : la base de production ne montre qu'une seule ligne INS, créée
# en 2023, et aucune depuis 2025 — cor_role_app_profil n'est plus alimenté à la
# validation, ce sont les groupes qui portent les droits. Mettre 6 pour le rétablir.
LEGACY_INSCRIPTION_APP_ID = env.int("LEGACY_INSCRIPTION_APP_ID", default=0)

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
