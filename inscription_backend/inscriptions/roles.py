from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application
from inscriptions.user_identity import admin_user_payload, fetch_user_info, resolve_user_sub

logger = logging.getLogger(__name__)


def _applications_root() -> str:
    return (getattr(settings, "KEYCLOAK_GROUP_APPLICATIONS", "applications") or "applications").strip("/")


def _super_admin_root() -> str:
    return (getattr(settings, "KEYCLOAK_GROUP_SUPER_ADMIN", "super-admin") or "super-admin").strip("/")


def normalize_group_paths(groups: Iterable[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in groups or []:
        if not isinstance(raw, str):
            continue
        path = raw.strip()
        if not path:
            continue
        out.add(path)
        out.add(path.lstrip("/"))
        if not path.startswith("/"):
            out.add(f"/{path}")
    return out


def super_admin_group_paths() -> set[str]:
    root = _super_admin_root()
    return {root, f"/{root}"}


def application_admin_group_paths(slug: str) -> set[str]:
    root = _applications_root()
    slug = (slug or "").strip()
    return {
        f"/{root}/{slug}/admin",
        f"{root}/{slug}/admin",
    }


def is_super_admin(groups: Iterable[str] | None) -> bool:
    return bool(normalize_group_paths(groups).intersection(super_admin_group_paths()))


def effective_groups_from_claims(claims: dict, keycloak_sub: str) -> list[str]:
    """Groupes du JWT, ou chargés via l'API Keycloak si absents du token."""
    raw = claims.get("groups") or []
    if isinstance(raw, list):
        groups = [g.strip() for g in raw if isinstance(g, str) and g.strip()]
        if groups:
            return groups
    if not settings.KEYCLOAK_SYNC_ENABLED or not (keycloak_sub or "").strip():
        return []
    try:
        kc = KeycloakAdminClient()
        paths: list[str] = []
        for group in kc.get_user_groups(keycloak_sub):
            path = (group.get("path") or "").strip()
            if path:
                paths.append(path.lstrip("/"))
        return paths
    except KeycloakAdminError as exc:
        logger.warning("Impossible de charger les groupes Keycloak pour %s: %s", keycloak_sub, exc)
        return []


def groups_for_request(request) -> list[str]:
    from inscriptions.authentication import KeycloakUser

    user = getattr(request, "user", None)
    if not isinstance(user, KeycloakUser):
        return []
    cached = getattr(request, "_effective_kc_groups", None)
    if cached is not None:
        return cached
    groups = effective_groups_from_claims(user.claims, user.sub)
    request._effective_kc_groups = groups
    return groups


def is_app_admin(groups: Iterable[str] | None, application: Application | str) -> bool:
    if is_super_admin(groups):
        return True
    slug = application.slug if isinstance(application, Application) else str(application)
    return bool(normalize_group_paths(groups).intersection(application_admin_group_paths(slug)))


def admin_application_slugs(groups: Iterable[str] | None) -> set[str]:
    if is_super_admin(groups):
        return set(Application.objects.values_list("slug", flat=True))
    root = _applications_root()
    prefix = f"/{root}/"
    slugs: set[str] = set()
    for g in normalize_group_paths(groups):
        path = g if g.startswith("/") else f"/{g}"
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :].strip("/")
        parts = [p for p in remainder.split("/") if p]
        if len(parts) == 2 and parts[1] == "admin":
            slugs.add(parts[0])
    return slugs


def _list_group_member_subs(group_id: str) -> list[str]:
    kc = KeycloakAdminClient()
    subs: list[str] = []
    for member in kc.list_group_members(group_id):
        sub = (member.get("id") or "").strip()
        if sub:
            subs.append(sub)
    return subs


def list_super_admin_subs() -> list[str]:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return []
    try:
        kc = KeycloakAdminClient()
        group_id = kc.ensure_super_admin_group()
        return _list_group_member_subs(group_id)
    except KeycloakAdminError as exc:
        logger.warning("Impossible de lister les super-admins Keycloak: %s", exc)
        return []


def list_application_admin_subs(application: Application) -> list[str]:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return []
    try:
        kc = KeycloakAdminClient()
        group_id = kc.ensure_application_admin_group(application.slug)
        return _list_group_member_subs(group_id)
    except KeycloakAdminError as exc:
        logger.warning("Impossible de lister les admins de %s: %s", application.slug, exc)
        return []


def list_application_admins(application: Application) -> list[dict]:
    admins: list[dict] = []
    for sub in list_application_admin_subs(application):
        info = fetch_user_info(sub)
        if info:
            admins.append(admin_user_payload(info))
        else:
            admins.append(
                {
                    "keycloak_sub": sub,
                    "email": "",
                    "first_name": "",
                    "last_name": "",
                    "username": sub,
                }
            )
    admins.sort(key=lambda row: (row.get("email") or row.get("username") or row.get("keycloak_sub") or "").lower())
    return admins


def _ensure_user_exists(sub: str):
    info = fetch_user_info(sub)
    if not info:
        raise ValueError(f"Utilisateur introuvable pour le sub {sub}")
    return info


def replace_application_admins(application: Application, keycloak_subs: Iterable[str]) -> list[dict]:
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in keycloak_subs:
        sub = (str(raw) or "").strip()
        if not sub or sub in seen:
            continue
        seen.add(sub)
        _ensure_user_exists(sub)
        wanted.append(sub)

    if not settings.KEYCLOAK_SYNC_ENABLED:
        raise ValueError("Synchronisation Keycloak désactivée")

    kc = KeycloakAdminClient()
    group_id = kc.ensure_application_admin_group(application.slug)
    current = set(list_application_admin_subs(application))
    wanted_set = set(wanted)

    for sub in current - wanted_set:
        kc.user_leave_group(sub, group_id)
    for sub in wanted_set - current:
        kc.user_join_group(sub, group_id)

    return list_application_admins(application)


def add_application_admin(
    application: Application,
    *,
    keycloak_sub: str = "",
    email: str = "",
) -> dict:
    sub = resolve_user_sub(keycloak_sub=keycloak_sub, email=email)
    if not sub:
        raise ValueError("Utilisateur introuvable")
    info = _ensure_user_exists(sub)
    if settings.KEYCLOAK_SYNC_ENABLED:
        kc = KeycloakAdminClient()
        group_id = kc.ensure_application_admin_group(application.slug)
        if sub not in set(list_application_admin_subs(application)):
            kc.user_join_group(sub, group_id)
    return admin_user_payload(info)


def remove_application_admin(application: Application, keycloak_sub: str) -> None:
    sub = (keycloak_sub or "").strip()
    if not sub or not settings.KEYCLOAK_SYNC_ENABLED:
        return
    kc = KeycloakAdminClient()
    group_id = kc.ensure_application_admin_group(application.slug)
    kc.user_leave_group(sub, group_id)


def _application_admin_group_path(slug: str) -> str:
    return f"/{_applications_root()}/{(slug or '').strip()}/admin"


def count_application_admins(application: Application, kc: KeycloakAdminClient | None = None) -> int | None:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return None
    try:
        client = kc or KeycloakAdminClient()
        group = client.find_group_by_path(_application_admin_group_path(application.slug))
        if not group or not group.get("id"):
            return 0
        return client.count_group_members(group["id"])
    except KeycloakAdminError:
        return None


def notify_recipient_subs_for_removal_request() -> list[str]:
    subs: set[str] = set(list_super_admin_subs())
    for app in Application.objects.all().only("slug"):
        subs.update(list_application_admin_subs(app))
    return sorted(subs)
