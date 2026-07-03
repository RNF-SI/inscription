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
