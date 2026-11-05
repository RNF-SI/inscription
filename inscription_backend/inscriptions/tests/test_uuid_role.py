"""L'uuid_role historique comme identifiant du compte Keycloak.

Les autres applications RNF joignent leurs comptes par ``utilisateurs.t_roles``.
Donner au compte Keycloak l'``uuid_role`` de sa ligne rend le ``sub`` des jetons
directement utilisable comme clé de jointure : pas d'attribut à lire, pas de requête
supplémentaire, et la correspondance tient même si l'adresse ou l'identifiant change.

``POST /users`` ignore le champ ``id`` qu'on lui passe — vérifié sur le serveur en
26.3 — et l'``id`` d'un compte existant n'est pas modifiable. Seul le
``partialImport`` respecte l'``id`` fourni, d'où le second chemin de création testé
ici. Les comptes qui existaient déjà dans le realm, comptes d'annuaire compris, ne
peuvent pas être réidentifiés : ils portent l'``uuid_role`` en attribut.
"""

import json
from unittest import mock

from django.test import SimpleTestCase

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.services import legacy_user_migration as migration
from inscriptions.services import legacy_writer, workflows
from inscriptions.services.mirror import LEGACY_ID_ROLE_ATTRIBUTE, UUID_ROLE_ATTRIBUTE
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    legacy_user_row,
    make_application,
    make_profile,
    make_registration,
)

UUID = "3f2b9c10-5d4e-4a7b-8c1d-9e0f1a2b3c4d"


def reponse(status, payload=None):
    r = mock.MagicMock()
    r.status_code = status
    r.text = json.dumps(payload or {})
    r.json.return_value = payload or {}
    r.headers = {}
    return r


def rapport_ajout(user_id):
    return {"added": 1, "overwritten": 0, "skipped": 0, "results": [{"id": user_id}]}


class CheminDeCreationTests(SimpleTestCase):
    """Sans ``user_id``, rien ne change ; avec, c'est le partialImport qui crée."""

    def setUp(self):
        self.kc = KeycloakAdminClient()

    def _creer(self, reponses, **kwargs):
        with mock.patch.object(KeycloakAdminClient, "_post", side_effect=reponses) as post:
            uid = self.kc.create_user(
                username="jean.dupont",
                email="jean@example.org",
                first_name="Jean",
                last_name="Dupont",
                password="motdepasse",
                **kwargs,
            )
        return uid, post

    def test_sans_id_impose_la_route_habituelle(self):
        r = reponse(201)
        r.headers = {"Location": "https://kc/admin/realms/x/users/aaaa-bbbb"}
        uid, post = self._creer([r])
        self.assertEqual(uid, "aaaa-bbbb")
        self.assertEqual(post.call_args.args[0], "/users")

    def test_id_impose_passe_par_partialimport(self):
        uid, post = self._creer([reponse(200, rapport_ajout(UUID))], user_id=UUID)
        self.assertEqual(uid, UUID)
        chemin = post.call_args.args[0]
        corps = post.call_args.kwargs["json"]
        self.assertEqual(chemin, "/partialImport")
        self.assertEqual(corps["users"][0]["id"], UUID)
        self.assertEqual(corps["users"][0]["username"], "jean.dupont")

    def test_ifresourceexists_reste_fail(self):
        """OVERWRITE supprimerait et recréerait le compte, en perdant tout ce que la
        charge utile ne redonne pas — mot de passe et groupes compris."""
        _, post = self._creer([reponse(200, rapport_ajout(UUID))], user_id=UUID)
        self.assertEqual(post.call_args.kwargs["json"]["ifResourceExists"], "FAIL")

    def test_le_mot_de_passe_et_les_attributs_suivent(self):
        _, post = self._creer(
            [reponse(200, rapport_ajout(UUID))],
            user_id=UUID,
            function_value="Conservateur",
            extra_attributes={LEGACY_ID_ROLE_ATTRIBUTE: ["42"]},
        )
        u = post.call_args.kwargs["json"]["users"][0]
        self.assertEqual(u["credentials"][0]["value"], "motdepasse")
        self.assertEqual(u["attributes"][LEGACY_ID_ROLE_ATTRIBUTE], ["42"])
        self.assertEqual(u["attributes"]["function"], ["Conservateur"])


