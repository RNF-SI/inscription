from unittest.mock import patch

from django.test import TestCase

from inscriptions.models import ApplicationAdmin
from inscriptions.services import application_admins as svc
from inscriptions.tests.helpers import make_application, make_app_admin, make_profile


class ApplicationAdminsServiceTests(TestCase):
    def test_list_application_admins(self):
        app = make_application()
        profile = make_profile(email="admin@test.local")
        make_app_admin(profile, app)
        admins = svc.list_application_admins(app)
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0]["email"], "admin@test.local")

    def test_replace_application_admins(self):
        app = make_application()
        first = make_profile(sub="admin-1", email="first@test.local")
        second = make_profile(sub="admin-2", email="second@test.local")
        make_app_admin(first, app)
        admins = svc.replace_application_admins(app, [second.keycloak_sub])
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0]["email"], "second@test.local")
        self.assertFalse(ApplicationAdmin.objects.filter(user=first, application=app).exists())

    @patch("inscriptions.services.application_admins.KeycloakAdminClient")
    def test_add_application_admin_creates_profile_from_keycloak(self, kc_cls):
        app = make_application()
        kc = kc_cls.return_value
        kc.get_user.return_value = {
            "id": "kc-sub-123",
            "email": "keycloak@test.local",
            "username": "kcuser",
            "firstName": "Key",
            "lastName": "Cloak",
        }
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            admin = svc.add_application_admin(app, keycloak_sub="kc-sub-123")
        self.assertEqual(admin["email"], "keycloak@test.local")
        self.assertTrue(ApplicationAdmin.objects.filter(application=app, user__keycloak_sub="kc-sub-123").exists())

    def test_add_application_admin_unknown_user_raises(self):
        app = make_application()
        with self.assertRaises(ValueError):
            svc.add_application_admin(app, email="missing@test.local")
