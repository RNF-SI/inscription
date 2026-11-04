"""Écritures dans la base historique (schémas ``utilisateurs`` et ``complement_rnf``).

Tant que les applications RNF lisent leurs comptes dans cette base, la plateforme
d'inscription doit y produire le même état final que le couple Flask + UsersHub
produisait. Ce module regroupe **toutes** ces écritures et elles seules : les appelants
passent par :mod:`inscriptions.services.mirror`, qui les orchestre avec Keycloak.

Deux pièges du schéma dictent la forme du code :

* ``complement_rnf.after_insert_user_function()`` peuple déjà ``cor_role_rn`` à l'INSERT
  de ``t_roles``, en lisant ``champs_addi->'reserves'``. À la création on écrit donc
  ``champs_addi`` et on laisse le trigger faire ; :func:`sync_reserves` ne sert qu'aux
  modifications ultérieures.
* ``id_role``, ``uuid_role``, ``active``, ``groupe`` ont des valeurs par défaut
  PostgreSQL, et ``date_insert`` / ``date_update`` sont posées par les triggers
  ``tri_modify_date_*_t_roles``. Aucune de ces colonnes ne doit être écrite ici.

``cor_role_rn.rn_id`` reçoit le code textuel de la réserve (``RNN41``) : c'est une clé
étrangère vers ``ref_geo.l_areas.area_code``, pas un identifiant numérique.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import NamedTuple

import bcrypt
from django.conf import settings
from django.db import DatabaseError, connections

logger = logging.getLogger(__name__)


class LegacyWriteError(RuntimeError):
    """Échec d'écriture côté base historique.

    La cause interne est journalisée ; les vues renvoient un message neutre, comme
    pour ``KeycloakAdminError``.
    """


def is_enabled() -> bool:
    """Vrai si l'écriture miroir est configurée et activée."""
    return bool(getattr(settings, "LEGACY_WRITE_ENABLED", False)) and "legacy" in connections.databases


def _execute(sql: str, params: list | None = None, *, fetch: str = ""):
    """Exécute une requête sur la connexion historique, erreurs enveloppées.

    ``fetch`` vaut ``"one"``, ``"all"`` ou ``""`` selon ce que l'appelant attend.
    """
    if not is_enabled():
        raise LegacyWriteError("écriture historique désactivée (LEGACY_WRITE_ENABLED)")
    try:
        with connections["legacy"].cursor() as cursor:
            cursor.execute(sql, params or [])
            if fetch == "one":
                return cursor.fetchone()
            if fetch == "all":
                return cursor.fetchall()
            return None
    except DatabaseError as exc:
        logger.exception("Échec d'écriture dans la base historique")
        raise LegacyWriteError(str(exc)) from exc


# --- Mots de passe -------------------------------------------------------------


def hash_password(plain: str) -> tuple[str, str | None]:
    """Hache un mot de passe au format attendu par pypnusershub.

    ``bcrypt.gensalt()`` sans argument produit un ``$2b$`` de coût 12, exactement ce
    que générait ``check_and_encrypt_password`` côté UsersHub. Le md5 n'est calculé que
    si ``LEGACY_WRITE_PASS_MD5`` est actif.
    """
    pass_plus = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    pass_md5 = None
    if getattr(settings, "LEGACY_WRITE_PASS_MD5", False):
        pass_md5 = hashlib.md5(plain.encode("utf-8")).hexdigest()
    return pass_plus, pass_md5


def verify_password(id_role: int, plain: str) -> bool:
    """Vérifie un mot de passe contre le bcrypt historique.

    C'est le contrôle que font les applications RNF elles-mêmes. Le client SPA
    n'autorise pas le « direct grant », on ne peut donc pas demander à Keycloak de
    valider ; et comme cette colonne est tenue à jour par la plateforme, elle porte
    bien le mot de passe courant.

    Renvoie faux si le compte n'a pas de hash exploitable, plutôt que de laisser
    passer : sans preuve, pas de changement.
    """
    row = _execute(
        "SELECT pass_plus FROM utilisateurs.t_roles WHERE id_role = %s", [id_role], fetch="one"
    )
    hashed = (row[0] if row else "") or ""
    if not hashed.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        logger.warning("Hash bcrypt illisible pour le rôle %s", id_role)
        return False