class EchecsDuPartialImportTests(SimpleTestCase):
    """Le rapport du partialImport doit être lu : un 200 ne vaut pas succès."""

    def setUp(self):
        self.kc = KeycloakAdminClient()

    def _attendre(self, reponse_kc):
        with mock.patch.object(KeycloakAdminClient, "_post", return_value=reponse_kc):
            with self.assertRaises(KeycloakAdminError) as ctx:
                self.kc.create_user(
                    username="jean.dupont",
                    email="jean@example.org",
                    first_name="Jean",
                    last_name="Dupont",
                    password="motdepasse",
                    user_id=UUID,
                )
        return ctx.exception

    def test_conflit_ressort_en_409(self):
        """C'est ce que la boucle de suffixe de l'import rattrape."""
        exc = self._attendre(reponse(409, {"errorMessage": "User with user name … exists."}))
        self.assertTrue(str(exc.code).endswith(":409"))

    def test_200_sans_creation_est_un_echec(self):
        exc = self._attendre(reponse(200, {"added": 0, "skipped": 1, "results": []}))
        self.assertFalse(str(exc.code).endswith(":409"))

    def test_id_different_de_celui_demande_est_refuse(self):
        """Un compte mal identifié ruinerait la jointure : mieux vaut échouer."""
        exc = self._attendre(reponse(200, rapport_ajout("un-autre-id")))
        self.assertEqual(exc.code, "create_user_id_mismatch")


class ImportDesComptesTests(SimpleTestCase):
    """L'import impose l'uuid_role de la ligne au compte qu'il crée."""

    def test_uuid_role_transmis_a_la_creation(self):
        kc = mock.MagicMock()
        kc.create_user.return_value = UUID
        user = legacy_user_row("jean.dupont", uuid_role=UUID)
        uid, identifiant = migration._create_with_available_username(
            kc, user, password=None, temporary_password=False, credential={"type": "password"}
        )
        self.assertEqual(uid, UUID)
        self.assertEqual(identifiant, "jean.dupont")
        self.assertEqual(kc.create_user.call_args.kwargs["user_id"], UUID)

    def test_sans_uuid_role_keycloak_garde_la_main(self):
        """Repli : une ligne sans uuid (jeu de test, base tronquée) doit rester
        importable, avec l'id que Keycloak génère."""
        kc = mock.MagicMock()
        kc.create_user.return_value = "id-genere"
        user = legacy_user_row("jean.dupont")
        uid, _ = migration._create_with_available_username(
            kc, user, password=None, temporary_password=False, credential={"type": "password"}
        )
        self.assertEqual(uid, "id-genere")
        self.assertIsNone(kc.create_user.call_args.kwargs["user_id"])

    def test_suffixe_sur_conflit_conserve_luuid(self):
        kc = mock.MagicMock()
        kc.create_user.side_effect = [
            KeycloakAdminError("create_user_failed:409"),
            UUID,
        ]
        user = legacy_user_row("jean.dupont", uuid_role=UUID)
        uid, identifiant = migration._create_with_available_username(
            kc, user, password=None, temporary_password=False, credential={"type": "password"}
        )
        self.assertEqual((uid, identifiant), (UUID, "jean.dupont.2"))
        for appel in kc.create_user.call_args_list:
            self.assertEqual(appel.kwargs["user_id"], UUID)


