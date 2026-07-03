from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings
from django.utils.text import slugify

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application, Organisme, RegistrationRequest

logger = logging.getLogger(__name__)


def _organisme_slug(org: Organisme) -> str:
    if org.keycloak_slug:
        return org.keycloak_slug
    return slugify(org.nom_organisme)[:200] or f"org-{org.pk}"


def provision_user_groups_after_super_approval(
    kc: KeycloakAdminClient,
    keycloak_user_id: str,
    registration: RegistrationRequest,
) -> None:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        logger.info("Keycloak sync désactivé, skip provisioning groupes")
        return
    if registration.organisme:
        slug = _organisme_slug(registration.organisme)
        gid = kc.ensure_organisme_group(
            slug,
            registration.organisme.id_organisme,
            registration.organisme.nom_organisme,
            registration.organisme.uuid_organisme or "",
        )
        kc.user_join_group(keycloak_user_id, gid)
    for code in registration.reserve_codes or []:
        if not code:
            continue
        gid = kc.ensure_reserve_group(str(code))
        kc.user_join_group(keycloak_user_id, gid)


def provision_application_access(kc: KeycloakAdminClient, keycloak_user_id: str, application: Application) -> None:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return
    gid = kc.ensure_application_group(application.slug)
    kc.user_join_group(keycloak_user_id, gid)


def revoke_application_access(kc: KeycloakAdminClient, keycloak_user_id: str, application: Application) -> None:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return
    gid = kc.ensure_application_group(application.slug)
    try:
        kc.user_leave_group(keycloak_user_id, gid)
    except KeycloakAdminError:
        logger.warning("Impossible de retirer le groupe %s pour %s", application.slug, keycloak_user_id)
