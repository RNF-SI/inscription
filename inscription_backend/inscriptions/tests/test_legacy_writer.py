"""Tests de l'écriture miroir vers la base historique.

La suite reste hermétique : aucun PostgreSQL n'est joint. Les tests qui vérifient le
SQL produit remplacent la connexion « legacy » par un curseur bouchonné, ce qui permet
d'affirmer quelles colonnes sont écrites — c'est précisément ce que la mise en
production doit garantir à l'identique de l'ancien système.
"""

import hashlib
from contextlib import contextmanager
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from inscriptions.models import Application, Organisme, RegistrationRequest, Reserve
from inscriptions.services import legacy_writer, mirror


class FakeCursor:
    """Curseur minimal mémorisant les requêtes et rejouant des résultats fournis."""

    def __init__(self, results=None):
        self.calls: list[tuple[str, list]] = []
        self._results = list(results or [])

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), list(params or [])))

    def fetchone(self):
        return self._results.pop(0) if self._results else None

    def fetchall(self):
        return self._results.pop(0) if self._results else []

    def sql_matching(self, needle: str) -> list[tuple[str, list]]:
        return [call for call in self.calls if needle in call[0]]


@contextmanager
def fake_legacy(results=None):
    """Active l'écriture miroir sur une connexion « legacy » bouchonnée."""
    cursor = FakeCursor(results)

    @contextmanager
    def _cursor():
        yield cursor

    connections = mock.MagicMock()
    connections.databases = {"default": {}, "legacy": {}}
    connections.__getitem__.return_value.cursor = _cursor

    with override_settings(LEGACY_WRITE_ENABLED=True):
        with mock.patch.object(legacy_writer, "connections", connections):
            yield cursor


class HashPasswordTests(SimpleTestCase):
    def test_bcrypt_format_matches_usershub(self):
        """pypnusershub lit un $2b$ de coût 12 : c'est ce que gensalt() produit."""
        pass_plus, pass_md5 = legacy_writer.hash_password("secret-123")
        self.assertTrue(pass_plus.startswith("$2b$12$"), pass_plus[:10])
        self.assertIsNone(pass_md5)

    @override_settings(LEGACY_WRITE_PASS_MD5=True)
    def test_md5_only_when_enabled(self):
        _pass_plus, pass_md5 = legacy_writer.hash_password("secret-123")
        self.assertEqual(pass_md5, hashlib.md5(b"secret-123").hexdigest())


class DisabledByDefaultTests(SimpleTestCase):
    def test_writer_disabled_in_tests(self):
        """settings_test coupe l'écriture : la suite ne doit joindre aucune base."""
        self.assertFalse(legacy_writer.is_enabled())

    def test_write_refused_when_disabled(self):
        with self.assertRaises(legacy_writer.LegacyWriteError):
            legacy_writer.deactivate_role(1)

    def test_mirror_operations_are_noops(self):
        """Les appels miroir des vues ne doivent rien tenter quand c'est désactivé."""
        kc = mock.MagicMock()
        mirror.legacy_join_reserve(kc, "sub-1", "RNN41")
        mirror.legacy_leave_reserve(kc, "sub-1", "RNN41")
        mirror.legacy_set_referent(kc, "sub-1", "RNN41", True)
        mirror.update_legacy_profile(kc, "sub-1", email="a@b.c")
        self.assertEqual(kc.mock_calls, [])


