import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from inscriptions.services.application_images import (
    ApplicationImageError,
    application_image_path,
    remove_application_image,
    save_application_image,
)
from inscriptions.tests.helpers import BaseApiTestCase, make_application, make_test_image_upload


class ApplicationImagesTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.managed_app = make_application(slug="ancrage", nom="Ancrage")

    def test_save_creates_png_named_after_slug(self):
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            filename = save_application_image(self.managed_app, make_test_image_upload("source.jpg"))
            self.assertEqual(filename, f"{self.managed_app.slug}.png")
            self.assertTrue((Path(self.tmpdir) / filename).is_file())
            self.managed_app.refresh_from_db()
            self.assertEqual(self.managed_app.image, filename)

    def test_save_rejects_oversized_file(self):
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            huge = SimpleUploadedFile("big.png", b"x" * (9 * 1024 * 1024), content_type="image/png")
            with self.assertRaises(ApplicationImageError):
                save_application_image(self.managed_app, huge)

    def test_remove_clears_db_and_file(self):
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            save_application_image(self.managed_app, make_test_image_upload())
            remove_application_image(self.managed_app)
            self.managed_app.refresh_from_db()
            self.assertEqual(self.managed_app.image, "")
            self.assertFalse((Path(self.tmpdir) / f"{self.managed_app.slug}.png").exists())

    def test_application_image_path_rejects_traversal(self):
        with self.assertRaises(ApplicationImageError):
            application_image_path("../etc/passwd")

    def test_serve_view_returns_image(self):
        with self.settings(APPLICATION_IMAGES_DIR=self.tmpdir):
            save_application_image(self.managed_app, make_test_image_upload())
            response = self.client.get(f"/media/application-images/{self.managed_app.slug}.png")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response["Content-Type"].startswith("image/"))

    def test_serve_view_404_when_missing(self):
        response = self.client.get("/media/application-images/missing.png")
        self.assertEqual(response.status_code, 404)