class ComptesRattachesTests(SimpleTestCase):
    """Leur id existait avant nous et Keycloak ne permet pas de le changer :
    l'uuid_role est posé en attribut pour que la jointure reste possible."""

    def test_les_deux_cles_sont_posees(self):
        kc = mock.MagicMock()
        user = legacy_user_row("zacharie.moulin", id_role=7, uuid_role=UUID)
        migration.link_existing_keycloak_user(kc, user, "id-existant")
        poses = {a.args[1]: a.args[2] for a in kc.set_user_attribute.call_args_list}
        self.assertEqual(poses, {LEGACY_ID_ROLE_ATTRIBUTE: "7", UUID_ROLE_ATTRIBUTE: UUID})

    def test_un_refus_dattribut_ne_bloque_pas_les_droits(self):
        """Un compte fédéré en lecture seule refuse les modifications ; les droits,
        eux, vivent côté Keycloak et doivent être attribués quand même."""
        kc = mock.MagicMock()
        kc.set_user_attribute.side_effect = KeycloakAdminError("update_user_failed")
        user = legacy_user_row("zacharie.moulin", uuid_role=UUID)
        with mock.patch.object(migration, "assign_legacy_groups") as droits:
            migration.link_existing_keycloak_user(kc, user, "id-existant")
        droits.assert_called_once()

    def test_sans_uuid_un_seul_attribut(self):
        kc = mock.MagicMock()
        migration.link_existing_keycloak_user(kc, legacy_user_row("x"), "id-existant")
        poses = [a.args[1] for a in kc.set_user_attribute.call_args_list]
        self.assertEqual(poses, [LEGACY_ID_ROLE_ATTRIBUTE])


class ApprobationSuperAdminTests(BaseApiTestCase):
    """À la validation d'une inscription, l'uuid_role que PostgreSQL vient de générer
    devient l'identifiant du compte Keycloak. L'écriture historique précède l'appel
    Keycloak, l'uuid est donc connu à ce moment-là."""

    def _approuver(self, role_cree):
        app = make_application(slug="waterwise")
        reg = make_registration(app=app)
        actor = make_profile(is_super_admin=True)
        kc = mock.MagicMock()
        kc.create_user.return_value = role_cree.uuid_role if role_cree else "id-genere"
        # Le realm ne connaît ni cette adresse ni cet identifiant : sans le dire, le
        # MagicMock répondrait un objet vrai et la validation refuserait un doublon.
        kc.find_user_by_email.return_value = None
        kc.find_user_by_username.return_value = None
        with self.settings(KEYCLOAK_SYNC_ENABLED=True), \
             mock.patch("inscriptions.services.workflows.KeycloakAdminClient", return_value=kc), \
             mock.patch.object(workflows.mirror, "create_legacy_role", return_value=role_cree), \
             mock.patch.object(workflows.prov, "provision_user_groups_after_super_approval"):
            workflows.super_admin_approve(reg, actor.keycloak_sub)
        return reg, kc

    def test_luuid_role_devient_lidentifiant_du_compte(self):
        reg, kc = self._approuver(legacy_writer.NouveauRole(4242, UUID))
        kwargs = kc.create_user.call_args.kwargs
        self.assertEqual(kwargs["user_id"], UUID)
        self.assertEqual(kwargs["extra_attributes"], {LEGACY_ID_ROLE_ATTRIBUTE: ["4242"]})
        reg.refresh_from_db()
        self.assertEqual(reg.keycloak_user_id, UUID)

    def test_sans_base_historique_keycloak_garde_la_main(self):
        """``LEGACY_WRITE_ENABLED=0`` : pas de ligne t_roles, donc pas d'uuid à
        imposer. L'inscription doit rester possible."""
        reg, kc = self._approuver(None)
        self.assertIsNone(kc.create_user.call_args.kwargs["user_id"])
        self.assertIsNone(kc.create_user.call_args.kwargs["extra_attributes"])
        reg.refresh_from_db()
        self.assertEqual(reg.keycloak_user_id, "id-genere")
