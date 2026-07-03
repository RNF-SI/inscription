from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings
from django.db import transaction

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application, ApplicationAdmin, UserProfile

logger = logging.getLogger(__name__)


def admin_user_payload(profile: UserProfile) -> dict:
    return {
        "keycloak_sub": profile.keycloak_sub,
        "email": profile.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "username": profile.username,
    }


def list_application_admins(application: Application) -> list[dict]:
    admins = (
        ApplicationAdmin.objects.filter(application=application)
        .select_related("user")
        .order_by("user__email", "user__username")
    )
    return [admin_user_payload(adm.user) for adm in admins]


def ensure_user_profile_from_keycloak(keycloak_sub: str) -> UserProfile | None:
    keycloak_sub = (keycloak_sub or "").strip()
    if not keycloak_sub:
        return None
    existing = UserProfile.objects.filter(keycloak_sub=keycloak_sub).first()
    if existing:
        return existing
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return None
    try:
        kc = KeycloakAdminClient()
        user = kc.get_user(keycloak_sub)
    except KeycloakAdminError as exc:
        logger.warning("Profil Keycloak introuvable pour %s: %s", keycloak_sub, exc)
        return None
    email = (user.get("email") or "").strip().lower()
    if not email:
        return None
    profile, _ = UserProfile.objects.get_or_create(
        keycloak_sub=keycloak_sub,
        defaults={
            "email": email,
            "username": (user.get("username") or email).strip(),
            "first_name": (user.get("firstName") or "").strip(),
            "last_name": (user.get("lastName") or "").strip(),
        },
    )
    profile.email = email
    profile.username = (user.get("username") or profile.username or email).strip()
    profile.first_name = (user.get("firstName") or profile.first_name or "").strip()
    profile.last_name = (user.get("lastName") or profile.last_name or "").strip()
    profile.save(
        update_fields=["email", "username", "first_name", "last_name", "updated_at"],
    )
    return profile


def resolve_user_profile(*, keycloak_sub: str = "", email: str = "") -> UserProfile | None:
    sub = (keycloak_sub or "").strip()
    if sub:
        profile = UserProfile.objects.filter(keycloak_sub=sub).first()
        if profile:
            return profile
        return ensure_user_profile_from_keycloak(sub)
    normalized_email = (email or "").strip().lower()
    if normalized_email:
        return UserProfile.objects.filter(email__iexact=normalized_email).first()
    return None


@transaction.atomic
def replace_application_admins(application: Application, keycloak_subs: Iterable[str]) -> list[dict]:
    wanted = []
    seen: set[str] = set()
    for raw in keycloak_subs:
        sub = (str(raw) or "").strip()
        if not sub or sub in seen:
            continue
        seen.add(sub)
        profile = resolve_user_profile(keycloak_sub=sub)
        if not profile:
            raise ValueError(f"Utilisateur introuvable pour le sub {sub}")
        wanted.append(profile)

    current = {
        adm.user.keycloak_sub: adm
        for adm in ApplicationAdmin.objects.filter(application=application).select_related("user")
    }
    wanted_subs = {profile.keycloak_sub for profile in wanted}

    for sub, adm in current.items():
        if sub not in wanted_subs:
            adm.delete()

    for profile in wanted:
        ApplicationAdmin.objects.get_or_create(application=application, user=profile)

    return list_application_admins(application)


@transaction.atomic
def add_application_admin(
    application: Application,
    *,
    keycloak_sub: str = "",
    email: str = "",
) -> dict:
    profile = resolve_user_profile(keycloak_sub=keycloak_sub, email=email)
    if not profile and (keycloak_sub or "").strip():
        profile = ensure_user_profile_from_keycloak(keycloak_sub)
    if not profile:
        raise ValueError("Utilisateur introuvable")
    ApplicationAdmin.objects.get_or_create(application=application, user=profile)
    return admin_user_payload(profile)


def remove_application_admin(application: Application, keycloak_sub: str) -> None:
    ApplicationAdmin.objects.filter(
        application=application,
        user__keycloak_sub=keycloak_sub,
    ).delete()
