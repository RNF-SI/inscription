"""Synchronisation du référentiel des réserves et des organismes depuis RADIS.

RADIS (equipe-app) est l'outil de gestion des données réserves ; son API v1 en est
la source publique, et c'est déjà d'elle que SOCLE tire ses sites. Le référentiel de
cette plateforme en descendait indirectement : ``migrate_legacy`` lisait
``ref_geo.l_areas``, ``utilisateurs.bib_organismes`` et ``complement_rnf.cor_rn_og``
de la base historique, que RADIS alimente par un *push* au fil des évènements. Ce
chemin pousse mais ne réconcilie jamais, et il perd ce qu'il n'a pas vu passer : le
relevé de bascule comptait 465 liens lus pour 451 créés, parce que ``cor_rn_og``
garde les liaisons terminées et rate les organismes dépourvus d'UUID SINP.

Ici l'état courant est tiré de l'API, comparé, appliqué. La synchronisation ne va que
dans ce sens : rien n'est jamais renvoyé vers RADIS.

Ce qu'elle ne fait jamais :

- **supprimer une réserve.** RADIS déclasse, il ne supprime pas. Les groupes Keycloak
  ``/reserves/<code>`` et les lignes ``cor_role_rn`` de ses membres référencent le
  code : la réserve est marquée ``ancienne_reserve`` et quitte les listes, sa ligne
  reste ;
- **supprimer ou désactiver un organisme.** La plateforme en porte plus que RADIS —
  tous les organismes ne gèrent pas une réserve — et un organisme absent de la réponse
  de RADIS est indiscernable d'un organisme qui n'en vient pas. Seuls ceux qui portent
  un ``radis_id`` sont comparés, et leur disparition est signalée, pas appliquée ;
- **créer un organisme.** ``Organisme.id_organisme`` est la clé primaire de
  ``utilisateurs.bib_organismes``, et ``legacy_writer`` l'écrit dans
  ``t_roles.id_organisme``, colonne qui référence cette table. Un identifiant inventé
  ici ferait échouer la création de compte de ses membres, puis entrerait en collision
  avec un futur ``id_organisme``. Un organisme de RADIS sans correspondance est donc
  signalé, pour être créé d'abord côté base historique ;
- **recalculer un ``keycloak_slug``.** Il est dans le chemin du groupe
  ``/organismes/<slug>``, donc dans les jetons déjà émis, et ``_organisme_for_request``
  s'en sert en repli. Un organisme renommé change de ``nom_organisme``, pas de slug ;
- **réécrire ce qui n'a pas changé**, pour qu'un rapport de passage nocturne ne
  mentionne que ce qui a bougé.

Les liens réserve ↔ organisme font exception à cette prudence : eux se suppriment.
Ils n'alimentent que la liste des réserves proposées d'après l'organisme — ce ne sont
pas des droits, qui viennent des groupes Keycloak — et un lien périmé y propose une
réserve que l'organisme ne gère plus.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any, Iterator

import requests
from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from django.utils.text import slugify

from inscriptions.models import Organisme, OrganismeReserveLink, Reserve, SynchroRadisRun
from inscriptions.services import legacy_writer, mirror
from inscriptions.services.legacy_writer import LegacyWriteError

logger = logging.getLogger(__name__)

# Les types que porte le référentiel de cette plateforme : ceux de
# ``ref_geo.l_areas`` filtrés par ``id_type IN ('5','6','18')`` à l'import, soit 376
# réserves. RADIS expose le type comme une nomenclature ; sa valeur courte est reprise
# après contrôle, plutôt que de risquer d'écrire un libellé long. Les périmètres de
# protection (« PP ») n'en font pas partie : on ne s'y rattache pas.
TYPES_RESERVES = ("RNN", "RNR", "RNC")

CLE_UUID = "uuid_organisme"


class ErreurRadis(Exception):
    """La synchronisation ne peut pas aboutir."""


class _Annulation(Exception):
    """Sentinelle de ``--a-blanc`` : annule la transaction sans la signaler comme un échec."""


def _appel(chemin: str, params: dict[str, Any] | None = None) -> dict:
    """GET sur l'API v1 de RADIS. Toute réponse non 200 arrête la synchronisation."""
    base = (settings.RADIS_API_URL or "").rstrip("/")
    cle = settings.RADIS_API_KEY
    if not base or not cle:
        raise ErreurRadis("RADIS_API_URL et RADIS_API_KEY doivent être renseignés dans .env")
    try:
        reponse = requests.get(
            f"{base}/api/v1{chemin}",
            headers={"X-API-Key": cle},
            params=params,
            timeout=settings.RADIS_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ErreurRadis(f"{chemin} injoignable : {exc}") from exc
    if reponse.status_code != 200:
        raise ErreurRadis(f"{chemin} a répondu {reponse.status_code} : {reponse.text[:200]}")
    return reponse.json()


def lire_inventaire() -> dict[str, dict]:
    """État d'ensemble des réserves de RADIS, déclassées incluses, indexé par code."""
    charge = _appel("/reserves/inventaire")
    return {
        item["id_local"]: item
        for item in (charge.get("items") or [])
        if item.get("id_local")
    }


def _pages(chemin: str, params: dict[str, Any]) -> Iterator[dict]:
    """Items d'un endpoint paginé, page par page."""
    page = 1
    while True:
        charge = _appel(chemin, {**params, "page": page, "per_page": settings.RADIS_PAGE_SIZE})
        items = charge.get("items") or []
        if not items:
            return
        yield from items
        if page >= (charge.get("pages") or 1):
            return
        page += 1


def lire_reserves() -> Iterator[dict]:
    """Réserves détaillées, gestionnaires en cours compris.

    ``ancienne_reserve=all`` lève le filtre par défaut de l'API : les déclassées
    doivent être lues pour que leur statut soit répercuté. ``geometry=none`` est le
    défaut de l'API et il est redonné à dessein — cette plateforme n'affiche aucun
    périmètre, et un polygone de réserve pèse plusieurs centaines de kilo-octets.
    """
    return _pages("/reserves", {"ancienne_reserve": "all", "geometry": "none"})


def lire_organismes() -> Iterator[dict]:
    """Organismes gestionnaires actifs de RADIS."""
    return _pages("/organismes", {})


def _type_rn(item: dict) -> str | None:
    """Code court du type de réserve, ou None s'il n'est pas reconnaissable."""
    nomenclature = item.get("type_rn")
    if isinstance(nomenclature, str):
        valeurs = [nomenclature]
    elif isinstance(nomenclature, dict):
        valeurs = [nomenclature.get("mnemonique"), nomenclature.get("label")]
    else:
        return None
    for valeur in valeurs:
        if valeur and str(valeur).strip().upper() in TYPES_RESERVES:
            return str(valeur).strip().upper()
    return None


def _date(valeur: Any) -> datetime.date | None:
    if not valeur:
        return None
    try:
        return datetime.date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


class _Correspondance:
    """Rapprochement des organismes de RADIS et de ceux de la plateforme.

    Construite une fois, en mémoire, pour deux raisons : la résolution d'un lien n'a
    pas à rouvrir une requête par réserve, et surtout ``--a-blanc`` annule ses
    transactions — un ``radis_id`` qu'elle vient de poser ne serait pas relisible.
    """

    def __init__(self, items_radis: list[dict]) -> None:
        self.par_radis_id: dict[int, Organisme] = {}
        self.par_uuid: dict[str, Organisme] = {}
        # UUID que plusieurs organismes de RADIS se partagent : la production en
        # compte dix, et ils ne désignent pas des doublons mais des organismes sans
        # rapport — « Conservatoire d'espaces naturels Centre-Val de Loire », la DREAL
        # et la Région portent le même UUID du SINP. Rapprocher par cette valeur
        # renommerait le conservatoire en région. Un UUID partagé n'est donc pas une
        # clé : il est signalé, et les organismes concernés ne sont pas rapprochés.
        comptes: dict[str, int] = {}
        for item in items_radis:
            uuid_org = (item.get(CLE_UUID) or "").strip().lower()
            if uuid_org:
                comptes[uuid_org] = comptes.get(uuid_org, 0) + 1
        self.uuids_ambigus = {uuid_org for uuid_org, n in comptes.items() if n > 1}
        # Clés primaires des organismes dont RADIS a la charge. C'est cet ensemble, et
        # non la colonne relue en base, qui dit quels liens sont réconciliables : un
        # passage à blanc annule les ``radis_id`` qu'il vient de poser.
        self.pks_radis: set[int] = set()
        for org in Organisme.objects.all():
            if org.radis_id is not None:
                self.par_radis_id[org.radis_id] = org
                self.pks_radis.add(org.pk)
            uuid_org = (org.uuid_organisme or "").strip().lower()
            if uuid_org:
                self.par_uuid[uuid_org] = org

    def resoudre(self, item: dict) -> Organisme | None:
        """Organisme de la plateforme correspondant à un organisme de RADIS.

        Par ``radis_id`` d'abord — la seule clé qui survive à un changement de nom
        comme d'UUID — puis par ``uuid_organisme``, celui du référentiel des organismes
        du SINP, qui est la clé primaire du rapprochement initial : c'est la valeur que
        porte ``utilisateurs.bib_organismes.uuid_organisme``. Jamais par le nom, qu'un
        organisme renommé dans Assoconnect rendrait inopérant.
        """
        radis_id = item.get("id")
        if isinstance(radis_id, int) and radis_id in self.par_radis_id:
            return self.par_radis_id[radis_id]
        uuid_org = (item.get(CLE_UUID) or "").strip().lower()
        if uuid_org and uuid_org not in self.uuids_ambigus:
            return self.par_uuid.get(uuid_org)
        return None

    def uuid_utilisable(self, item: dict) -> str:
        """UUID du SINP de cet organisme, vide s'il est partagé avec un autre."""
        uuid_org = (item.get(CLE_UUID) or "").strip()
        if not uuid_org or uuid_org.lower() in self.uuids_ambigus:
            return ""
        return uuid_org

    def enregistrer(self, org: Organisme, radis_id: int | None) -> None:
        """Prend en compte un organisme créé à l'instant, pour la suite du passage."""
        if isinstance(radis_id, int):
            self.par_radis_id[radis_id] = org
        uuid_org = (org.uuid_organisme or "").strip().lower()
        if uuid_org:
            self.par_uuid[uuid_org] = org
        self.pks_radis.add(org.pk)

    def rattacher(self, org: Organisme, radis_id: int) -> None:
        self.par_radis_id[radis_id] = org
        self.pks_radis.add(org.pk)


def _rapport_vide(a_blanc: bool) -> dict:
    return {
        "debut": datetime.datetime.now(),
        "a_blanc": a_blanc,
        "reserves_radis": 0,
        "reserves_creees": [],
        "reserves_modifiees": [],
        "reserves_inchangees": 0,
        "reserves_ignorees": [],
        "reserves_declassees": [],
        "reserves_supprimees": [],
        "reserves_absentes_ref_geo": [],
        "ref_geo_consulte": False,
        "organismes_radis": 0,
        "organismes_rattaches": [],
        "organismes_crees": [],
        "organismes_adoptes": [],
        "organismes_non_creables": [],
        "organismes_uuid_partage": [],
        "creation_organismes": False,
        "organismes_renommes": [],
        "organismes_sans_correspondance": [],
        "organismes_disparus_de_radis": [],
        "liens_crees": 0,
        "liens_modifies": 0,
        "liens_supprimes": 0,
    }


def _creer_organisme(
    item: dict, correspondance: _Correspondance, rapport: dict, a_blanc: bool
) -> None:
    """Crée l'organisme dans ``bib_organismes`` puis ici, avec l'identifiant qu'elle donne.

    L'ordre est imposé : ``Organisme.id_organisme`` **est** la clé primaire de
    ``utilisateurs.bib_organismes``, que ``legacy_writer`` écrit dans
    ``t_roles.id_organisme`` — colonne qui la référence. L'identifiant ne peut donc pas
    être choisi ici ; il est généré par la séquence de la base historique, et la ligne
    locale le reprend. Un organisme créé ici sans ligne historique ferait échouer la
    création de compte de chacun de ses membres.

    Un organisme déjà présent dans ``bib_organismes`` — posé à la main, ou par le push
    de RADIS vers GeoNature — est adopté plutôt que dupliqué.
    """
    nom = (item.get("name") or "").strip()
    radis_id = item.get("id")
    if not nom:
        rapport["organismes_non_creables"].append((radis_id, "nom absent"))
        return

    uuid_radis = correspondance.uuid_utilisable(item)
    adresse = " ".join(
        part for part in [(item.get("street1") or "").strip(), (item.get("street2") or "").strip()] if part
    )
    try:
        # La recherche est en lecture seule : elle a lieu même à blanc, pour que le
        # rapport distingue ce qui serait adopté de ce qui serait vraiment créé. Les
        # noms de bib_organismes étant ce qu'ils sont, l'écart est de vingt-trois
        # organismes sur cent soixante-treize.
        existant = legacy_writer.find_organisme(uuid_organisme=uuid_radis, nom_organisme=nom)
        if a_blanc:
            if existant is None:
                rapport["organismes_crees"].append((None, nom))
            else:
                rapport["organismes_adoptes"].append((existant.id_organisme, nom))
            return
        with mirror.atomic_mirror():
            if existant is None:
                existant = legacy_writer.create_organisme(
                    nom_organisme=nom,
                    uuid_organisme=uuid_radis or None,
                    adresse_organisme=adresse,
                    cp_organisme=(item.get("postal_code") or "").strip(),
                    ville_organisme=(item.get("city") or "").strip(),
                    url_logo=(item.get("logo_url") or "").strip(),
                )
                rapport["organismes_crees"].append((existant.id_organisme, nom))
            else:
                rapport["organismes_adoptes"].append((existant.id_organisme, nom))

            org, cree = Organisme.objects.get_or_create(
                id_organisme=existant.id_organisme,
                defaults={
                    "uuid_organisme": existant.uuid_organisme,
                    "nom_organisme": nom,
                    # Le slug n'est posé qu'à la création, ici comme ailleurs : il
                    # entre dans le chemin du groupe Keycloak /organismes/<slug>.
                    "keycloak_slug": slugify(nom)[:200] or f"org-{existant.id_organisme}",
                    "radis_id": radis_id if isinstance(radis_id, int) else None,
                },
            )
            if not cree:
                # Ligne locale déjà là : l'adoption lui apporte sa clé RADIS et son
                # nom. Sans ce renommage, l'organisme adopté sur son nom normalisé —
                # « Parc National de la Réunion » contre « Parc national de la
                # Réunion » — ne se corrigeait qu'au passage suivant, et le second
                # passage n'était donc pas sans effet.
                champs = []
                if org.radis_id is None and isinstance(radis_id, int):
                    org.radis_id = radis_id
                    champs.append("radis_id")
                if nom != org.nom_organisme:
                    rapport["organismes_renommes"].append((org.pk, org.nom_organisme, nom))
                    org.nom_organisme = nom
                    champs.append("nom_organisme")
                if champs:
                    org.save(update_fields=champs)
            correspondance.enregistrer(org, radis_id)
    except LegacyWriteError as exc:
        logger.warning("Création de l'organisme « %s » impossible : %s", nom, exc)
        rapport["organismes_non_creables"].append((radis_id, str(exc)))


def _appliquer_organismes(
    items: list[dict],
    correspondance: _Correspondance,
    rapport: dict,
    a_blanc: bool,
    creer: bool,
) -> None:
    """Rapproche les organismes de RADIS, met à jour leur nom, crée les manquants.

    Le nom seulement : l'adresse et le logo ne servent pas ici, et le
    ``keycloak_slug`` ne se recalcule jamais.
    """
    vus: set[int] = set()
    try:
        with transaction.atomic():
            for item in items:
                rapport["organismes_radis"] += 1
                radis_id = item.get("id")
                nom = (item.get("name") or "").strip()
                if correspondance.uuid_utilisable(item) == "" and (item.get(CLE_UUID) or "").strip():
                    rapport["organismes_uuid_partage"].append(
                        (radis_id, nom, (item.get(CLE_UUID) or "").strip())
                    )
                org = correspondance.resoudre(item)
                if org is None:
                    rapport["organismes_sans_correspondance"].append((radis_id, nom))
                    if creer:
                        _creer_organisme(item, correspondance, rapport, a_blanc)
                    continue
                if isinstance(radis_id, int):
                    vus.add(radis_id)
                champs: list[str] = []
                if org.radis_id != radis_id and isinstance(radis_id, int):
                    org.radis_id = radis_id
                    champs.append("radis_id")
                    correspondance.enregistrer(org, radis_id)
                    rapport["organismes_rattaches"].append((org.pk, radis_id))
                if nom and nom != org.nom_organisme:
                    rapport["organismes_renommes"].append((org.pk, org.nom_organisme, nom))
                    org.nom_organisme = nom
                    champs.append("nom_organisme")
                if champs:
                    org.save(update_fields=champs)

            # Un organisme qui porte un radis_id et que RADIS ne renvoie plus : il a
            # été désactivé là-bas, ou il a changé d'identifiant. Signalé seulement —
            # ses membres existent, et la liste du formulaire d'inscription relève
            # d'une décision, pas d'une déduction.
            for org in Organisme.objects.exclude(radis_id=None):
                if org.radis_id not in vus:
                    rapport["organismes_disparus_de_radis"].append((org.pk, org.nom_organisme))

            if a_blanc:
                raise _Annulation
    except _Annulation:
        pass


def _appliquer_reserve(item: dict, rapport: dict) -> Reserve | None:
    """Crée ou met à jour une réserve. Renvoie la ligne, ou None si elle est écartée."""
    code = (item.get("id_local") or "").strip()
    nom = (item.get("nom_site") or "").strip()
    if not code or not nom:
        rapport["reserves_ignorees"].append((code or "?", "id_local ou nom_site absent"))
        return None

    existante = Reserve.objects.filter(pk=code).first()
    type_rn = _type_rn(item)
    if type_rn is None and existante is None:
        # Périmètre de protection, type nouveau, nomenclature inattendue : créer la
        # ligne proposerait au formulaire d'inscription une réserve dont on ne sait
        # rien. Une réserve déjà connue, elle, garde le type qu'elle a.
        rapport["reserves_ignorees"].append((code, f"type_rn non reconnu : {item.get('type_rn')!r}"))
        return None

    valeurs = {
        "area_name": nom,
        "ancienne_reserve": bool(item.get("ancienne_reserve")),
        "date_declassement": _date(item.get("date_declassement")),
    }
    if type_rn is not None:
        valeurs["type_rn"] = type_rn

    if existante is None:
        rapport["reserves_creees"].append(code)
        return Reserve.objects.create(area_code=code, **valeurs)

    modifies = [champ for champ, valeur in valeurs.items() if getattr(existante, champ) != valeur]
    if modifies:
        for champ in modifies:
            setattr(existante, champ, valeurs[champ])
        existante.save(update_fields=modifies)
        rapport["reserves_modifiees"].append(code)
    else:
        rapport["reserves_inchangees"] += 1
    return existante


def _appliquer_liens(
    reserve: Reserve,
    item: dict,
    correspondance: _Correspondance,
    rapport: dict,
) -> None:
    """Aligne les liens de la réserve sur ses gestionnaires en cours.

    La liste de RADIS ne porte que les gestionnaires en cours (``date_fin`` nulle) et
    actifs ; la garde sur ``date_fin`` est reprise ici pour que la synchronisation ne
    dépende pas de ce filtrage côté serveur.

    Seuls les liens d'organismes connus de RADIS sont réconciliés. Ceux des organismes
    propres à la plateforme ne viennent pas d'ici et ne sont pas touchés.
    """
    voulus: dict[int, bool] = {}
    for liaison in item.get("organismes") or []:
        if not isinstance(liaison, dict) or liaison.get("date_fin"):
            continue
        org_item = liaison.get("organisme") or {}
        org = correspondance.resoudre(org_item)
        if org is None:
            continue
        # RADIS le donne pour gestionnaire : ses liens sont donc réconciliables, même
        # si la liste des organismes ne l'a pas encore rapproché (page manquée,
        # organisme apparu entre les deux appels).
        correspondance.pks_radis.add(org.pk)
        principal = bool(liaison.get("gestionnaire_principal"))
        # Une réserve peut être listée deux fois pour le même organisme (antennes) :
        # le lien est principal si l'une des liaisons l'est.
        voulus[org.pk] = voulus.get(org.pk, False) or principal

    existants = {
        lien.organisme_id: lien
        for lien in OrganismeReserveLink.objects.filter(reserve=reserve)
        if lien.organisme_id in correspondance.pks_radis
    }

    for org_id, principal in voulus.items():
        lien = existants.get(org_id)
        if lien is None:
            OrganismeReserveLink.objects.create(
                organisme_id=org_id, reserve=reserve, principal=principal
            )
            rapport["liens_crees"] += 1
        elif lien.principal != principal:
            lien.principal = principal
            lien.save(update_fields=["principal"])
            rapport["liens_modifies"] += 1

    for org_id, lien in existants.items():
        if org_id not in voulus:
            lien.delete()
            rapport["liens_supprimes"] += 1


def _marquer_absentes_de_ref_geo(codes: set[str], rapport: dict, a_blanc: bool) -> None:
    """Marque les réserves que ``ref_geo.l_areas`` ignore.

    Sans la connexion historique, rien n'est touché : remettre tout le monde à
    « présente » parce que la base n'est pas joignable rendrait sélectionnables des
    réserves dont la base refuse le rattachement.
    """
    if "legacy" not in connections.databases or not codes:
        return
    try:
        with connections["legacy"].cursor() as c:
            c.execute(
                "SELECT area_code::text FROM ref_geo.l_areas WHERE area_code::text = ANY(%s)",
                [list(codes)],
            )
            presentes = {row[0] for row in c.fetchall()}
    except Exception as exc:  # pragma: no cover - dépend de la base historique
        logger.warning("ref_geo.l_areas illisible, absente_ref_geo laissé tel quel : %s", exc)
        return

    rapport["ref_geo_consulte"] = True
    absentes = sorted(codes - presentes)
    rapport["reserves_absentes_ref_geo"] = absentes
    if a_blanc:
        return
    Reserve.objects.filter(pk__in=absentes, absente_ref_geo=False).update(absente_ref_geo=True)
    Reserve.objects.filter(pk__in=presentes, absente_ref_geo=True).update(absente_ref_geo=False)


def synchroniser(*, a_blanc: bool = False, creer_organismes: bool = True) -> dict:
    """Applique l'état de RADIS au référentiel local. Renvoie un rapport."""
    inventaire = lire_inventaire()
    if not inventaire:
        # Appliquer un inventaire vide reviendrait à déclarer tout le réseau déclassé.
        raise ErreurRadis("L'inventaire RADIS est vide : rien n'est appliqué")

    rapport = _rapport_vide(a_blanc)
    rapport["reserves_radis"] = len(inventaire)
    rapport["reserves_declassees"] = sorted(
        code for code, item in inventaire.items() if item.get("ancienne_reserve")
    )

    # Les organismes sont lus d'un bloc — ils tiennent en quatre pages — parce que le
    # rapprochement a besoin de la liste entière avant de commencer : un UUID du SINP
    # que deux organismes de RADIS se partagent n'est pas une clé, et on ne peut le
    # savoir qu'en les ayant tous vus.
    items_organismes = list(lire_organismes())
    correspondance = _Correspondance(items_organismes)
    creer = creer_organismes and legacy_writer.is_enabled()
    rapport["creation_organismes"] = creer
    _appliquer_organismes(items_organismes, correspondance, rapport, a_blanc, creer)

    # Une transaction par page, et non une pour toute la synchronisation : la lecture
    # de RADIS prend plusieurs secondes par page et garder une transaction ouverte
    # pendant ce temps tiendrait des verrous pour rien. Chaque réserve est
    # indépendante. Les liens d'une réserve sont posés dans la même transaction que la
    # réserve elle-même, pour qu'un passage à blanc annule les deux ensemble.
    page: list[dict] = []
    codes_radis: set[str] = set()

    def appliquer_page(items: list[dict]) -> None:
        try:
            with transaction.atomic():
                for item in items:
                    reserve = _appliquer_reserve(item, rapport)
                    if reserve is not None:
                        codes_radis.add(reserve.pk)
                        _appliquer_liens(reserve, item, correspondance, rapport)
                if a_blanc:
                    raise _Annulation
        except _Annulation:
            pass

    for item in lire_reserves():
        page.append(item)
        if len(page) >= settings.RADIS_PAGE_SIZE:
            appliquer_page(page)
            page = []
    if page:
        appliquer_page(page)

    # La liste de RADIS fait loi : une réserve que son inventaire ne contient pas n'a
    # pas à rester ici. L'inventaire porte aussi les déclassées, donc une absence y
    # signifie bien « cette réserve n'existe pas », pas « elle est sortie du réseau ».
    # La suppression emporte les liens de la réserve et les demandes en attente qui la
    # visent (référent, retrait de membre) — pas les rattachements eux-mêmes, qui
    # vivent dans Keycloak et dans cor_role_rn. C'est pourquoi le passage à blanc
    # existe : il donne la liste avant qu'elle ne soit appliquée.
    inconnues = [
        (code, nom)
        for code, nom in Reserve.objects.order_by("area_name").values_list("area_code", "area_name")
        if code not in inventaire
    ]
    rapport["reserves_supprimees"] = inconnues
    if inconnues and not a_blanc:
        Reserve.objects.filter(pk__in=[code for code, _ in inconnues]).delete()

    _marquer_absentes_de_ref_geo(set(inventaire) & codes_radis, rapport, a_blanc)

    return rapport


def resume(rapport: dict) -> dict:
    """Résumé JSON du rapport, pour ``SynchroRadisRun.report``.

    Le rapport brut porte un ``datetime`` et des listes de tuples : JSON n'en veut
    pas tel quel. Les comptes suffisent partout, **sauf** là où la liste est l'action
    à mener — réserves créées ou supprimées, organismes à créer dans ``bib_organismes``,
    UUID du SINP partagés, réserves absentes de ``ref_geo.l_areas``. Celles-là sont
    conservées entières : c'est ce qu'un validateur doit pouvoir relire le lendemain.
    """
    return {
        "a_blanc": bool(rapport["a_blanc"]),
        "reserves": {
            "radis": rapport["reserves_radis"],
            "creees": list(rapport["reserves_creees"]),
            "modifiees": len(rapport["reserves_modifiees"]),
            "inchangees": rapport["reserves_inchangees"],
            "supprimees": [list(x) for x in rapport["reserves_supprimees"]],
            "declassees": len(rapport["reserves_declassees"]),
            "ignorees": [list(x) for x in rapport["reserves_ignorees"]],
            "absentes_ref_geo": list(rapport["reserves_absentes_ref_geo"]),
            "ref_geo_consulte": bool(rapport["ref_geo_consulte"]),
        },
        "organismes": {
            "radis": rapport["organismes_radis"],
            "rattaches": len(rapport["organismes_rattaches"]),
            "renommes": [list(x) for x in rapport["organismes_renommes"]],
            "crees": [list(x) for x in rapport["organismes_crees"]],
            "adoptes": len(rapport["organismes_adoptes"]),
            "sans_correspondance": len(rapport["organismes_sans_correspondance"]),
            "uuid_partage": [list(x) for x in rapport["organismes_uuid_partage"]],
            "non_creables": [list(x) for x in rapport["organismes_non_creables"]],
            "disparus_de_radis": [list(x) for x in rapport["organismes_disparus_de_radis"]],
            "creation_active": bool(rapport["creation_organismes"]),
        },
        "liens": {
            "crees": rapport["liens_crees"],
            "modifies": rapport["liens_modifies"],
            "supprimes": rapport["liens_supprimes"],
        },
    }


def executer(
    *,
    a_blanc: bool = False,
    creer_organismes: bool = True,
    declencheur: str = SynchroRadisRun.DECLENCHEUR_COMMANDE,
    actor_sub: str = "",
) -> tuple[SynchroRadisRun, dict]:
    """Synchronise et journalise le passage. Renvoie la trace et le rapport brut.

    Point d'entrée unique de la commande comme de la route d'administration : le
    bouton et le minuteur laissent donc la même trace, et l'un voit ce que l'autre a
    fait. La ligne est créée avant l'appel pour qu'un passage interrompu — processus
    tué, timeout — reste visible avec ``finished_at`` vide plutôt que de disparaître.
    """
    passage = SynchroRadisRun.objects.create(
        declencheur=declencheur, actor_sub=actor_sub, a_blanc=a_blanc
    )
    try:
        rapport = synchroniser(a_blanc=a_blanc, creer_organismes=creer_organismes)
    except Exception as exc:
        passage.ok = False
        passage.error = str(exc)[:2000]
        passage.finished_at = timezone.now()
        passage.save(update_fields=["ok", "error", "finished_at"])
        raise
    passage.ok = True
    passage.report = resume(rapport)
    passage.finished_at = timezone.now()
    passage.save(update_fields=["ok", "report", "finished_at"])
    return passage, rapport
