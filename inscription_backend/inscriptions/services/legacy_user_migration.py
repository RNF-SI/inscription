from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from django.conf import settings
from django.db import connections
from django.utils.text import slugify

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application, Organisme
from inscriptions.services import provisioning as prov

logger = logging.getLogger(__name__)

LEGACY_INSCRIPTION_APP_ID = 6
LEGACY_ADMIN_PROFIL_ID = 6
LEGACY_SUPER_ADMIN_GROUP_NAMES = {"grp_admin"}
MIGRATION_EMAIL_DOMAIN = "legacy-migration.local"

# Correspondances manuelles id_application UsersHub → slug catalogue Django.
MANUAL_LEGACY_APP_SLUG: dict[int, str] = {
    14: "geonature-saisie",
}


@dataclass
class LegacyApplicationRow:
    id_application: int
    code_application: str
    nom_application: str


@dataclass
class LegacyOrganismeRow:
    id_organisme: int
    uuid_organisme: str
    nom_organisme: str
    keycloak_slug: str


@dataclass
class LegacyUserRow:
    id_role: int
    username: str
    email: str
    first_name: str
    last_name: str
    fonction: str
    id_organisme: int | None
    password_bcrypt: str | None = None
    password_md5: str | None = None
    reserve_codes: list[str] = field(default_factory=list)
    referent_valid_codes: list[str] = field(default_factory=list)
    referent_pending_codes: list[str] = field(default_factory=list)
    app_member_slugs: set[str] = field(default_factory=set)
    app_admin_slugs: set[str] = field(default_factory=set)
    is_super_admin: bool = False


def _normalize_token(value: str) -> str:
    raw = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def _legacy_cursor():
    if "legacy" not in connections.databases:
        raise RuntimeError("LEGACY_DATABASE_URL doit être configuré.")
    return connections["legacy"].cursor()


def load_legacy_organismes() -> list[LegacyOrganismeRow]:
    with _legacy_cursor() as cursor:
        cursor.execute(
            """
            SELECT id_organisme, COALESCE(uuid_organisme::text, ''), COALESCE(nom_organisme, '')
            FROM utilisateurs.bib_organismes
            ORDER BY id_organisme
            """
        )
        rows = cursor.fetchall()
    out: list[LegacyOrganismeRow] = []
    for oid, uuid_o, nom in rows:
        nom_s = str(nom or "").strip()
        slug = slugify(nom_s)[:200] or f"org-{oid}"
        out.append(
            LegacyOrganismeRow(
                id_organisme=int(oid),
                uuid_organisme=str(uuid_o or "").strip(),
                nom_organisme=nom_s,
                keycloak_slug=slug,
            )
        )
    return out


def sync_legacy_organismes_to_django(rows: Iterable[LegacyOrganismeRow]) -> int:
    synced = 0
    for row in rows:
        Organisme.objects.update_or_create(
            id_organisme=row.id_organisme,
            defaults={
                "uuid_organisme": row.uuid_organisme,
                "nom_organisme": row.nom_organisme,
                "keycloak_slug": row.keycloak_slug,
            },
        )
        synced += 1
    return synced


def ensure_organisme_groups(
    kc: KeycloakAdminClient,
    organismes: Iterable[LegacyOrganismeRow],
    *,
    dry_run: bool = False,
) -> int:
    count = 0
    for org in organismes:
        count += 1
        if dry_run:
            continue
        gid = kc.ensure_organisme_group(
            org.keycloak_slug,
            org.id_organisme,
            org.nom_organisme,
            org.uuid_organisme,
        )
        logger.info("Groupe organisme assuré : /organismes/%s (%s)", org.keycloak_slug, gid)
    return count


def ensure_reserve_groups(
    kc: KeycloakAdminClient,
    area_codes: Iterable[str],
    *,
    dry_run: bool = False,
) -> int:
    count = 0
    for code in sorted({str(c or "").strip() for c in area_codes if str(c or "").strip()}):
        count += 1
        if dry_run:
            continue
        kc.ensure_reserve_group(code)
    return count


