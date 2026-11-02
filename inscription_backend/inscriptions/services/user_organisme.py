from __future__ import annotations

import logging
import time
from dataclasses import replace
from typing import Any

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.user_identity import UserInfo

logger = logging.getLogger(__name__)

_ORG_NAME_CACHE: dict[str, tuple[float, str]] = {}
_ORG_NAME_CACHE_TTL_SEC = 300


def token_groups_from_claims(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups") or []
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for group in raw:
        if isinstance(group, str) and group.strip():
            out.add(group.strip())
    return out


def fetch_user_group_paths(keycloak_sub: str) -> list[str]:
    kc = KeycloakAdminClient()
    out: list[str] = []
    for group in kc.get_user_groups(keycloak_sub):
        path = (group.get("path") or "").strip()
        if path:
            out.append(path.lstrip("/"))
    return out


def claims_with_groups(claims: dict[str, Any], keycloak_sub: str) -> dict[str, Any]:
    if token_groups_from_claims(claims):
        return claims
    if not settings.KEYCLOAK_SYNC_ENABLED or not (keycloak_sub or "").strip():
        return claims
    try:
        kc_paths = fetch_user_group_paths(keycloak_sub)
    except KeycloakAdminError as exc:
        logger.warning("Impossible de charger les groupes Keycloak pour %s: %s", keycloak_sub, exc)
        return claims
    if not kc_paths:
        return claims
    return {**claims, "groups": kc_paths}


def first_organisme_group_path(claims: dict[str, Any]) -> str:
    root = (getattr(settings, "KEYCLOAK_GROUP_ORGANISMES", "organismes") or "organismes").strip("/")
    groups = sorted(token_groups_from_claims(claims))
    for group in groups:
        path = f"/{group.strip('/')}"
        if path == f"/{root}" or path.startswith(f"/{root}/"):
            return path
    return ""


def organisme_name_from_group_path(group_path: str) -> str:
    now = time.time()
    cached = _ORG_NAME_CACHE.get(group_path)
    if cached and (now - cached[0]) < _ORG_NAME_CACHE_TTL_SEC:
        return cached[1]

    if not group_path:
        return ""

    try:
        kc = KeycloakAdminClient()
        group = kc.find_group_by_path(group_path)
        if not group:
            _ORG_NAME_CACHE[group_path] = (now, "")
            return ""
        attrs = group.get("attributes") or {}
        names = attrs.get("nom_organisme") or []
        if isinstance(names, list) and names:
            name = str(names[0]).strip()
        else:
            name = str(group.get("name") or "").strip()
        _ORG_NAME_CACHE[group_path] = (now, name)
        return name
    except KeycloakAdminError:
        logger.warning("Impossible de resoudre l'organisme Keycloak pour %s", group_path)
    except Exception:
        logger.exception("Erreur de resolution organisme Keycloak")
    _ORG_NAME_CACHE[group_path] = (now, "")
    return ""


def organisme_id_from_group_path(group_path: str) -> int | None:
    if not group_path:
        return None
    try:
        kc = KeycloakAdminClient()
        group = kc.find_group_by_path(group_path)
        if not group:
            return None
        attrs = group.get("attributes") or {}
        ids = attrs.get("id_organisme") or []
        if isinstance(ids, list) and ids:
            try:
                return int(str(ids[0]).strip())
            except (TypeError, ValueError):
                return None
    except Exception:
        logger.exception("Erreur de resolution id_organisme Keycloak")
    return None


def organisme_name_from_claims(claims: dict[str, Any]) -> str:
    path = first_organisme_group_path(claims)
    name = organisme_name_from_group_path(path)
    if name:
        return name
    return (claims.get("organisme_name") or claims.get("organisme") or "").strip()


def organisme_name_for_user(*, keycloak_sub: str, claims: dict[str, Any] | None = None) -> str:
    enriched = claims_with_groups(dict(claims or {}), keycloak_sub)
    return organisme_name_from_claims(enriched)


def enrich_user_organisme(info: UserInfo, claims: dict[str, Any] | None = None) -> UserInfo:
    if (info.organisme or "").strip():
        return info
    org = organisme_name_for_user(keycloak_sub=info.sub, claims=claims)
    if not org:
        return info
    return replace(info, organisme=org)
