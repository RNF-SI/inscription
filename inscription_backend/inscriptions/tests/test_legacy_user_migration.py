from unittest import mock

from django.test import SimpleTestCase

from inscriptions.keycloak_client import KeycloakAdminError
from inscriptions.models import Application
from inscriptions.services.legacy_user_migration import (
    LEGACY_ADMIN_PROFIL_ID,
    LegacyApplicationRow,
    LegacyUserRow,
    _normalize_email,
    build_keycloak_password_credential,
    build_legacy_application_slug_map,
    find_existing_keycloak_user,
    link_existing_keycloak_user,
)


def _compte(username="jdupont", email="jean@example.org", id_role=7):
    return LegacyUserRow(
        id_role=id_role, username=username, email=email,
        first_name="Jean", last_name="Dupont", fonction="", id_organisme=None,
    )


class RattachementCompteExistantTests(SimpleTestCase):
    """Les membres de l'équipe sont fédérés depuis l'annuaire : leur compte existe
    avant l'import, souvent sous un autre identifiant. Il faut leur donner les droits
    sans toucher à leur identifiant ni à leur mot de passe."""

    def test_rapprochement_par_identifiant_dabord(self):
        kc = mock.MagicMock()
        kc.find_user_by_username.return_value = "sub-1"
        self.assertEqual(find_existing_keycloak_user(kc, _compte()), ("sub-1", "identifiant"))
        kc.find_user_by_email.assert_not_called()

    def test_rapprochement_par_email_si_identifiant_different(self):
        kc = mock.MagicMock()
        kc.find_user_by_username.return_value = None
        kc.find_user_by_email.return_value = "sub-ldap"
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte(username="ancien.login")),
            ("sub-ldap", "e-mail"),
        )

    def test_email_de_substitution_jamais_rapproche(self):
        """Les adresses @legacy-migration.local sont fabriquées : elles ne désignent
        personne, les rapprocher mélangerait des comptes sans rapport."""
        kc = mock.MagicMock()
        kc.find_user_by_username.return_value = None
        compte = _compte(email="jdupont@legacy-migration.local")
        self.assertIsNone(find_existing_keycloak_user(kc, compte))
        kc.find_user_by_email.assert_not_called()

    def test_aucun_rapprochement(self):
        kc = mock.MagicMock()
        kc.find_user_by_username.return_value = None
        kc.find_user_by_email.return_value = None
        self.assertIsNone(find_existing_keycloak_user(kc, _compte()))

    def test_rattachement_ne_touche_ni_identifiant_ni_mot_de_passe(self):
        kc = mock.MagicMock()
        with mock.patch(
            "inscriptions.services.legacy_user_migration.assign_legacy_groups"
        ) as droits:
            link_existing_keycloak_user(kc, _compte(), "sub-ldap")
        kc.create_user.assert_not_called()
        kc.update_user_profile.assert_not_called()
        droits.assert_called_once()

    def test_attribut_non_posable_nempeche_pas_les_droits(self):
        """Un compte fédéré en lecture seule refuse l'écriture d'attributs ; les
        droits, eux, vivent côté Keycloak et doivent être attribués quand même."""
        kc = mock.MagicMock()
        kc.set_user_attribute.side_effect = KeycloakAdminError("update_user_failed:400")
        with mock.patch(
            "inscriptions.services.legacy_user_migration.assign_legacy_groups"
        ) as droits:
            link_existing_keycloak_user(kc, _compte(), "sub-ldap")
        droits.assert_called_once()


class LegacyUserMigrationMappingTests(SimpleTestCase):
    def test_build_legacy_application_slug_map_fuzzy(self):
        """Le rapprochement par nom suffit : plus aucune correspondance codée en dur."""
        legacy_apps = [
            LegacyApplicationRow(4, "GNS", "GeoNature saisie"),
            LegacyApplicationRow(99, "waterwise-db", "Waterwise DB management"),
        ]
        django_apps = [
            Application(slug="geonature-saisie", nom="GeoNature Saisie"),
            Application(slug="waterwise", nom="Waterwise DB management"),
        ]
        mapping = build_legacy_application_slug_map(legacy_apps, django_apps)
        self.assertEqual(mapping[4], "geonature-saisie")
        self.assertEqual(mapping[99], "waterwise")

    def test_communaute_rnf_nest_pas_rapprochee_de_geonature(self):
        """id 14 = Communauté RNF en production : il ne doit rien accorder."""
        legacy_apps = [LegacyApplicationRow(14, "COMM_RNF", "Communauté RNF")]
        django_apps = [Application(slug="geonature-saisie", nom="GeoNature Saisie")]
        mapping = build_legacy_application_slug_map(legacy_apps, django_apps)
        self.assertNotIn(14, mapping)

    def test_normalize_email_fallback(self):
        self.assertEqual(_normalize_email("", "jean.dupont"), "jean.dupont@legacy-migration.local")
        self.assertEqual(_normalize_email("a@b.com", "jean"), "a@b.com")

    def test_legacy_user_row_defaults(self):
        user = LegacyUserRow(
            id_role=1,
            username="agent",
            email="agent@test.local",
            first_name="Jean",
            last_name="Dupont",
            fonction="Référent",
            id_organisme=12,
            password_bcrypt="$2b$12$abcdefghijklmnopqrstuv",
            app_member_slugs={"socle"},
            app_admin_slugs={"waterwise"},
            is_super_admin=True,
        )
        self.assertEqual(user.app_member_slugs, {"socle"})
        self.assertEqual(user.app_admin_slugs, {"waterwise"})
        self.assertTrue(user.is_super_admin)
        self.assertEqual(LEGACY_ADMIN_PROFIL_ID, 6)

    def test_build_keycloak_password_credential_bcrypt(self):
        cred = build_keycloak_password_credential(
            password_bcrypt="$2b$12$abcdefghijklmnopqrstuv",
            password_md5=None,
        )
        self.assertIsNotNone(cred)
        self.assertEqual(cred["type"], "password")
        self.assertIn("bcrypt", cred["credentialData"])

    def test_build_keycloak_password_credential_md5(self):
        cred = build_keycloak_password_credential(
            password_bcrypt=None,
            password_md5="5f4dcc3b5aa765d61d8327deb882cf99",
        )
        self.assertIsNotNone(cred)
        self.assertIn("md5", cred["credentialData"])
