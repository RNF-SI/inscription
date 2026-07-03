from __future__ import annotations

import logging
import math
from typing import Any

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import AccessRequestItem, Application
from inscriptions.services import provisioning as prov

logger = logging.getLogger(__name__)


def si_managed_applications():
    """Applications gérées par le SI (hors apps indépendantes de Keycloak)."""
    return Application.objects.filter(managed_by_si=True).order_by("nom")


def _group_paths(groups: list[dict]) -> set[str]:
    out: set[str] = set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        path = (g.get("path") or "").strip()
        if not path:
            continue
        out.add(path)
        out.add(path.lstrip("/"))
    return out


def user_has_application_access(group_paths: set[str], app: Application) -> bool:
    root = (getattr(settings, "KEYCLOAK_GROUP_APPLICATIONS", "applications") or "applications").strip("/")
    candidates = {
        f"/{root}/{app.slug}",
        f"{root}/{app.slug}",
        app.slug,
    }
    return bool(group_paths.intersection(candidates))


def is_application_access_editable(app: Application) -> bool:
    """Les applications SI sans demande d'accès sont accordées automatiquement."""
    return app.managed_by_si and app.requires_access_request


def application_group_path(slug: str) -> str:
    root = (getattr(settings, "KEYCLOAK_GROUP_APPLICATIONS", "applications") or "applications").strip("/")
    return f"/{root}/{slug}"


def format_keycloak_user(u: dict) -> dict[str, str] | None:
    sub = (u.get("id") or "").strip()
    if not sub:
        return None
    email = (u.get("email") or "").strip()
    first_name = (u.get("firstName") or "").strip()
    last_name = (u.get("lastName") or "").strip()
    username = (u.get("username") or "").strip()
    label_name = f"{first_name} {last_name}".strip()
    label = f"{label_name} ({email or username})" if label_name else (email or username)
    return {
        "keycloak_sub": sub,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "username": username,
        "label": label,
    }


def member_matches_query(member: dict[str, str], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    haystack = " ".join(
        [
            member.get("email", ""),
            member.get("first_name", ""),
            member.get("last_name", ""),
            member.get("username", ""),
            member.get("label", ""),
        ]
    ).lower()
    return q in haystack


def _sort_members(members: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        members,
        key=lambda m: (
            m.get("last_name", "").lower(),
            m.get("first_name", "").lower(),
            m.get("email", "").lower(),
        ),
    )


def _paginate_member_rows(
    members_all: list[dict[str, str]],
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    q = (query or "").strip()
    if q:
        members_all = [m for m in members_all if member_matches_query(m, q)]

    members_all = _sort_members(members_all)
    total = len(members_all)
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    total_pages = math.ceil(total / page_size) if total else 0
    if total_pages and page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    return {
        "members": members_all[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def application_group_member_subs(kc: KeycloakAdminClient, app: Application) -> set[str]:
    group = kc.find_group_by_path(application_group_path(app.slug))
    if not group or not group.get("id"):
        return set()
    subs: set[str] = set()
    for user in kc.list_all_group_members(group["id"]):
        sub = (user.get("id") or "").strip()
        if sub:
            subs.add(sub)
    return subs


def list_application_group_members_page(
    kc: KeycloakAdminClient,
    app: Application,
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    group = kc.find_group_by_path(application_group_path(app.slug))
    members_all: list[dict[str, str]] = []
    if group and group.get("id"):
        for u in kc.list_all_group_members(group["id"]):
            row = format_keycloak_user(u)
            if row:
                members_all.append(row)
    return _paginate_member_rows(members_all, query=query, page=page, page_size=page_size)


def list_application_non_members_page(
    kc: KeycloakAdminClient,
    app: Application,
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    dual = list_application_dual_members(kc, app)
    return _paginate_member_rows(dual["available"], query=query, page=page, page_size=page_size)


def list_application_dual_members(kc: KeycloakAdminClient, app: Application) -> dict[str, list[dict[str, str]]]:
    members_all: list[dict[str, str]] = []
    member_subs: set[str] = set()
    group = kc.find_group_by_path(application_group_path(app.slug))
    if group and group.get("id"):
        for u in kc.list_all_group_members(group["id"]):
            row = format_keycloak_user(u)
            if row:
                members_all.append(row)
                member_subs.add(row["keycloak_sub"])

    available_all: list[dict[str, str]] = []
    for u in kc.list_all_users():
        sub = (u.get("id") or "").strip()
        if not sub or sub in member_subs:
            continue
        row = format_keycloak_user(u)
        if row:
            available_all.append(row)

    return {
        "members": _sort_members(members_all),
        "available": _sort_members(available_all),
    }


def count_application_group_members(kc: KeycloakAdminClient, app: Application) -> int | None:
    """Nombre de membres du groupe Keycloak, ou None si le décompte ne s'applique pas."""
    if not is_application_access_editable(app):
        return None
    if not getattr(settings, "KEYCLOAK_SYNC_ENABLED", False):
        return None
    try:
        group = kc.find_group_by_path(application_group_path(app.slug))
        if not group or not group.get("id"):
            return 0
        return kc.count_group_members(group["id"])
    except KeycloakAdminError:
        logger.exception("count application group members for %s", app.slug)
        return None


def build_user_application_access_rows(
    apps: list[Application],
    group_paths: set[str],
    pending_app_ids: set[int],
) -> list[dict[str, Any]]:
    rows = []
    for app in apps:
        auto_granted = not is_application_access_editable(app)
        has_access = auto_granted or user_has_application_access(group_paths, app)
        rows.append(
            {
                "application": app,
                "has_access": has_access,
                "auto_granted": auto_granted,
                "editable": is_application_access_editable(app),
                "pending_request": app.pk in pending_app_ids,
            }
        )
    return rows


def pending_application_ids_for_user(keycloak_sub: str) -> set[int]:
    from inscriptions.models import UserProfile

    profile = UserProfile.objects.filter(keycloak_sub=keycloak_sub).first()
    if not profile:
        return set()
    reg_ids = AccessRequestItem.objects.filter(
        registration__created_profile=profile,
        origin=AccessRequestItem.ORIGIN_REGISTRATION,
        status=AccessRequestItem.STATUS_PENDING,
    ).values_list("application_id", flat=True)
    add_ids = AccessRequestItem.objects.filter(
        user=profile,
        registration__isnull=True,
        origin=AccessRequestItem.ORIGIN_ADDITIONAL,
        status=AccessRequestItem.STATUS_PENDING,
    ).values_list("application_id", flat=True)
    return set(reg_ids) | set(add_ids)


def apply_application_access_changes(
    kc: KeycloakAdminClient,
    keycloak_user_id: str,
    current_paths: set[str],
    desired_by_slug: dict[str, bool],
) -> None:
    root = (getattr(settings, "KEYCLOAK_GROUP_APPLICATIONS", "applications") or "applications").strip("/")
    apps_by_slug = {
        a.slug: a
        for a in si_managed_applications().filter(slug__in=desired_by_slug.keys())
    }
    for slug, want_access in desired_by_slug.items():
        app = apps_by_slug.get(slug)
        if not app or not is_application_access_editable(app):
            continue
        has_access = user_has_application_access(current_paths, app)
        if want_access and not has_access:
            prov.provision_application_access(kc, keycloak_user_id, app)
            current_paths.add(f"/{root}/{app.slug}")
            current_paths.add(f"{root}/{app.slug}")
        elif not want_access and has_access:
            prov.revoke_application_access(kc, keycloak_user_id, app)
            current_paths.discard(f"/{root}/{app.slug}")
            current_paths.discard(f"{root}/{app.slug}")
