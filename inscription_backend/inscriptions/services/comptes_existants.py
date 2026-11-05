"""Un compte existe-t-il déjà pour cette adresse ou cet identifiant ?

La question se pose à l'inscription, et elle se posait trop tard. ``SignupSerializer``
ne contrôlait que la *forme* de l'identifiant ; la collision n'éclatait qu'à la
validation super-admin, où ``partialImport`` renvoie 409 — et le message disait
« Identifiant déjà utilisé » alors que la cause réelle était presque toujours
l'adresse, la connexion par e-mail étant active dans le realm. Le super-admin voyait
un refus incompréhensible pour une demande vieille de plusieurs jours, et le doublon
n'était jamais expliqué à celui qui l'avait créé.

La vérification porte sur **les deux mondes**. Keycloak refuserait de lui-même, mais
la base historique, elle, accepterait peut-être le doublon selon ses contraintes : un
compte peut exister dans ``t_roles`` — donc pour toutes les applications RNF — sans
être encore dans le realm. L'adresse passe avant l'identifiant, parce qu'une adresse
déjà connue ne veut pas dire « choisissez autre chose » mais « vous avez déjà un
compte » : la bonne suite est « mot de passe oublié », pas une seconde inscription.

Un contrôle qui échoue ne bloque pas une inscription : Keycloak ou la base peuvent
être momentanément injoignables, et le 409 de la validation reste le dernier filet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.services import legacy_writer
from inscriptions.services.legacy_writer import LegacyWriteError

logger = logging.getLogger(__name__)

MESSAGE_EMAIL = (
    "Un compte existe déjà avec cette adresse électronique. "
    "Utilisez « Mot de passe oublié » depuis la page de connexion pour y accéder, "
    "plutôt que de créer un second compte."
)
MESSAGE_IDENTIFIANT = "Cet identifiant est déjà utilisé. Choisissez-en un autre."


@dataclass(frozen=True)
class CompteExistant:
    """Le champ en cause, et ce qu'il faut dire à celui qui le lit."""

    champ: str  # "email" ou "identifiant"
    message: str


def _keycloak(kc: KeycloakAdminClient | None) -> KeycloakAdminClient | None:
    if not settings.KEYCLOAK_SYNC_ENABLED:
        return None
    return kc or KeycloakAdminClient()


def compte_existant(
    *,
    email: str = "",
    identifiant: str = "",
    kc: KeycloakAdminClient | None = None,
) -> CompteExistant | None:
    """Premier conflit trouvé, ou None si les deux valeurs sont libres.

    Pour une **création** de compte : aucune exclusion de soi-même. La modification de
    son propre profil passe par ``_identifiant_deja_pris`` (``views.py``), qui doit,
    lui, s'autoriser à garder son identifiant.
    """
    email = (email or "").strip()
    identifiant = (identifiant or "").strip()
    client = _keycloak(kc)

    if email:
        if client is not None:
            try:
                if client.find_user_by_email(email):
                    return CompteExistant("email", MESSAGE_EMAIL)
            except KeycloakAdminError as exc:
                logger.warning("Vérification de l'adresse dans Keycloak impossible : %s", exc)
        if legacy_writer.is_enabled():
            try:
                if legacy_writer.find_role_id(email=email) is not None:
                    return CompteExistant("email", MESSAGE_EMAIL)
            except LegacyWriteError as exc:
                logger.warning("Vérification de l'adresse dans t_roles impossible : %s", exc)

    if identifiant:
        if client is not None:
            try:
                # Keycloak replie les identifiants en minuscules : la recherche exacte
                # sur la valeur saisie suffit, « JDupont » et « jdupont » y désignent
                # le même compte.
                if client.find_user_by_username(identifiant):
                    return CompteExistant("identifiant", MESSAGE_IDENTIFIANT)
            except KeycloakAdminError as exc:
                logger.warning("Vérification de l'identifiant dans Keycloak impossible : %s", exc)
        if legacy_writer.is_enabled():
            try:
                if legacy_writer.find_role_id(identifiant=identifiant) is not None:
                    return CompteExistant("identifiant", MESSAGE_IDENTIFIANT)
            except LegacyWriteError as exc:
                logger.warning("Vérification de l'identifiant dans t_roles impossible : %s", exc)

    return None
