"""Orchestration des écritures doubles : Keycloak + base historique.

La plateforme écrit dans deux systèmes qui n'ont pas les mêmes garanties : PostgreSQL
est transactionnel, l'API Admin de Keycloak ne l'est pas. Pour obtenir malgré tout un
« tout ou rien », :func:`atomic_mirror` ouvre une transaction sur chaque base et tient
une pile d'annulations pour ce qui a déjà été fait côté Keycloak ; si une exception
traverse le bloc, les transactions sont annulées par Django et la pile est rejouée en
ordre inverse.

Chaque opération de ce module est **sans effet** quand ``LEGACY_WRITE_ENABLED`` est
faux : les appelants gardent leurs appels Keycloak et ajoutent simplement l'appel
miroir, sans se soucier de la configuration.

Le lien entre les deux mondes est l'attribut Keycloak ``legacy_id_role``, déjà posé par
l'import de l'existant (``legacy_user_migration``).
"""

from __future__ import annotations

import logging
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.db import transaction

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import Application, RegistrationRequest
from inscriptions.services import legacy_writer
from inscriptions.services.legacy_writer import LegacyWriteError  # noqa: F401  (ré-export)

logger = logging.getLogger(__name__)

#: Attribut Keycloak portant l'identifiant du compte dans la base historique.
LEGACY_ID_ROLE_ATTRIBUTE = "legacy_id_role"

def _inscription_app_id() -> int:
    """Application « inscription » côté UsersHub, dont la validation accordait le droit.

    Configurable car toutes les instances ne portent pas cette ligne : sur un
    GeoNature de test, l'identifiant 6 n'existe pas et l'INSERT échouerait sur la
    clé étrangère de cor_role_app_profil. 0 désactive le droit.
    """
    return int(getattr(settings, "LEGACY_INSCRIPTION_APP_ID", 6) or 0)


class _Compensation:
    """Pile d'annulations pour les effets non transactionnels déjà appliqués."""

    def __init__(self) -> None:
        self._undos: list = []

    def push(self, undo) -> None:
        self._undos.append(undo)

    def run(self) -> None:
        while self._undos:
            undo = self._undos.pop()
            try:
                undo()
            except Exception:  # noqa: BLE001 - une compensation ne doit jamais masquer l'erreur d'origine
                logger.exception("Échec d'une compensation Keycloak ; état possiblement incohérent")


@contextmanager
def atomic_mirror():
    """Transaction couvrant les deux bases, avec compensation Keycloak.

    Utilisation :

    .. code-block:: python

        with atomic_mirror() as undo:
            id_role = mirror.create_legacy_role(...)
            sub = kc.create_user(...)
            undo.push(lambda: kc.delete_user(sub))
    """
    undo = _Compensation()
    with ExitStack() as stack:
        stack.enter_context(transaction.atomic(using="default"))
        if legacy_writer.is_enabled():
            stack.enter_context(transaction.atomic(using="legacy"))
        try:
            yield undo
        except Exception:
            undo.run()
            raise


# --- Correspondance sub Keycloak → id_role historique ---------------------------


def legacy_id_role_for(
    kc: KeycloakAdminClient, user_sub: str, *, email: str = "", username: str = ""
) -> int | None:
    """Résout l'``id_role`` historique d'un compte Keycloak.

    Lit d'abord l'attribut ``legacy_id_role``. À défaut — compte créé avant la mise en
    place du miroir, ou importé sans attribut — retombe sur l'e-mail puis l'identifiant,
    et réécrit l'attribut pour que la résolution suivante soit directe.
    """
    if not legacy_writer.is_enabled():
        return None

    try:
        user = kc.get_user(user_sub) or {}
    except KeycloakAdminError:
        logger.warning("Lecture Keycloak impossible pour %s, repli sur e-mail", user_sub)
        user = {}

    raw = (user.get("attributes") or {}).get(LEGACY_ID_ROLE_ATTRIBUTE)
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if raw:
        try:
            return int(str(raw).strip())
        except ValueError:
            logger.warning("Attribut %s illisible pour %s: %r", LEGACY_ID_ROLE_ATTRIBUTE, user_sub, raw)

    id_role = legacy_writer.find_role_id(
        email=email or str(user.get("email") or ""),
        identifiant=username or str(user.get("username") or ""),
    )
    if id_role is not None:
        try:
            kc.set_user_attribute(user_sub, LEGACY_ID_ROLE_ATTRIBUTE, str(id_role))
        except KeycloakAdminError:
            logger.warning("Impossible de mémoriser %s sur %s", LEGACY_ID_ROLE_ATTRIBUTE, user_sub)
    return id_role


