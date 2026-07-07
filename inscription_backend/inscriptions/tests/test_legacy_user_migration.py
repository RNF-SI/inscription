from django.test import SimpleTestCase

from inscriptions.models import Application
from inscriptions.services.legacy_user_migration import (
    LEGACY_ADMIN_PROFIL_ID,
    LegacyApplicationRow,
    LegacyUserRow,
    _normalize_email,
    build_keycloak_password_credential,
    build_legacy_application_slug_map,
)


class LegacyUserMigrationMappingTests(SimpleTestCase):
    def test_build_legacy_application_slug_map_manual_and_fuzzy(self):
        legacy_apps = [
            LegacyApplicationRow(14, "geonature", "Application GeoNature"),
            LegacyApplicationRow(99, "waterwise-db", "Waterwise DB management"),
        ]
        django_apps = [
            Application(slug="geonature-saisie", nom="GeoNature Saisie"),
            Application(slug="waterwise", nom="Waterwise DB management"),
        ]
        mapping = build_legacy_application_slug_map(legacy_apps, django_apps)
        self.assertEqual(mapping[14], "geonature-saisie")
        self.assertEqual(mapping[99], "waterwise")

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