def set_password(id_role: int, plain: str) -> None:
    """Met à jour le mot de passe d'un compte historique."""
    pass_plus, pass_md5 = hash_password(plain)
    if pass_md5 is None:
        _execute(
            'UPDATE utilisateurs.t_roles SET pass_plus = %s WHERE id_role = %s',
            [pass_plus, id_role],
        )
    else:
        _execute(
            'UPDATE utilisateurs.t_roles SET pass_plus = %s, "pass" = %s WHERE id_role = %s',
            [pass_plus, pass_md5, id_role],
        )


# --- Comptes -------------------------------------------------------------------


class NouveauRole(NamedTuple):
    """Ce que la base historique attribue au compte à l'INSERT.

    ``uuid_role`` sert d'identifiant au compte Keycloak : le ``sub`` des jetons
    devient alors la clé de jointure vers ``utilisateurs.t_roles``, sans attribut
    ni requête supplémentaire. C'est PostgreSQL qui le génère
    (``uuid_generate_v4()``), d'où sa remontée par ``RETURNING``.
    """

    id_role: int
    uuid_role: str


def create_role(
    *,
    identifiant: str,
    nom_role: str,
    prenom_role: str,
    email: str,
    remarques: str = "",
    id_organisme: int | None = None,
    password: str | None = None,
    champs_addi: dict | None = None,
) -> NouveauRole:
    """Crée la ligne ``utilisateurs.t_roles`` et renvoie ses deux identifiants.

    ``champs_addi`` doit déjà porter ``reserves`` et ``reserves_referent`` : c'est le
    trigger ``after_insert_user_function`` qui en déduira les lignes ``cor_role_rn``.
    """
    pass_plus, pass_md5 = hash_password(password) if password else (None, None)
    row = _execute(
        """
        INSERT INTO utilisateurs.t_roles
            (identifiant, nom_role, prenom_role, email, remarques,
             id_organisme, pass_plus, "pass", champs_addi)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id_role, uuid_role
        """,
        [
            identifiant,
            nom_role,
            prenom_role,
            email,
            remarques,
            id_organisme,
            pass_plus,
            pass_md5,
            json.dumps(champs_addi or {}),
        ],
        fetch="one",
    )
    return NouveauRole(int(row[0]), str(row[1]))


class NouvelOrganisme(NamedTuple):
    """Ce que ``bib_organismes`` attribue à l'organisme créé.

    ``id_organisme`` est généré par la séquence : c'est lui que porte
    ``Organisme.id_organisme`` ici, et que ``t_roles.id_organisme`` référencera pour
    chaque membre. Il faut donc que la ligne historique existe avant la ligne locale,
    jamais l'inverse. ``uuid_organisme`` est renvoyé parce qu'il peut venir du défaut
    PostgreSQL quand l'appelant n'en fournit pas.
    """

    id_organisme: int
    uuid_organisme: str


def create_organisme(
    *,
    nom_organisme: str,
    uuid_organisme: str | None = None,
    adresse_organisme: str = "",
    cp_organisme: str = "",
    ville_organisme: str = "",
    url_logo: str = "",
) -> NouvelOrganisme:
    """Crée la ligne ``utilisateurs.bib_organismes`` et renvoie ses identifiants.

    ``uuid_organisme`` est l'UUID du référentiel des organismes du SINP quand RADIS en
    connaît un ; sinon la colonne a un défaut (``gen_random_uuid()``) et c'est lui qui
    s'applique. Ni ``meta_create_date`` ni ``meta_update_date`` ne sont écrites : la
    base s'en charge.
    """
    row = _execute(
        """
        INSERT INTO utilisateurs.bib_organismes
            (nom_organisme, uuid_organisme, adresse_organisme, cp_organisme,
             ville_organisme, url_logo)
        VALUES (%s, COALESCE(%s::uuid, gen_random_uuid()), %s, %s, %s, %s)
        RETURNING id_organisme, uuid_organisme
        """,
        [
            nom_organisme,
            uuid_organisme or None,
            adresse_organisme or None,
            cp_organisme or None,
            ville_organisme or None,
            url_logo or None,
        ],
        fetch="one",
    )
    return NouvelOrganisme(int(row[0]), str(row[1]))


