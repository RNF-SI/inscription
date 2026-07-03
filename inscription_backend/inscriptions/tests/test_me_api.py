from unittest.mock import patch

from rest_framework import status

from inscriptions.models import Notification
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    auth_client,
    make_app_admin,
    make_application,
    make_profile,
    make_reserve,
)


class MeApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.regular_user = make_profile(sub="user-sub", email="user@test.local")

    def test_me_requires_auth(self):
        response = self.client.get("/api/me/")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_me_returns_profile(self):
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["profile"]["email"], self.regular_user.email)
        self.assertIn("applications", data)

    def test_me_flags_reserve_referent_from_token_groups(self):
        from inscriptions.tests.helpers import make_reserve

        reserve = make_reserve(area_code="RNN42", area_name="Réserve test")
        auth_client(
            self.client,
            self.regular_user,
            groups=[f"reserves/{reserve.area_code}/referent", f"reserves/{reserve.area_code}"],
        )
        response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["is_reserve_referent"])
        self.assertTrue(any(r["area_code"] == reserve.area_code and r["referent"] for r in data["reserves"]))

    def test_me_flags_reserve_referent_from_keycloak_when_token_has_no_groups(self):
        from inscriptions.tests.helpers import make_reserve

        reserve = make_reserve(area_code="RNN43", area_name="Réserve KC")
        auth_client(self.client, self.regular_user, groups=[])
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            with patch("inscriptions.roles.KeycloakAdminClient") as kc_cls:
                kc = kc_cls.return_value
                kc.get_user_groups.return_value = [
                    {"path": f"/reserves/{reserve.area_code}/referent"},
                    {"path": f"/reserves/{reserve.area_code}"},
                ]
                response = self.client.get("/api/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["is_reserve_referent"])

    def test_me_patch_accepts_fonction(self):
        auth_client(self.client, self.regular_user)
        with patch("inscriptions.views.KeycloakAdminClient.update_user_profile"):
            response = self.client.patch("/api/me/", {"fonction": "Référent"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_notifications_list(self):
        Notification.objects.create(
            user_sub=self.regular_user.keycloak_sub,
            title="Test",
            body="Corps",
            admin_tab="requests",
        )
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/notifications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 1)
        self.assertEqual(payload[0]["admin_tab"], "requests")

    def test_mark_notification_read(self):
        notif = Notification.objects.create(user_sub=self.regular_user.keycloak_sub, title="Test", body="Corps")
        auth_client(self.client, self.regular_user)
        response = self.client.patch(f"/api/notifications/{notif.pk}/mark-read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notif.refresh_from_db()
        self.assertTrue(notif.read)

    def test_delete_read_notifications(self):
        read_notif = Notification.objects.create(
            user_sub=self.regular_user.keycloak_sub, title="Lue", body="Corps", read=True
        )
        unread_notif = Notification.objects.create(
            user_sub=self.regular_user.keycloak_sub, title="Non lue", body="Corps", read=False
        )
        other_read = Notification.objects.create(user_sub="other-sub", title="Autre", body="Corps", read=True)
        auth_client(self.client, self.regular_user)
        response = self.client.post("/api/notifications/delete-read/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(Notification.objects.filter(pk=read_notif.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=unread_notif.pk).exists())
        self.assertTrue(Notification.objects.filter(pk=other_read.pk).exists())


class ReferentRemovalRequestApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.referent = make_profile(sub="referent-sub", email="referent@test.local")
        self.reserve = make_reserve(area_code="RNN41", area_name="Réserve 41")

    @patch("inscriptions.services.reserve_notifications.mail_svc.send_reserve_member_removal_superadmin_mail")
    @patch("inscriptions.services.reserve_notifications.list_super_admin_subs")
    def test_referent_removal_request_uses_keycloak_groups_fallback(self, list_super, send_mail):
        list_super.return_value = ["super-sub"]
        auth_client(self.client, self.referent, groups=[])
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
                kc = kc_cls.return_value
                kc.get_user_groups.return_value = [
                    {"path": f"/reserves/{self.reserve.area_code}/referent"},
                    {"path": f"/reserves/{self.reserve.area_code}"},
                ]
                response = self.client.post(
                    f"/api/me/referent/reserves/{self.reserve.area_code}/removal-requests/",
                    {
                        "target_sub": "target-sub",
                        "target_email": "target@test.local",
                        "target_first_name": "Cible",
                        "target_last_name": "Test",
                        "reason": "Ne fait plus partie de la réserve",
                    },
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            Notification.objects.filter(user_sub="super-sub", title__icontains="retrait").exists()
        )
        send_mail.assert_called_once()


class AppAdminApiTests(BaseApiTestCase):
    def test_pending_items_for_app_admin(self):
        app = make_application(slug="waterwise")
        admin_profile = make_profile(email="admin-app@test.local")
        make_app_admin(admin_profile, app)
        auth_client(self.client, admin_profile)

        response = self.client.get("/api/admin/pending-items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.json(), list)

    def test_my_validation_applications(self):
        app = make_application(slug="waterwise")
        admin_profile = make_profile(email="admin-app@test.local")
        make_app_admin(admin_profile, app)
        auth_client(self.client, admin_profile)

        response = self.client.get("/api/admin/my-validation-applications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {row["slug"] for row in response.json()}
        self.assertIn(app.slug, slugs)
