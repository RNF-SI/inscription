from django.test import TestCase
from rest_framework.test import APIClient

from inscriptions.models import Application, RegistrationRequest


class SignupApiTests(TestCase):
    def setUp(self):
        Application.objects.create(
            slug="ancrage",
            nom="Ancrage",
            url="https://example.org",
            image="",
            description="",
            managed_by_si=True,
        )
        self.client = APIClient()

    def test_register_creates_request(self):
        payload = {
            "nom_role": "Test",
            "prenom_role": "User",
            "identifiant": "tuser",
            "email": "t@example.org",
            "password": "secretpass1",
            "password_confirmation": "secretpass1",
            "remarques": "ok",
            "id_organisme": None,
            "organisme": "X",
            "champs_addi": {"ancrage": True, "reserves": []},
            "applications": [],
        }
        r = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(RegistrationRequest.objects.filter(email="t@example.org").exists())

    def test_register_accepts_empty_id_organisme_string(self):
        Application.objects.create(
            slug="opnl",
            nom="OPNL",
            url="",
            image="",
            description="",
            managed_by_si=True,
        )
        payload = {
            "nom_role": "Test",
            "prenom_role": "User",
            "identifiant": "tuser2",
            "email": "t2@example.org",
            "password": "secretpass1",
            "password_confirmation": "secretpass1",
            "remarques": "ok",
            "id_organisme": "",
            "organisme": "Organisme hors liste",
            "champs_addi": {"reserves": [], "opnl": True, "precisions_opnl": "x"},
            "applications": [],
        }
        r = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(RegistrationRequest.objects.filter(email="t2@example.org").exists())