# --- Création de compte ---------------------------------------------------------


def referent_codes_from_registration(registration: RegistrationRequest) -> list[str]:
    """Codes de réserve pour lesquels le demandeur se déclare référent.

    Filtrés sur les réserves effectivement demandées : le formulaire peut envoyer un
    référent sur une réserve retirée depuis.
    """
    champs_addi = registration.champs_addi or {}
    raw = champs_addi.get("reserves_referent")
    if not isinstance(raw, list):
        return []
    allowed = {str(c).strip() for c in (registration.reserve_codes or []) if str(c).strip()}
    codes = []
    for item in raw:
        code = ""
        if isinstance(item, dict):
            code = str(item.get("id") or "").strip()
        elif isinstance(item, str):
            code = item.strip()
        if code and code in allowed:
            codes.append(code)
    return codes


def create_legacy_role(registration: RegistrationRequest, plain_password: str) -> int | None:
    """Crée la ligne ``t_roles`` correspondant à une demande validée.

    ``champs_addi`` est normalisé avant l'INSERT : c'est le trigger
    ``after_insert_user_function`` qui en déduira les lignes ``cor_role_rn``, il lui
    faut donc des tableaux d'objets bien formés, pas la chaîne vide que le formulaire
    envoie quand rien n'est sélectionné.

    Le droit sur l'application d'inscription est accordé dans la foulée, comme le
    faisait la validation côté UsersHub.
    """
    if not legacy_writer.is_enabled():
        return None

    codes = [str(c).strip() for c in (registration.reserve_codes or []) if str(c).strip()]
    referent_codes = referent_codes_from_registration(registration)
    champs_addi = dict(registration.champs_addi or {})
    champs_addi["reserves"], champs_addi["reserves_referent"] = legacy_writer.build_reserves_payload(
        codes, referent_codes
    )

    id_role = legacy_writer.create_role(
        identifiant=registration.username,
        nom_role=registration.last_name,
        prenom_role=registration.first_name,
        email=registration.email,
        remarques=(registration.remarks or "").strip(),
        id_organisme=registration.organisme.id_organisme if registration.organisme else None,
        password=plain_password,
        champs_addi=champs_addi,
    )
    # UsersHub rattache tout nouveau compte à ses groupes par défaut (Grp_all sur
    # l'installation RNF) : sans cela, l'inscrit n'a pas ce que ce groupe confère.
    default_groups = getattr(settings, "LEGACY_DEFAULT_GROUP_IDS", []) or []
    if default_groups:
        legacy_writer.add_to_groups(id_role, default_groups)

    app_id = _inscription_app_id()
    if app_id:
        legacy_writer.grant_application(id_role, id_application=app_id)
    return id_role


# --- Opérations sur un compte existant ------------------------------------------


def update_legacy_profile(kc: KeycloakAdminClient, user_sub: str, **fields) -> None:
    """Répercute une modification de profil (mêmes colonnes que l'ancien PUT /role)."""
    if not legacy_writer.is_enabled():
        return
    id_role = legacy_id_role_for(kc, user_sub)
    if id_role is None:
        logger.warning("Profil non répercuté : aucun id_role historique pour %s", user_sub)
        return
    legacy_writer.update_role_profile(id_role, **fields)


