from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError


class KeycloakGroupMembersCountTests(SimpleTestCase):
    def test_count_group_members_single_page(self):
        kc = KeycloakAdminClient()
        with patch.object(kc, "_get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [{"id": "1"}, {"id": "2"}])
            self.assertEqual(kc.count_group_members("gid"), 2)
            mock_get.assert_called_once_with("/groups/gid/members?first=0&max=200")

    def test_count_group_members_multiple_pages(self):
        kc = KeycloakAdminClient()
        page1 = [{"id": str(i)} for i in range(200)]
        page2 = [{"id": str(i)} for i in range(200, 250)]

        def side_effect(url):
            if "first=0" in url:
                return MagicMock(status_code=200, json=lambda: page1)
            if "first=200" in url:
                return MagicMock(status_code=200, json=lambda: page2)
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(kc, "_get", side_effect=side_effect):
            self.assertEqual(kc.count_group_members("gid"), 250)

    def test_count_group_members_raises_on_error(self):
        kc = KeycloakAdminClient()
        with patch.object(kc, "_get") as mock_get:
            mock_get.return_value = MagicMock(status_code=500, json=lambda: {})
            with self.assertRaises(KeycloakAdminError):
                kc.count_group_members("gid")

    def test_list_all_group_members_multiple_pages(self):
        kc = KeycloakAdminClient()
        page1 = [{"id": str(i)} for i in range(200)]
        page2 = [{"id": str(i)} for i in range(200, 205)]

        def side_effect(url):
            if "first=0" in url:
                return MagicMock(status_code=200, json=lambda: page1)
            if "first=200" in url:
                return MagicMock(status_code=200, json=lambda: page2)
            raise AssertionError(f"unexpected url: {url}")

        with patch.object(kc, "_get", side_effect=side_effect):
            members = kc.list_all_group_members("gid")
        self.assertEqual(len(members), 205)


class KeycloakNetworkErrorTests(SimpleTestCase):
    """Une panne réseau doit devenir un KeycloakAdminError, sinon les appelants qui
    dégradent gracieusement (`except KeycloakAdminError`) laissent remonter une 500."""

    def test_connection_error_is_wrapped(self):
        import requests

        kc = KeycloakAdminClient()
        with patch.object(kc, "get_access_token", return_value="tok"):
            with patch("inscriptions.keycloak_client.requests.get") as get:
                get.side_effect = requests.ConnectionError("injoignable")
                with self.assertRaises(KeycloakAdminError) as ctx:
                    kc._get("/users/abc")
        self.assertEqual(ctx.exception.code, "keycloak_unreachable")

    def test_timeout_on_token_endpoint_is_wrapped(self):
        import requests

        kc = KeycloakAdminClient()
        with patch("inscriptions.keycloak_client.requests.post") as post:
            post.side_effect = requests.Timeout("trop long")
            with self.assertRaises(KeycloakAdminError):
                kc.get_access_token()

    def test_fetch_user_info_degrades_to_none_when_keycloak_is_down(self):
        import requests

        from inscriptions.user_identity import fetch_user_info

        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            with patch("inscriptions.keycloak_client.requests.post") as post:
                post.side_effect = requests.ConnectionError("injoignable")
                self.assertIsNone(fetch_user_info("un-sub"))