def find_organisme(*, uuid_organisme: str = "", nom_organisme: str = "") -> NouvelOrganisme | None:
    """Cherche un organisme historique par UUID puis par nom exact.

    Évite de créer un doublon d'une ligne posée à la main ou par RADIS : l'UUID du SINP
    d'abord, le nom ensuite — comparé sans tenir compte de la casse, comme le fait déjà
    la résolution d'organisme des vues.
    """
    if uuid_organisme:
        row = _execute(
            """
            SELECT id_organisme, uuid_organisme
              FROM utilisateurs.bib_organismes
             WHERE uuid_organisme = %s::uuid
            """,
            [uuid_organisme],
            fetch="one",
        )
        if row:
            return NouvelOrganisme(int(row[0]), str(row[1]))
    if nom_organisme:
        # Les noms de bib_organismes ne sont pas propres : « Conservatoire d'espaces
        # naturels de Normandie » y porte une espace finale, et une comparaison exacte
        # créerait un doublon de l'organisme qu'on cherche. D'où le repli sur une forme
        # normalisée — bords rognés, espaces internes réduites, casse ignorée.
        row = _execute(
            r"""
            SELECT id_organisme, uuid_organisme
              FROM utilisateurs.bib_organismes
             WHERE regexp_replace(btrim(lower(nom_organisme)), '\s+', ' ', 'g')
                 = regexp_replace(btrim(lower(%s)), '\s+', ' ', 'g')
             ORDER BY id_organisme
             LIMIT 1
            """,
            [nom_organisme],
            fetch="one",
        )
        if row:
            return NouvelOrganisme(int(row[0]), str(row[1]))
    return None


# Colonnes que l'ancien PUT /role acceptait de modifier. Tout le reste (organisme,
# active, groupe, uuid_role…) était en liste noire et le reste ici.
UPDATABLE_PROFILE_COLUMNS = ("identifiant", "nom_role", "prenom_role", "email", "remarques")


def update_role_profile(id_role: int, **values) -> None:
    """Met à jour les colonnes de profil, en ignorant celles laissées à ``None``."""
    assignments = []
    params: list = []
    for column in UPDATABLE_PROFILE_COLUMNS:
        value = values.get(column)
        if value is None:
            continue
        assignments.append(f"{column} = %s")
        params.append(value)
    if not assignments:
        return
    params.append(id_role)
    _execute(
        f"UPDATE utilisateurs.t_roles SET {', '.join(assignments)} WHERE id_role = %s",
        params,
    )


def deactivate_role(id_role: int) -> None:
    """Désactive un compte sans le supprimer (les lignes liées restent en place)."""
    _execute("UPDATE utilisateurs.t_roles SET active = false WHERE id_role = %s", [id_role])


def get_role_identifiant(id_role: int) -> str:
    """Identifiant historique du compte, celui que connaissent les applications RNF."""
    row = _execute(
        "SELECT identifiant FROM utilisateurs.t_roles WHERE id_role = %s", [id_role], fetch="one"
    )
    return (row[0] if row else "") or ""