def _sync_reserve_membership(kc: KeycloakAdminClient, user_sub: str, code: str, *, present: bool) -> None:
    id_role = legacy_id_role_for(kc, user_sub)
    if id_role is None:
        logger.warning("Réserve non répercutée : aucun id_role historique pour %s", user_sub)
        return
    codes = legacy_writer.list_reserve_codes(id_role)
    if present:
        codes.add(code)
    else:
        codes.discard(code)
    referents = _current_referent_codes(id_role) & codes
    legacy_writer.sync_reserves(id_role, codes, referents)


def _current_referent_codes(id_role: int) -> set[str]:
    champs = legacy_writer.get_champs_addi(id_role)
    raw = champs.get("reserves_referent")
    if not isinstance(raw, list):
        return set()
    return {str(i.get("id") or "").strip() for i in raw if isinstance(i, dict)}


def legacy_join_reserve(kc: KeycloakAdminClient, user_sub: str, code: str) -> None:
    """Ajoute une réserve au compte historique."""
    if not legacy_writer.is_enabled():
        return
    _sync_reserve_membership(kc, user_sub, code, present=True)


def legacy_leave_reserve(kc: KeycloakAdminClient, user_sub: str, code: str) -> None:
    """Retire une réserve du compte historique."""
    if not legacy_writer.is_enabled():
        return
    _sync_reserve_membership(kc, user_sub, code, present=False)


def legacy_set_referent(kc: KeycloakAdminClient, user_sub: str, code: str, valid: bool) -> None:
    """Valide ou retire le statut de référent sur une réserve."""
    if not legacy_writer.is_enabled():
        return
    id_role = legacy_id_role_for(kc, user_sub)
    if id_role is None:
        logger.warning("Référent non répercuté : aucun id_role historique pour %s", user_sub)
        return
    legacy_writer.set_referent_valid(id_role, code, valid)


def _application_mapping(application: Application) -> tuple[int | None, int, int | None] | None:
    """Correspondance historique d'une application, ou ``None`` si rien n'est déclaré.

    Le groupe suffit : c'est lui qui porte l'accès côté historique, l'identifiant
    d'application ne servant qu'à écrire un droit dans ``cor_role_app_profil``, table
    que la production n'alimente plus.
    """
    if not application.legacy_id_application and not application.legacy_group_id_role:
        return None
    return (
        int(application.legacy_id_application) if application.legacy_id_application else None,
        int(application.legacy_id_profil or 1),
        int(application.legacy_group_id_role) if application.legacy_group_id_role else None,
    )


def legacy_grant_application(kc: KeycloakAdminClient, user_sub: str, application: Application) -> None:
    """Accorde le droit applicatif historique, si la correspondance est déclarée."""
    if not legacy_writer.is_enabled():
        return
    mapping = _application_mapping(application)
    if mapping is None:
        logger.info("Application %s sans correspondance historique, rien à écrire", application.slug)
        return
    id_role = legacy_id_role_for(kc, user_sub)
    if id_role is None:
        logger.warning("Accès non répercuté : aucun id_role historique pour %s", user_sub)
        return
    id_application, id_profil, group_id_role = mapping
    legacy_writer.grant_application(
        id_role, id_application=id_application, id_profil=id_profil, group_id_role=group_id_role
    )


def legacy_revoke_application(kc: KeycloakAdminClient, user_sub: str, application: Application) -> None:
    """Retire le droit applicatif historique, si la correspondance est déclarée."""
    if not legacy_writer.is_enabled():
        return
    mapping = _application_mapping(application)
    if mapping is None:
        return
    id_role = legacy_id_role_for(kc, user_sub)
    if id_role is None:
        logger.warning("Révocation non répercutée : aucun id_role historique pour %s", user_sub)
        return
    id_application, _id_profil, group_id_role = mapping
    legacy_writer.revoke_application(
        id_role, id_application=id_application, group_id_role=group_id_role
    )
