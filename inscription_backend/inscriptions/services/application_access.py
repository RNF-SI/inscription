from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient
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