def find_role_id(*, email: str = "", identifiant: str = "") -> int | None:
    """Retrouve un ``id_role`` par e-mail puis par identifiant.

    Repli pour les comptes dont l'attribut Keycloak ``legacy_id_role`` est absent.
    """
    for column, value in (("email", email), ("identifiant", identifiant)):
        cleaned = (value or "").strip()
        if not cleaned:
            continue
        row = _execute(
            f"SELECT id_role FROM utilisateurs.t_roles WHERE lower({column}) = lower(%s) "
            "AND COALESCE(groupe, false) = false ORDER BY id_role LIMIT 1",
            [cleaned],
            fetch="one",
        )
        if row:
            return int(row[0])
    return None


# --- Réserves ------------------------------------------------------------------


def get_champs_addi(id_role: int) -> dict:
    """Lit ``champs_addi``, en tolérant ``NULL`` et les valeurs non-objet."""
    row = _execute(
        "SELECT champs_addi FROM utilisateurs.t_roles WHERE id_role = %s", [id_role], fetch="one"
    )
    if not row or not row[0]:
        return {}
    value = row[0]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def build_reserves_payload(codes, referent_codes) -> tuple[list[dict], list[dict]]:
    """Construit les listes ``[{"id": code, "name": libellé}]`` du ``champs_addi``.

    Même forme que celle produite par l'ancien formulaire : ``id`` est l'``area_code``,
    ``name`` le libellé dénormalisé.
    """
    from inscriptions.models import Reserve

    wanted = {code for code in codes if code}
    names = dict(Reserve.objects.filter(area_code__in=wanted).values_list("area_code", "area_name"))
    reserves = [{"id": code, "name": names.get(code, code)} for code in sorted(wanted)]
    referents = [
        {"id": code, "name": names.get(code, code)}
        for code in sorted({c for c in referent_codes if c in wanted})
    ]
    return reserves, referents


def _set_champs_addi_reserves(id_role: int, codes, referent_codes) -> None:
    """Réécrit les seules clés de réserves, en préservant le reste du ``champs_addi``."""
    champs = get_champs_addi(id_role)
    champs["reserves"], champs["reserves_referent"] = build_reserves_payload(codes, referent_codes)
    _execute(
        "UPDATE utilisateurs.t_roles SET champs_addi = %s::jsonb WHERE id_role = %s",
        [json.dumps(champs), id_role],
    )


def sync_reserves(id_role: int, codes, referent_codes=()) -> None:
    """Aligne ``cor_role_rn`` et ``champs_addi`` sur les réserves voulues.

    Reprend la réconciliation de l'ancien ``PUT /role`` : suppression des réserves
    retirées, insertion des ajoutées avec ``referent_valid = false``, mise à jour du seul
    drapeau ``referent`` sur les réserves déjà présentes — leur ``referent_valid`` est
    conservé, pour ne pas invalider un référent déjà validé.
    """
    wanted = {code for code in codes if code}
    wanted_referents = {code for code in referent_codes if code in wanted}

    rows = _execute(
        "SELECT rn_id::text, COALESCE(referent, false) FROM complement_rnf.cor_role_rn "
        "WHERE role_id = %s",
        [id_role],
        fetch="all",
    )
    current = {code: referent for code, referent in (rows or [])}

    for code in set(current) - wanted:
        _execute(
            "DELETE FROM complement_rnf.cor_role_rn WHERE role_id = %s AND rn_id = %s",
            [id_role, code],
        )

    for code in wanted - set(current):
        _execute(
            "INSERT INTO complement_rnf.cor_role_rn (role_id, rn_id, referent, referent_valid) "
            "VALUES (%s, %s, %s, false)",
            [id_role, code, code in wanted_referents],
        )

    for code in wanted & set(current):
        referent = code in wanted_referents
        if referent != current[code]:
            _execute(
                "UPDATE complement_rnf.cor_role_rn SET referent = %s "
                "WHERE role_id = %s AND rn_id = %s",
                [referent, id_role, code],
            )

    _set_champs_addi_reserves(id_role, wanted, wanted_referents)


def list_reserve_codes(id_role: int) -> set[str]:
    """Codes des réserves actuellement liées au compte."""
    rows = _execute(
        "SELECT rn_id::text FROM complement_rnf.cor_role_rn WHERE role_id = %s",
        [id_role],
        fetch="all",
    )
    return {row[0] for row in (rows or [])}