def build_keycloak_password_credential(
    *,
    password_bcrypt: str | None,
    password_md5: str | None,
) -> dict | None:
    bcrypt_hash = (password_bcrypt or "").strip()
    if bcrypt_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return {
            "type": "password",
            "credentialData": json.dumps(
                {"hashIterations": -1, "algorithm": "bcrypt", "additionalParameters": {}}
            ),
            "secretData": json.dumps({"value": bcrypt_hash, "salt": ""}),
            "temporary": False,
        }
    md5_hash = (password_md5 or "").strip().lower()
    if md5_hash and re.fullmatch(r"[a-f0-9]{32}", md5_hash):
        return {
            "type": "password",
            "credentialData": json.dumps(
                {"hashIterations": 1, "algorithm": "md5", "additionalParameters": {}}
            ),
            "secretData": json.dumps({"value": md5_hash, "salt": ""}),
            "temporary": False,
        }
    return None


def load_legacy_applications() -> list[LegacyApplicationRow]:
    with _legacy_cursor() as cursor:
        cursor.execute(
            """
            SELECT id_application, COALESCE(code_application, ''), COALESCE(nom_application, '')
            FROM utilisateurs.t_applications
            ORDER BY id_application
            """
        )
        rows = cursor.fetchall()
    return [
        LegacyApplicationRow(
            id_application=int(row[0]),
            code_application=str(row[1] or "").strip(),
            nom_application=str(row[2] or "").strip(),
        )
        for row in rows
    ]


def build_legacy_application_slug_map(
    legacy_apps: Iterable[LegacyApplicationRow],
    django_apps: Iterable[Application] | None = None,
) -> dict[int, str]:
    catalog = list(django_apps or Application.objects.all())
    by_slug = {app.slug: app for app in catalog}
    by_norm_name = {_normalize_token(app.nom): app.slug for app in catalog}
    mapping: dict[int, str] = dict(MANUAL_LEGACY_APP_SLUG)

    for legacy_app in legacy_apps:
        if legacy_app.id_application in mapping:
            continue
        if legacy_app.id_application == LEGACY_INSCRIPTION_APP_ID:
            continue

        candidates = [
            slugify(legacy_app.code_application or "")[:120],
            slugify(legacy_app.nom_application or "")[:120],
            _normalize_token(legacy_app.code_application or "").replace(" ", "-"),
            _normalize_token(legacy_app.nom_application or "").replace(" ", "-"),
        ]
        for candidate in candidates:
            if candidate and candidate in by_slug:
                mapping[legacy_app.id_application] = candidate
                break
        if legacy_app.id_application in mapping:
            continue

        norm_nom = _normalize_token(legacy_app.nom_application)
        for app in catalog:
            app_norm = _normalize_token(app.nom)
            if norm_nom and (norm_nom in app_norm or app_norm in norm_nom):
                mapping[legacy_app.id_application] = app.slug
                break
        if legacy_app.id_application not in mapping and norm_nom in by_norm_name:
            mapping[legacy_app.id_application] = by_norm_name[norm_nom]

    return mapping


def _load_reserve_links() -> dict[int, dict[str, tuple[bool, bool]]]:
    with _legacy_cursor() as cursor:
        cursor.execute(
            """
            SELECT role_id::integer, rn_id::text, COALESCE(referent, false), COALESCE(referent_valid, false)
            FROM complement_rnf.cor_role_rn
            """
        )
        rows = cursor.fetchall()

    out: dict[int, dict[str, tuple[bool, bool]]] = {}
    for role_id, area_code, referent, referent_valid in rows:
        rid = int(role_id)
        code = str(area_code or "").strip()
        if not code:
            continue
        out.setdefault(rid, {})[code] = (bool(referent), bool(referent_valid))
    return out