class CreateRoleSqlTests(TestCase):
    def test_insert_columns_and_values(self):
        with fake_legacy(results=[(4242,)]) as cursor:
            id_role = legacy_writer.create_role(
                identifiant="jdupont",
                nom_role="Dupont",
                prenom_role="Jean",
                email="jean@example.org",
                remarques="Chargé de mission",
                id_organisme=12,
                password="secret-123",
                champs_addi={"reserves": [{"id": "RNN41", "name": "Grand Lieu"}]},
            )

        self.assertEqual(id_role, 4242)
        sql, params = cursor.calls[0]
        self.assertIn("INSERT INTO utilisateurs.t_roles", sql)
        self.assertIn("RETURNING id_role", sql)
        # Les colonnes à valeur par défaut ou gérées par trigger ne sont pas écrites.
        for forbidden in ("id_role,", "uuid_role", "active", "groupe", "date_insert", "date_update"):
            self.assertNotIn(forbidden, sql.split("VALUES")[0])
        self.assertEqual(params[0], "jdupont")
        self.assertEqual(params[5], 12)
        self.assertTrue(params[6].startswith("$2b$12$"))
        self.assertIsNone(params[7])  # pass md5 désactivé

    def test_grant_application_writes_profil_and_group(self):
        # Le (True,) répond au contrôle « ce rôle est-il bien un groupe ? ».
        with fake_legacy(results=[(True,)]) as cursor:
            legacy_writer.grant_application(
                7, id_application=14, id_profil=1, group_id_role=36
            )
        profil = cursor.sql_matching("cor_role_app_profil")
        groupe = cursor.sql_matching("INSERT INTO utilisateurs.cor_roles")
        self.assertEqual(len(profil), 1)
        self.assertEqual(profil[0][1], [7, 14, 1])
        self.assertEqual(len(groupe), 1)
        self.assertEqual(groupe[0][1], [36, 7])

    def test_add_to_groups_skips_unknown_and_non_group_roles(self):
        """Un identifiant douteux ne doit pas faire échouer la création entière."""
        with fake_legacy(results=[None, (False,), (True,)]) as cursor:
            ajoutes = legacy_writer.add_to_groups(7, [404, 12, 69])
        self.assertEqual(ajoutes, [69])
        inserts = cursor.sql_matching("INSERT INTO utilisateurs.cor_roles")
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][1], [69, 7])

    def test_grant_application_skips_group_when_not_declared(self):
        with fake_legacy() as cursor:
            legacy_writer.grant_application(7, id_application=14)
        self.assertEqual(cursor.sql_matching("cor_roles"), [])

    def test_update_profile_ignores_unset_columns(self):
        with fake_legacy() as cursor:
            legacy_writer.update_role_profile(7, email="neuf@example.org", nom_role=None)
        sql, params = cursor.calls[0]
        self.assertIn("SET email = %s", sql)
        self.assertNotIn("nom_role", sql)
        self.assertEqual(params, ["neuf@example.org", 7])

    def test_update_profile_without_values_does_nothing(self):
        with fake_legacy() as cursor:
            legacy_writer.update_role_profile(7)
        self.assertEqual(cursor.calls, [])


class SyncReservesTests(TestCase):
    def setUp(self):
        Reserve.objects.create(area_code="RNN41", area_name="Grand Lieu")
        Reserve.objects.create(area_code="RNN99", area_name="Camargue")

    def test_reconciliation_adds_removes_and_updates(self):
        # État courant : RNN41 (non référent) et RNN77 (référent).
        results = [
            [("RNN41", False), ("RNN77", True)],  # SELECT des liens existants
            None,  # SELECT champs_addi
        ]
        with fake_legacy(results=results) as cursor:
            legacy_writer.sync_reserves(7, {"RNN41", "RNN99"}, {"RNN41"})

        self.assertEqual(len(cursor.sql_matching("DELETE FROM complement_rnf.cor_role_rn")), 1)
        self.assertIn("RNN77", cursor.sql_matching("DELETE FROM complement_rnf.cor_role_rn")[0][1])

        inserts = cursor.sql_matching("INSERT INTO complement_rnf.cor_role_rn")
        self.assertEqual(len(inserts), 1)
        # rn_id reçoit le code textuel, pas un identifiant numérique.
        self.assertEqual(inserts[0][1][:2], [7, "RNN99"])

        updates = cursor.sql_matching("UPDATE complement_rnf.cor_role_rn SET referent")
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1], [True, 7, "RNN41"])

    def test_champs_addi_keeps_other_keys(self):
        results = [
            [],  # aucun lien existant
            ('{"ancrage": true, "precisions_ancrage": "texte"}',),  # champs_addi courant
        ]
        with fake_legacy(results=results) as cursor:
            legacy_writer.sync_reserves(7, {"RNN41"}, set())

        import json

        payload = json.loads(cursor.sql_matching("SET champs_addi")[0][1][0])
        self.assertTrue(payload["ancrage"])
        self.assertEqual(payload["precisions_ancrage"], "texte")
        self.assertEqual(payload["reserves"], [{"id": "RNN41", "name": "Grand Lieu"}])

    def test_build_reserves_payload_uses_reserve_names(self):
        reserves, referents = legacy_writer.build_reserves_payload(
            ["RNN99", "RNN41"], ["RNN41", "HORS-LISTE"]
        )
        self.assertEqual(
            reserves,
            [{"id": "RNN41", "name": "Grand Lieu"}, {"id": "RNN99", "name": "Camargue"}],
        )
        # Un référent sur une réserve non demandée est écarté.
        self.assertEqual(referents, [{"id": "RNN41", "name": "Grand Lieu"}])


