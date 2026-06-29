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
        response = self.client.get("/api/admin/catalog/applications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(any(row["slug"] == self.managed_app.slug for row in response.json()))

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