def _load_app_rights(app_slug_map: dict[int, str]) -> dict[int, dict[str, set[int]]]:
    with _legacy_cursor() as cursor:
        cursor.execute(
            """
            SELECT u.id_role, c.id_application, c.id_profil
            FROM utilisateurs.t_roles u
            JOIN utilisateurs.cor_role_app_profil c ON c.id_role = u.id_role
            WHERE COALESCE(u.groupe, false) = false AND COALESCE(u.active, true) = true
            UNION
            SELECT u.id_role, c.id_application, c.id_profil
            FROM utilisateurs.t_roles u
            JOIN utilisateurs.cor_roles g ON g.id_role_utilisateur = u.id_role
            JOIN utilisateurs.cor_role_app_profil c ON c.id_role = g.id_role_groupe
            WHERE COALESCE(u.groupe, false) = false AND COALESCE(u.active, true) = true
            """
        )
        rows = cursor.fetchall()

    out: dict[int, dict[str, set[int]]] = {}
    for role_id, id_application, id_profil in rows:
        rid = int(role_id)
        app_id = int(id_application)
        profil_id = int(id_profil)
        if app_id == LEGACY_INSCRIPTION_APP_ID:
            out.setdefault(rid, {}).setdefault("inscription", set()).add(profil_id)
            continue
        slug = app_slug_map.get(app_id)
        if not slug:
            continue
        out.setdefault(rid, {}).setdefault(slug, set()).add(profil_id)
    return out


