from inscriptions.serializers import AdminApplicationWriteSerializer, SignupSerializer
from inscriptions.tests.helpers import BaseApiTestCase, make_application


class SignupSerializerTests(BaseApiTestCase):
    def test_valid_minimal_payload(self):
        make_application(slug="ancrage", nom="Ancrage")
        ser = SignupSerializer(
            data={
                "nom_role": "Dupont",
                "prenom_role": "Jean",
                "identifiant": "jdoe",
                "email": "j@test.local",
                "password": "secretpass1",
                "password_confirmation": "secretpass1",
                "remarques": "",
                "organisme": "X",
                "applications": [],
            }
        )
        self.assertTrue(ser.is_valid(), ser.errors)

    def test_slug_write_unique(self):
        make_application(slug="existing")
        ser = AdminApplicationWriteSerializer(
            data={
                "slug": "existing",
                "nom": "Doublon",
                "managed_by_si": True,
                "requires_access_request": True,
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("slug", ser.errors)

    def test_admin_write_slug_readonly_on_update(self):
        app = make_application(slug="editable")
        ser = AdminApplicationWriteSerializer(app, data={"slug": "changed", "nom": "Nouveau nom"}, partial=True)
        self.assertTrue(ser.is_valid(), ser.errors)
        updated = ser.save()
        self.assertEqual(updated.slug, "editable")
        self.assertEqual(updated.nom, "Nouveau nom")
