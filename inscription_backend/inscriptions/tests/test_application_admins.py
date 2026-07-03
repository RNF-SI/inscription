from unittest.mock import patch

from django.test import TestCase

from inscriptions.services import application_admins as svc
from inscriptions.tests.helpers import make_application, make_profile


class ApplicationAdminsServiceTests(TestCase):
    @patch("inscriptions.roles.list_application_admin_subs")
    @patch("inscriptions.roles.fetch_user_info")
    def test_list_application_admins(self, fetch_user_info, list_subs):
        app = make_application()
        list_subs.return_value = ["admin-sub"]
        from inscriptions.user_identity import UserInfo

        fetch_user_info.return_value = UserInfo(
            sub="admin-sub",
            email="admin@test.local",
            username="admin",
            first_name="Admin",
            last_name="User",
        )
        admins = svc.list_application_admins(app)
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0]["email"], "admin@test.local")

    @patch("inscriptions.roles.KeycloakAdminClient")
    @patch("inscriptions.roles._ensure_user_exists")
    @patch("inscriptions.roles.list_application_admin_subs")
    @patch("inscriptions.roles.list_application_admins")
    def test_replace_application_admins(self, list_admins, list_subs, ensure_user, kc_cls):
        app = make_application()
        list_subs.side_effect = [["admin-1"], ["admin-2"]]
        list_admins.return_value = [{"keycloak_sub": "admin-2", "email": "second@test.local"}]
        kc = kc_cls.return_value
        kc.ensure_application_admin_group.return_value = "group-id"
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            admins = svc.replace_application_admins(app, ["admin-2"])
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0]["email"], "second@test.local")

    @patch("inscriptions.roles.KeycloakAdminClient")
    @patch("inscriptions.roles.resolve_user_sub")
    @patch("inscriptions.roles._ensure_user_exists")
    @patch("inscriptions.roles.list_application_admin_subs")
    def test_add_application_admin_from_keycloak(self, list_subs, ensure_user, resolve_sub, kc_cls):
        app = make_application()
        from inscriptions.user_identity import UserInfo

        resolve_sub.return_value = "kc-sub-123"
        ensure_user.return_value = UserInfo(
            sub="kc-sub-123",
            email="keycloak@test.local",
            username="kcuser",
            first_name="Key",
            last_name="Cloak",
        )
        list_subs.return_value = []
        kc = kc_cls.return_value
        kc.ensure_application_admin_group.return_value = "group-id"
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            admin = svc.add_application_admin(app, keycloak_sub="kc-sub-123")
        self.assertEqual(admin["email"], "keycloak@test.local")
        kc.user_join_group.assert_called_once()

    def test_add_application_admin_unknown_user_raises(self):
        app = make_application()
        with self.assertRaises(ValueError):
            svc.add_application_admin(app, email="missing@test.local")