def _load_super_admin_ids() -> set[int]:
    with _legacy_cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT g.id_role_utilisateur
            FROM utilisateurs.cor_roles g
            JOIN utilisateurs.t_roles grp ON grp.id_role = g.id_role_groupe
            WHERE COALESCE(grp.groupe, false) = true
              AND (
                lower(COALESCE(grp.nom_role, '')) = ANY(%s)
                OR lower(COALESCE(grp.identifiant, '')) = ANY(%s)
              )
            """,
            [sorted(LEGACY_SUPER_ADMIN_GROUP_NAMES), sorted(LEGACY_SUPER_ADMIN_GROUP_NAMES)],
        )
        group_rows = {int(row[0]) for row in cursor.fetchall()}

        cursor.execute(
            """
            SELECT DISTINCT u.id_role
            FROM utilisateurs.t_roles u
            JOIN utilisateurs.cor_role_app_profil c ON c.id_role = u.id_role
            WHERE COALESCE(u.groupe, false) = false
              AND COALESCE(u.active, true) = true
              AND c.id_application = %s
              AND c.id_profil = %s
            UNION
            SELECT DISTINCT u.id_role
            FROM utilisateurs.t_roles u
            JOIN utilisateurs.cor_roles g ON g.id_role_utilisateur = u.id_role
            JOIN utilisateurs.cor_role_app_profil c ON c.id_role = g.id_role_groupe
            WHERE COALESCE(u.groupe, false) = false
              AND COALESCE(u.active, true) = true
              AND c.id_application = %s
              AND c.id_profil = %s
            """,
            [
                LEGACY_INSCRIPTION_APP_ID,
                LEGACY_ADMIN_PROFIL_ID,
                LEGACY_INSCRIPTION_APP_ID,
                LEGACY_ADMIN_PROFIL_ID,
            ],
        )
        inscription_admin_rows = {int(row[0]) for row in cursor.fetchall()}
    return group_rows | inscription_admin_rows


def load_legacy_users(
    *,
    limit: int | None = 20,
    offset: int = 0,
    legacy_id: int | None = None,
) -> list[LegacyUserRow]:
    legacy_apps = load_legacy_applications()
    app_slug_map = build_legacy_application_slug_map(legacy_apps)
    reserve_links = _load_reserve_links()
    app_rights = _load_app_rights(app_slug_map)
    super_admin_ids = _load_super_admin_ids()

    params: list[object] = []
    where = ["COALESCE(u.groupe, false) = false", "COALESCE(u.active, true) = true"]
    if legacy_id is not None:
        where.append("u.id_role = %s")
        params.append(legacy_id)
    where_sql = " AND ".join(where)
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT %s OFFSET %s"
        params.extend([limit, offset])

    with _legacy_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT u.id_role, u.identifiant, u.nom_role, u.prenom_role, u.email, u.id_organisme, u.remarques,
                   u.pass_plus, u.pass
            FROM utilisateurs.t_roles u
            WHERE {where_sql}
            ORDER BY u.id_role
            {limit_sql}
            """,
            params,
        )
        rows = cursor.fetchall()

    users: list[LegacyUserRow] = []
    for id_role, identifiant, nom, prenom, email, id_organisme, remarques, pass_plus, pass_md5 in rows:
        username = str(identifiant or "").strip()
        if not username:
            continue
        rid = int(id_role)
        reserves = reserve_links.get(rid, {})
        reserve_codes = sorted(reserves.keys())
        referent_valid_codes = sorted(code for code, (is_ref, is_valid) in reserves.items() if is_ref and is_valid)
        referent_pending_codes = sorted(code for code, (is_ref, is_valid) in reserves.items() if is_ref and not is_valid)

        member_slugs: set[str] = set()
        admin_slugs: set[str] = set()
        for slug, profils in app_rights.get(rid, {}).items():
            if slug == "inscription":
                continue
            if LEGACY_ADMIN_PROFIL_ID in profils:
                admin_slugs.add(slug)
            elif any(pid > 0 for pid in profils):
                member_slugs.add(slug)

        users.append(
            LegacyUserRow(
                id_role=rid,
                username=username,
                email=_normalize_email(email, username),
                first_name=str(prenom or "").strip(),
                last_name=str(nom or "").strip(),
                fonction=str(remarques or "").strip(),
                id_organisme=int(id_organisme) if id_organisme is not None else None,
                password_bcrypt=str(pass_plus or "").strip() or None,
                password_md5=str(pass_md5 or "").strip() or None,
                reserve_codes=reserve_codes,
                referent_valid_codes=referent_valid_codes,
                referent_pending_codes=referent_pending_codes,
                app_member_slugs=member_slugs,
                app_admin_slugs=admin_slugs,
                is_super_admin=rid in super_admin_ids,
            )
        )
    return users


def _normalize_email(email: str | None, username: str) -> str:
    normalized = (email or "").strip().lower()
    if normalized and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized):
        return normalized
    safe_username = re.sub(r"[^a-zA-Z0-9._+-]", "-", username).strip("-") or "user"
    return f"{safe_username}@{MIGRATION_EMAIL_DOMAIN}"


def _resolve_organisme(id_organisme: int | None) -> LegacyOrganismeRow | None:
    if not id_organisme:
        return None
    org = Organisme.objects.filter(pk=id_organisme).first()
    if org:
        return LegacyOrganismeRow(
            id_organisme=org.id_organisme,
            uuid_organisme=org.uuid_organisme or "",
            nom_organisme=org.nom_organisme,
            keycloak_slug=prov._organisme_slug(org),
        )
    for row in load_legacy_organismes():
        if row.id_organisme == id_organisme:
            sync_legacy_organismes_to_django([row])
            return row
    return None


