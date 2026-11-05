"""Tests d'intégration de l'écriture miroir, sur un PostgreSQL jetable.

Ces tests **écrivent et suppriment des schémas entiers**. Ils refusent donc de
s'exécuter si le nom de la base ne contient pas « test », ou s'il ressemble à une base
de production. Ne les pointez jamais vers geonature_global.

  createdb inscription_legacy_test
  # .env local :
  #   LEGACY_DATABASE_URL=postgres://user:pass@localhost:5432/inscription_legacy_test
  export LEGACY_TEST_INTEGRATION=1
  DJANGO_SETTINGS_MODULE=config.settings \\
    python manage.py test inscriptions.tests.test_legacy_integration

Ce qu'ils vérifient, et qui ne peut pas l'être en test unitaire :

* le SQL produit est accepté par un vrai PostgreSQL (noms de colonnes, cast jsonb) ;
* ``cor_role_rn`` est bien peuplé par le trigger ``after_insert_user_function`` à la
  création, et la plateforme n'y ajoute pas de doublon ;
* les triggers de diffusion alimentent les bases satellites et le site internet.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from unittest import SkipTest, skipUnless

from django.conf import settings
from django.db import connections
from django.test import TestCase, override_settings

from inscriptions.models import Reserve
from inscriptions.services import legacy_writer

SCHEMA_SQL = Path(__file__).resolve().parent / "sql" / "legacy_schema.sql"

_FORBIDDEN_NAMES = {"geonature_global", "geonature2db", "geonature", "production", "prod"}


def _integration_enabled() -> bool:
    if os.environ.get("LEGACY_TEST_INTEGRATION", "") != "1":
        return False
    return "legacy" in settings.DATABASES


def _database_name() -> str:
    return str(settings.DATABASES.get("legacy", {}).get("NAME") or "").strip().lower()


@skipUnless(_integration_enabled(), "LEGACY_TEST_INTEGRATION=1 et LEGACY_DATABASE_URL requis")
@override_settings(LEGACY_WRITE_ENABLED=True)
class LegacyIntegrationTests(TestCase):
    databases = {"default", "legacy"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        name = _database_name()
        if name in _FORBIDDEN_NAMES or "test" not in name:
            raise SkipTest(
                f"Base « {name} » refusée : ces tests effacent des schémas entiers. "
                "Pointez LEGACY_DATABASE_URL vers une base jetable dont le nom "
                "contient « test »."
            )
        # Le nom ne suffit pas : une copie de production s'appelle volontiers
        # « …_test ». Ces tests attendent une base vide ; la présence de comptes
        # signale une vraie base, qu'il ne faut surtout pas vider.
        with connections["legacy"].cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('utilisateurs.t_roles') IS NOT NULL"
            )
            if cursor.fetchone()[0]:
                cursor.execute("SELECT count(*) FROM utilisateurs.t_roles")
                existants = cursor.fetchone()[0]
                if existants:
                    raise SkipTest(
                        f"Base « {name} » refusée : elle contient déjà {existants} "
                        "comptes dans utilisateurs.t_roles. Ces tests effacent les "
                        "schémas utilisateurs, complement_rnf et ref_geo — n'utilisez "
                        "qu'une base vide."
                    )
        with connections["legacy"].cursor() as cursor:
            for schema in ("utilisateurs", "utilisateurs_saisie", "utilisateurs_sinp",
                           "complement_rnf", "ref_geo"):
                cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cursor.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    def setUp(self):
        super().setUp()
        # build_reserves_payload lit les libellés dans la base Django (alimentée en
        # production par migrate_legacy) : sans ces lignes, champs_addi retomberait
        # sur le code comme libellé.
        Reserve.objects.create(area_code="RNN41", area_name="Grand Lieu")
        Reserve.objects.create(area_code="RNN99", area_name="Camargue")

    def _query(self, sql, params=None):
        with connections["legacy"].cursor() as cursor:
            cursor.execute(sql, params or [])
            return cursor.fetchall()

    def _create(self, **overrides):
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "identifiant": f"jdupont-{suffix}",
            "nom_role": "Dupont",
            "prenom_role": "Jean",
            "email": f"jean-{suffix}@example.org",
            "remarques": "Chargé de mission",
            "id_organisme": 1,
            "password": "secret-123",
            "champs_addi": {
                "reserves": [{"id": "RNN41", "name": "Grand Lieu"}],
                "reserves_referent": [{"id": "RNN41", "name": "Grand Lieu"}],
                "ancrage": True,
            },
        }
        payload.update(overrides)
        return legacy_writer.create_role(**payload)

    def test_create_organisme_returns_the_generated_id(self):
        """L'id_organisme vient de la séquence : c'est lui que porte Organisme ici, et
        que t_roles.id_organisme référencera pour chaque membre."""
        cree = legacy_writer.create_organisme(
            nom_organisme="Agence de l'eau Loire-Bretagne",
            uuid_organisme=None,
            adresse_organisme="9 avenue Buffon",
            cp_organisme="45100",
            ville_organisme="Orléans",
            url_logo="https://radis.example/logo.png",
        )
        rows = self._query(
            "SELECT nom_organisme, uuid_organisme::text, adresse_organisme, cp_organisme, "
            "ville_organisme, url_logo FROM utilisateurs.bib_organismes WHERE id_organisme = %s",
            [cree.id_organisme],
        )
        self.assertEqual(
            rows,
            [
                (
                    "Agence de l'eau Loire-Bretagne",
                    cree.uuid_organisme,
                    "9 avenue Buffon",
                    "45100",
                    "Orléans",
                    "https://radis.example/logo.png",
                )
            ],
        )

    def test_create_organisme_honours_the_sinp_uuid(self):
        """Quand RADIS en connaît un, c'est lui qui devient la clé de jointure."""
        uuid_sinp = str(uuid.uuid4())
        cree = legacy_writer.create_organisme(
            nom_organisme="Syndicat mixte de test", uuid_organisme=uuid_sinp
        )
        self.assertEqual(cree.uuid_organisme, uuid_sinp)
        self.assertEqual(
            legacy_writer.find_organisme(uuid_organisme=uuid_sinp).id_organisme,
            cree.id_organisme,
        )

    def test_find_organisme_matches_name_without_case(self):
        cree = legacy_writer.create_organisme(nom_organisme="Mairie de Sélestat")
        trouve = legacy_writer.find_organisme(nom_organisme="mairie de sélestat")
        self.assertEqual(trouve.id_organisme, cree.id_organisme)

    def test_create_role_returns_the_row_uuid(self):
        """L'uuid_role remonté devient l'identifiant du compte Keycloak : s'il ne
        correspondait pas à la ligne, le « sub » des jetons ne joindrait rien."""
        role = self._create()
        rows = self._query(
            "SELECT uuid_role::text FROM utilisateurs.t_roles WHERE id_role = %s",
            [role.id_role],
        )
        self.assertEqual(rows, [(role.uuid_role,)])

    def test_create_role_fills_expected_columns(self):
        id_role = self._create().id_role
        rows = self._query(
            "SELECT identifiant, nom_role, prenom_role, remarques, id_organisme, "
            "active, groupe, pass_plus, uuid_role IS NOT NULL, date_insert IS NOT NULL "
            "FROM utilisateurs.t_roles WHERE id_role = %s",
            [id_role],
        )
        self.assertEqual(len(rows), 1)
        (_identifiant, nom, prenom, remarques, id_org, active, groupe,
         pass_plus, has_uuid, has_date) = rows[0]
        self.assertEqual((nom, prenom, remarques, id_org), ("Dupont", "Jean", "Chargé de mission", 1))
        # Valeurs laissées à PostgreSQL et aux triggers.
        self.assertTrue(active)
        self.assertFalse(groupe)
        self.assertTrue(has_uuid)
        self.assertTrue(has_date)
        self.assertTrue(pass_plus.startswith("$2b$12$"))

    def test_trigger_creates_reserve_links_without_duplicates(self):
        """Le piège principal : cor_role_rn vient du trigger, pas de la plateforme."""
        id_role = self._create().id_role
        rows = self._query(
            "SELECT rn_id, referent FROM complement_rnf.cor_role_rn WHERE role_id = %s "
            "ORDER BY rn_id",
            [id_role],
        )
        self.assertEqual(rows, [("RNN41", True)])

    def test_downstream_triggers_receive_the_account(self):
        id_role = self._create().id_role
        for table in ("utilisateurs_saisie.t_roles", "utilisateurs_sinp.t_roles"):
            rows = self._query(f"SELECT count(*) FROM {table} WHERE id_role = %s", [id_role])
            self.assertEqual(rows[0][0], 1, table)
        site = self._query(
            "SELECT password FROM complement_rnf.site_internet_utilisateurs WHERE id_role = %s",
            [id_role],
        )
        self.assertEqual(len(site), 1)
        self.assertTrue(site[0][0].startswith("$2b$12$"))

    def test_sync_reserves_reconciles_without_touching_validated_referent(self):
        id_role = self._create().id_role
        # La réserve existe déjà via le trigger ; on la valide comme référent.
        legacy_writer.set_referent_valid(id_role, "RNN41", True)
        legacy_writer.sync_reserves(id_role, {"RNN41", "RNN99"}, {"RNN41"})

        rows = dict(
            (code, (referent, valid))
            for code, referent, valid in self._query(
                "SELECT rn_id, referent, referent_valid FROM complement_rnf.cor_role_rn "
                "WHERE role_id = %s",
                [id_role],
            )
        )
        self.assertEqual(rows["RNN41"], (True, True))   # validation préservée
        self.assertEqual(rows["RNN99"], (False, False))  # nouvelle réserve

        legacy_writer.sync_reserves(id_role, {"RNN99"}, set())
        remaining = legacy_writer.list_reserve_codes(id_role)
        self.assertEqual(remaining, {"RNN99"})

    def test_sync_reserves_preserves_other_champs_addi_keys(self):
        id_role = self._create().id_role
        legacy_writer.sync_reserves(id_role, {"RNN99"}, set())
        champs = legacy_writer.get_champs_addi(id_role)
        self.assertTrue(champs["ancrage"])
        self.assertEqual(champs["reserves"], [{"id": "RNN99", "name": "Camargue"}])

    def test_application_rights_and_group(self):
        id_role = self._create().id_role
        legacy_writer.grant_application(id_role, id_application=6, id_profil=1)
        rows = self._query(
            "SELECT id_application, id_profil, is_default_group_for_app "
            "FROM utilisateurs.cor_role_app_profil WHERE id_role = %s",
            [id_role],
        )
        self.assertEqual(rows, [(6, 1, False)])

        # Idempotent : un second appel ne doit pas lever.
        legacy_writer.grant_application(id_role, id_application=6, id_profil=1)

        legacy_writer.revoke_application(id_role, id_application=6)
        self.assertEqual(legacy_writer.list_application_ids(id_role), set())

    def test_update_profile_and_password(self):
        id_role = self._create().id_role
        legacy_writer.update_role_profile(id_role, email="neuf@example.org", nom_role="Durand")
        legacy_writer.set_password(id_role, "nouveau-mdp")
        rows = self._query(
            "SELECT email, nom_role, prenom_role, pass_plus FROM utilisateurs.t_roles "
            "WHERE id_role = %s",
            [id_role],
        )
        email, nom, prenom, pass_plus = rows[0]
        self.assertEqual((email, nom), ("neuf@example.org", "Durand"))
        self.assertEqual(prenom, "Jean")  # non fourni : inchangé
        self.assertTrue(pass_plus.startswith("$2b$12$"))

        site = self._query(
            "SELECT email, password FROM complement_rnf.site_internet_utilisateurs "
            "WHERE id_role = %s",
            [id_role],
        )
        self.assertEqual(site[0][0], "neuf@example.org")
        self.assertEqual(site[0][1], pass_plus)