# TestCase et non SimpleTestCase : atomic_mirror ouvre une transaction, ce que
# SimpleTestCase interdit.
class ImportNeReecritPasTests(TestCase):
    """L'import de l'existant lit la base historique : il ne doit rien y réécrire.

    Sans cela, peupler Keycloak depuis UsersHub déclencherait, pour chaque compte,
    la diffusion vers les bases GeoNature satellites et le site internet.
    """

    @override_settings(KEYCLOAK_SYNC_ENABLED=False)
    def test_provision_access_sans_miroir(self):
        from inscriptions.services import provisioning

        app = Application.objects.create(slug="ancrage", nom="Ancrage", legacy_group_id_role=64)
        with mock.patch.object(provisioning.mirror, "legacy_grant_application") as ecriture:
            provisioning.provision_application_access(
                mock.MagicMock(), "sub-1", app, mirror_legacy=False
            )
        ecriture.assert_not_called()

    @override_settings(KEYCLOAK_SYNC_ENABLED=False)
    def test_provision_access_avec_miroir_par_defaut(self):
        from inscriptions.services import provisioning

        app = Application.objects.create(slug="ancrage", nom="Ancrage", legacy_group_id_role=64)
        with mock.patch.object(provisioning.mirror, "legacy_grant_application") as ecriture:
            provisioning.provision_application_access(mock.MagicMock(), "sub-1", app)
        ecriture.assert_called_once()


class CompensationTests(TestCase):
    def test_undo_runs_in_reverse_on_failure(self):
        done = []
        with self.assertRaises(RuntimeError):
            with mirror.atomic_mirror() as undo:
                undo.push(lambda: done.append("premier"))
                undo.push(lambda: done.append("second"))
                raise RuntimeError("échec simulé")
        self.assertEqual(done, ["second", "premier"])

    def test_undo_not_run_on_success(self):
        done = []
        with mirror.atomic_mirror() as undo:
            undo.push(lambda: done.append("jamais"))
        self.assertEqual(done, [])

    def test_failing_undo_does_not_mask_original_error(self):
        def boom():
            raise ValueError("compensation cassée")

        with self.assertRaises(RuntimeError):
            with mirror.atomic_mirror() as undo:
                undo.push(boom)
                raise RuntimeError("erreur d'origine")


class ReferentCodesTests(TestCase):
    def test_referent_codes_filtered_on_requested_reserves(self):
        org = Organisme.objects.create(id_organisme=1, nom_organisme="RNF")
        registration = RegistrationRequest(
            username="jdupont",
            email="jean@example.org",
            first_name="Jean",
            last_name="Dupont",
            organisme=org,
            reserve_codes=["RNN41", "RNN99"],
            champs_addi={
                "reserves_referent": [
                    {"id": "RNN41", "name": "Grand Lieu"},
                    {"id": "RNN00", "name": "Non demandée"},
                ]
            },
        )
        self.assertEqual(mirror.referent_codes_from_registration(registration), ["RNN41"])

    def test_referent_codes_tolerates_empty_string(self):
        """Le formulaire envoie '' et non [] quand rien n'est sélectionné."""
        registration = RegistrationRequest(
            username="x", email="x@y.z", first_name="X", last_name="Y",
            reserve_codes=[], champs_addi={"reserves_referent": ""},
        )
        self.assertEqual(mirror.referent_codes_from_registration(registration), [])


class ApplicationMappingTests(TestCase):
    def test_application_without_mapping_writes_nothing(self):
        app = Application.objects.create(slug="sans-correspondance", nom="Sans correspondance")
        self.assertIsNone(mirror._application_mapping(app))

    def test_group_alone_is_a_valid_mapping(self):
        """L'accès est porté par le groupe ; cor_role_app_profil n'est plus alimenté."""
        app = Application.objects.create(
            slug="ancrage", nom="Ancrage", legacy_group_id_role=64
        )
        self.assertEqual(mirror._application_mapping(app), (None, 1, 64))

    def test_grant_application_without_app_id_writes_only_the_group(self):
        with fake_legacy(results=[(True,)]) as cursor:
            legacy_writer.grant_application(7, group_id_role=64)
        self.assertEqual(cursor.sql_matching("cor_role_app_profil"), [])
        self.assertEqual(cursor.sql_matching("INSERT INTO utilisateurs.cor_roles")[0][1], [64, 7])

    def test_application_mapping_defaults_to_profil_lecteur(self):
        app = Application.objects.create(
            slug="geonature-saisie", nom="GeoNature Saisie", legacy_id_application=14
        )
        self.assertEqual(mirror._application_mapping(app), (14, 1, None))