def prepare_migration_groups(
    kc: KeycloakAdminClient,
    users: Iterable[LegacyUserRow],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    organismes = load_legacy_organismes()
    synced = sync_legacy_organismes_to_django(organismes)
    org_groups = ensure_organisme_groups(kc, organismes, dry_run=dry_run)
    reserve_codes: set[str] = set()
    for user in users:
        reserve_codes.update(user.reserve_codes)
        reserve_codes.update(user.referent_valid_codes)
        reserve_codes.update(user.referent_pending_codes)
    reserve_groups = ensure_reserve_groups(kc, reserve_codes, dry_run=dry_run)
    return {
        "organismes_synced": synced,
        "organisme_groups": org_groups,
        "reserve_groups": reserve_groups,
    }


def clear_keycloak_users(kc: KeycloakAdminClient, *, dry_run: bool = False) -> int:
    removed = 0
    for user in kc.list_all_users():
        user_id = (user.get("id") or "").strip()
        if not user_id:
            continue
        removed += 1
        if dry_run:
            continue
        resp = kc._delete(f"/users/{user_id}")
        if resp.status_code not in (200, 204, 404):
            raise KeycloakAdminError(f"delete_user:{resp.status_code}")
    return removed


def migrate_legacy_user_to_keycloak(
    kc: KeycloakAdminClient,
    user: LegacyUserRow,
    *,
    fallback_password: str | None = None,
    fallback_temporary: bool = True,
    dry_run: bool = False,
) -> tuple[str, str, str | None]:
    """Retourne (user_id, password_mode, generated_password)."""
    if dry_run:
        mode = "legacy-bcrypt" if user.password_bcrypt else "legacy-md5" if user.password_md5 else "generated"
        return f"dry-run-{user.id_role}", mode, None

    imported = build_keycloak_password_credential(
        password_bcrypt=user.password_bcrypt,
        password_md5=user.password_md5,
    )
    password_mode = "legacy-bcrypt" if user.password_bcrypt else "legacy-md5" if user.password_md5 else ""
    plain_password: str | None = None
    temporary_password = False
    generated_plain: str | None = None

    if imported:
        credential = imported
    elif fallback_password:
        plain_password = fallback_password
        temporary_password = fallback_temporary
        password_mode = "shared"
        credential = None
    else:
        import secrets

        generated_plain = secrets.token_urlsafe(14)
        plain_password = generated_plain
        temporary_password = True
        password_mode = "generated"
        credential = None

    user_id = kc.create_user(
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        password=plain_password,
        temporary_password=temporary_password,
        imported_password_credential=credential,
        require_verify_email=False,
        email_verified=True,
        function_value=user.fonction,
        extra_attributes={"legacy_id_role": [str(user.id_role)]},
    )

    org = _resolve_organisme(user.id_organisme)
    if org:
        gid = kc.ensure_organisme_group(
            org.keycloak_slug,
            org.id_organisme,
            org.nom_organisme,
            org.uuid_organisme,
        )
        kc.user_join_group(user_id, gid)
    elif user.id_organisme:
        logger.warning(
            "Organisme legacy %s introuvable pour %s — groupe non attribué",
            user.id_organisme,
            user.username,
        )

    for code in user.reserve_codes:
        gid = kc.ensure_reserve_group(code)
        kc.user_join_group(user_id, gid)

    for code in user.referent_valid_codes:
        gid = kc.ensure_reserve_referent_group(code)
        kc.user_join_group(user_id, gid)

    for slug in sorted(user.app_member_slugs):
        app = Application.objects.filter(slug=slug).first()
        if app:
            prov.provision_application_access(kc, user_id, app)

    for slug in sorted(user.app_admin_slugs):
        app = Application.objects.filter(slug=slug).first()
        if app:
            gid = kc.ensure_application_admin_group(app.slug)
            kc.user_join_group(user_id, gid)

    if user.is_super_admin:
        gid = kc.ensure_super_admin_group()
        kc.user_join_group(user_id, gid)

    return user_id, password_mode, generated_plain


def realm_is_safe_for_migration(realm: str) -> bool:
    normalized = (realm or "").strip().lower()
    if not normalized:
        return False
    forbidden = {"rnf", "si-rnf", "master", "production", "prod"}
    if normalized in forbidden:
        return False
    return "test" in normalized or normalized.endswith("-dev") or normalized.endswith("-local")
