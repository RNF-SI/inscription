from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError


@dataclass(frozen=True)
class UserInfo:
    sub: str
    email: str
    username: str
    first_name: str
    last_name: str
    fonction: str = ""

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> UserInfo:
        sub = (claims.get("sub") or "").strip()
        email = (claims.get("email") or "").strip().lower()
        username = (
            (claims.get("preferred_username") or claims.get("username") or email.split("@")[0] or sub).strip()
        )
        first_name = (claims.get("given_name") or claims.get("first_name") or "").strip()
        last_name = (claims.get("family_name") or claims.get("last_name") or "").strip()
        fonction = (claims.get("function") or claims.get("fonction") or "").strip()
        return cls(
            sub=sub,
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            fonction=fonction,
        )

    @classmethod
    def from_keycloak_user(cls, kc_user: dict[str, Any]) -> UserInfo | None:
        sub = (kc_user.get("id") or "").strip()
        if not sub:
            return None
        email = (kc_user.get("email") or "").strip().lower()
        username = (kc_user.get("username") or email or sub).strip()
        attrs = kc_user.get("attributes") or {}
        fonction = ""
        fn_vals = attrs.get("function") or []
        if isinstance(fn_vals, list) and fn_vals:
            fonction = str(fn_vals[0]).strip()
        return cls(
            sub=sub,
            email=email,
            username=username,
            first_name=(kc_user.get("firstName") or "").strip(),
            last_name=(kc_user.get("lastName") or "").strip(),
            fonction=fonction,
        )


def user_label(info: UserInfo) -> str:
    name = f"{info.first_name} {info.last_name}".strip()
    if name:
        return f"{name} ({info.email or info.username})"
    return info.email or info.username or info.sub


def fetch_user_info(sub: str) -> UserInfo | None:
    sub = (sub or "").strip()
    if not sub or not settings.KEYCLOAK_SYNC_ENABLED:
        return None
    try:
        kc = KeycloakAdminClient()
        return UserInfo.from_keycloak_user(kc.get_user(sub))
    except KeycloakAdminError:
        return None


def resolve_user_sub(*, keycloak_sub: str = "", email: str = "") -> str | None:
    sub = (keycloak_sub or "").strip()
    if sub:
        return sub
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return None
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None
    try:
        kc = KeycloakAdminClient()
        for user in kc.search_users(normalized_email, max_count=20):
            if (user.get("email") or "").strip().lower() == normalized_email:
                found = (user.get("id") or "").strip()
                if found:
                    return found
    except KeycloakAdminError:
        return None
    return None


def admin_user_payload(info: UserInfo) -> dict:
    return {
        "keycloak_sub": info.sub,
        "email": info.email,
        "first_name": info.first_name,
        "last_name": info.last_name,
        "username": info.username,
    }