def set_referent_valid(id_role: int, code: str, valid: bool) -> None:
    """Valide ou retire le statut de référent sur une réserve déjà liée.

    L'ancien backend ne savait pas le faire : la validation se faisait dans UsersHub.
    """
    _execute(
        "UPDATE complement_rnf.cor_role_rn SET referent = %s, referent_valid = %s "
        "WHERE role_id = %s AND rn_id = %s",
        [valid, valid, id_role, code],
    )


# --- Droits applicatifs --------------------------------------------------------


def grant_application(id_role: int, *, id_application: int | None = None, id_profil: int = 1,
                      group_id_role: int | None = None) -> None:
    """Accorde l'accès à une application : groupe, et droit applicatif si déclaré.

    Les deux sont indépendants. En pratique c'est le groupe qui porte l'accès :
    ``cor_role_app_profil`` n'est plus alimenté en production, aussi ``id_application``
    est-il optionnel. ``is_default_group_for_app`` reste à ``false``, un CHECK du
    schéma réservant ``true`` aux lignes de groupe.
    """
    if id_application:
        _execute(
            "INSERT INTO utilisateurs.cor_role_app_profil (id_role, id_application, id_profil) "
            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [id_role, id_application, id_profil],
        )
    if group_id_role:
        add_to_groups(id_role, [group_id_role])


def revoke_application(id_role: int, *, id_application: int | None = None,
                       group_id_role: int | None = None) -> None:
    """Retire le groupe de l'application, et ses profils applicatifs s'il y en a."""
    if id_application:
        _execute(
            "DELETE FROM utilisateurs.cor_role_app_profil "
            "WHERE id_role = %s AND id_application = %s",
            [id_role, id_application],
        )
    if group_id_role:
        _execute(
            "DELETE FROM utilisateurs.cor_roles "
            "WHERE id_role_groupe = %s AND id_role_utilisateur = %s",
            [group_id_role, id_role],
        )


def add_to_groups(id_role: int, group_ids) -> list[int]:
    """Rattache le compte à des groupes (``utilisateurs.cor_roles``).

    Chaque identifiant est vérifié avant insertion : une ligne absente, ou qui n'est
    pas un groupe, déclencherait une violation de clé étrangère et ferait échouer
    toute la création. Les identifiants écartés sont journalisés et renvoyés à vide.
    Renvoie la liste des groupes effectivement rattachés.
    """
    ajoutes: list[int] = []
    for group_id in group_ids:
        if not group_id:
            continue
        row = _execute(
            "SELECT COALESCE(groupe, false) FROM utilisateurs.t_roles WHERE id_role = %s",
            [group_id],
            fetch="one",
        )
        if not row:
            logger.warning("Groupe historique %s inexistant, rattachement ignoré", group_id)
            continue
        if not row[0]:
            logger.warning("Le rôle %s n'est pas un groupe, rattachement ignoré", group_id)
            continue
        _execute(
            "INSERT INTO utilisateurs.cor_roles (id_role_groupe, id_role_utilisateur) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [group_id, id_role],
        )
        ajoutes.append(int(group_id))
    return ajoutes


def list_group_ids(id_role: int) -> set[int]:
    """Groupes historiques auxquels le compte appartient."""
    rows = _execute(
        "SELECT id_role_groupe FROM utilisateurs.cor_roles WHERE id_role_utilisateur = %s",
        [id_role],
        fetch="all",
    )
    return {int(r[0]) for r in (rows or [])}


def list_application_ids(id_role: int) -> set[int]:
    """Applications historiques sur lesquelles le compte a au moins un profil."""
    rows = _execute(
        "SELECT DISTINCT id_application FROM utilisateurs.cor_role_app_profil WHERE id_role = %s",
        [id_role],
        fetch="all",
    )
    return {int(row[0]) for row in (rows or [])}
