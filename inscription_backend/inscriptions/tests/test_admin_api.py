import tempfile
from unittest.mock import patch

from rest_framework import status

from inscriptions.models import Application
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    auth_client,
    make_application,
    make_profile,
    make_test_image_upload,
)


class AdminCatalogApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.regular_user = make_profile(sub="user-sub", email="user@test.local")
        self.managed_app = make_application(slug="ancrage", nom="Ancrage")
        self.auto_app = make_application(slug="socle", nom="SOCLE", requires_access_request=False)
        self.out_of_si_app = make_application(slug="naturadapt", nom="Natur'Adapt", managed_by_si=False)
        self.tmpdir = tempfile.mkdtemp()

    def test_list_requires_super_admin(self):
        auth_client(self.client, self.regular_user)
        response = self.client.get("/api/admin/catalog/applications/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_applications(self):
        auth_client(self.client, self.super_admin)
        with self.settings(KEYCLOAK_SYNC_ENABLED=True):
            with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
                kc = kc_cls.return_value
                kc.find_group_by_path.return_value = {"id": "group-ancrage"}
                kc.count_group_members.return_value = 2
                response = self.client.get("/api/admin/catalog/applications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = response.json()
        self.assertTrue(any(row["slug"] == self.managed_app.slug for row in rows))
        ancrage = next(row for row in rows if row["slug"] == self.managed_app.slug)
        self.assertEqual(ancrage["member_count"], 2)
        socle = next(row for row in rows if row["slug"] == self.auto_app.slug)
        self.assertIsNone(socle["member_count"])
        naturadapt = next(row for row in rows if row["slug"] == self.out_of_si_app.slug)
        self.assertIsNone(naturadapt["member_count"])

    def test_create_application(self):
        auth_client(self.client, self.super_admin)
        response = self.client.post(
            "/api/admin/catalog/applications/",
            {
                "slug": "new-app",
                "nom": "Nouvelle app",
                "url": "https://new.example.org",
                "managed_by_si": True,
                "requires_access_request": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Application.objects.filter(slug="new-app").exists())

    def test_patch_application(self):
        auth_client(self.client, self.super_admin)
        response = self.client.patch(
            f"/api/admin/catalog/applications/{self.managed_app.slug}/",
            {"nom": "Ancrage modifié"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.managed_app.refresh_from_db()
        self.assertEqual(self.managed_app.nom, "Ancrage modifié")

    def test_upload_image(self):
        auth_client(self.client, self.super_admin)
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            upload = make_test_image_upload()
            response = self.client.post(
                f"/api/admin/catalog/applications/{self.managed_app.slug}/image/",
                {"image": upload},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.managed_app.refresh_from_db()
            self.assertEqual(self.managed_app.image, f"{self.managed_app.slug}.png")

    def test_delete_image(self):
        auth_client(self.client, self.super_admin)
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            self.client.post(
                f"/api/admin/catalog/applications/{self.managed_app.slug}/image/",
                {"image": make_test_image_upload()},
                format="multipart",
            )
            response = self.client.delete(f"/api/admin/catalog/applications/{self.managed_app.slug}/image/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.managed_app.refresh_from_db()
            self.assertEqual(self.managed_app.image, "")


class AdminApplicationMembersApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.regular_user = make_profile(sub="user-sub", email="user@test.local")
        self.managed_app = make_application(slug="ancrage", nom="Ancrage")
        self.auto_app = make_application(slug="socle", nom="SOCLE", requires_access_request=False)

    def test_list_members_requires_super_admin(self):
        auth_client(self.client, self.regular_user)
        response = self.client.get(f"/api/admin/catalog/applications/{self.managed_app.slug}/members/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_members_paginated(self):
        auth_client(self.client, self.super_admin)
        members = [{"id": f"user-{i}", "email": f"user{i}@test.local", "firstName": "User", "lastName": str(i)} for i in range(12)]
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.find_group_by_path.return_value = {"id": "group-ancrage"}
            kc.list_all_group_members.return_value = members
            response = self.client.get(
                f"/api/admin/catalog/applications/{self.managed_app.slug}/members/?page=2&page_size=10"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["total"], 12)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 10)
        self.assertEqual(len(payload["members"]), 2)

    def test_list_available_members(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.find_group_by_path.return_value = {"id": "group-ancrage"}
            kc.list_all_group_members.return_value = [
                {"id": "in-group", "email": "in@test.local", "firstName": "In", "lastName": "Group"}
            ]
            kc.list_all_users.return_value = [
                {"id": "in-group", "email": "in@test.local", "firstName": "In", "lastName": "Group"},
                {"id": "out-group", "email": "out@test.local", "firstName": "Out", "lastName": "Group"},
            ]
            response = self.client.get(
                f"/api/admin/catalog/applications/{self.managed_app.slug}/members/?side=available"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["members"][0]["keycloak_sub"], "out-group")

    def test_list_dual_members(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.find_group_by_path.return_value = {"id": "group-ancrage"}
            kc.list_all_group_members.return_value = [
                {"id": "in-group", "email": "in@test.local", "firstName": "In", "lastName": "Group"}
            ]
            kc.list_all_users.return_value = [
                {"id": "in-group", "email": "in@test.local", "firstName": "In", "lastName": "Group"},
                {"id": "out-group", "email": "out@test.local", "firstName": "Out", "lastName": "Group"},
            ]
            response = self.client.get(
                f"/api/admin/catalog/applications/{self.managed_app.slug}/members/dual/"
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(len(payload["members"]), 1)
        self.assertEqual(len(payload["available"]), 1)
        self.assertEqual(payload["members"][0]["keycloak_sub"], "in-group")
        self.assertEqual(payload["available"][0]["keycloak_sub"], "out-group")

    def test_list_members_rejects_auto_access_app(self):
        auth_client(self.client, self.super_admin)
        response = self.client.get(f"/api/admin/catalog/applications/{self.auto_app.slug}/members/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_member(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {"id": "new-user-sub"}
            kc.get_user_groups.return_value = []
            with patch("inscriptions.services.provisioning.provision_application_access") as provision:
                response = self.client.post(
                    f"/api/admin/catalog/applications/{self.managed_app.slug}/members/",
                    {"keycloak_sub": "new-user-sub"},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        provision.assert_called_once()

    def test_add_members_bulk(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {"id": "user-sub"}
            kc.get_user_groups.return_value = []
            with patch("inscriptions.services.provisioning.provision_application_access") as provision:
                response = self.client.post(
                    f"/api/admin/catalog/applications/{self.managed_app.slug}/members/",
                    {"keycloak_subs": ["user-a", "user-b"]},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(provision.call_count, 2)

    def test_remove_member(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {"id": "target-user-sub"}
            with patch("inscriptions.services.provisioning.revoke_application_access") as revoke:
                response = self.client.delete(
                    f"/api/admin/catalog/applications/{self.managed_app.slug}/members/target-user-sub/"
                )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        revoke.assert_called_once()

    def test_remove_members_bulk(self):
        auth_client(self.client, self.super_admin)
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {"id": "target-user-sub"}
            with patch("inscriptions.services.provisioning.revoke_application_access") as revoke:
                response = self.client.post(
                    f"/api/admin/catalog/applications/{self.managed_app.slug}/members/remove/",
                    {"keycloak_subs": ["user-a", "user-b"]},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(revoke.call_count, 2)


class AdminApplicationAccessApiTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.super_admin = make_profile(sub="super-admin-sub", email="super@test.local", is_super_admin=True)
        self.managed_app = make_application(slug="ancrage", nom="Ancrage")
        self.auto_app = make_application(slug="socle", nom="SOCLE", requires_access_request=False)
        self.out_of_si_app = make_application(slug="naturadapt", nom="Natur'Adapt", managed_by_si=False)

    def test_get_user_access(self):
        auth_client(self.client, self.super_admin)
        user_sub = "target-user-sub"
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {
                "id": user_sub,
                "email": "target@test.local",
                "firstName": "Target",
                "lastName": "User",
                "username": "target",
            }
            kc.get_user_groups.return_value = [{"path": f"/applications/{self.managed_app.slug}"}]
            response = self.client.get(f"/api/admin/users/{user_sub}/application-access/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {row["application"]["slug"] for row in response.json()["applications"]}
        self.assertIn(self.managed_app.slug, slugs)
        self.assertIn(self.auto_app.slug, slugs)
        self.assertNotIn(self.out_of_si_app.slug, slugs)

    def test_put_user_access(self):
        auth_client(self.client, self.super_admin)
        user_sub = "target-user-sub"
        with patch("inscriptions.views.KeycloakAdminClient") as kc_cls:
            kc = kc_cls.return_value
            kc.get_user.return_value = {"email": "target@test.local", "firstName": "T", "lastName": "U", "username": "t"}
            kc.get_user_groups.return_value = []
            with patch("inscriptions.services.application_access.prov.provision_application_access") as provision:
                response = self.client.put(
                    f"/api/admin/users/{user_sub}/application-access/",
                    {"access": {self.managed_app.slug: True}},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                provision.assert_called_once()
