from django.core import mail
from rest_framework import status

from inscriptions.models import AccessRequestItem, RegistrationRequest
from inscriptions.tests.helpers import BaseApiTestCase, make_application, signup_payload


class SignupApiTests(BaseApiTestCase):
    def test_register_creates_request(self):
        make_application(slug="ancrage", nom="Ancrage")
        payload = signup_payload()
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RegistrationRequest.objects.filter(email=payload["email"]).exists())

    def test_register_accepts_empty_id_organisme_string(self):
        make_application(slug="opnl", nom="OPNL")
        payload = signup_payload(
            identifiant="tuser2",
            email="t2@example.org",
            id_organisme="",
            champs_addi={"reserves": [], "opnl": True, "precisions_opnl": "x"},
        )
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_register_rejects_invalid_identifiant(self):
        payload = signup_payload(identifiant="bad ident")
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_rejects_short_identifiant(self):
        payload = signup_payload(identifiant="ab")
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("identifiant", response.json()["errors"])

    def test_register_rejects_identifiant_with_spaces(self):
        payload = signup_payload(identifiant="jean dupont")
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("espaces", response.json()["errors"]["identifiant"][0].lower())

    def test_register_rejects_password_mismatch(self):
        payload = signup_payload(password_confirmation="otherpass1")
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_requires_justification_for_managed_apps(self):
        make_application(slug="waterwise", nom="Waterwise", requires_access_request=True)
        payload = signup_payload(
            applications=[{"application_slug": "waterwise", "justification": ""}],
        )
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_creates_access_items(self):
        make_application(slug="waterwise", nom="Waterwise", requires_access_request=True)
        payload = signup_payload(
            applications=[{"application_slug": "waterwise", "justification": "Projet X"}],
        )
        response = self.client.post("/api/register/", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        reg = RegistrationRequest.objects.get(email=payload["email"])
        self.assertEqual(reg.items.filter(application__slug="waterwise").count(), 1)
        self.assertGreaterEqual(len(mail.outbox), 2)

    def test_register_sends_superadmin_notification(self):
        make_application(slug="ancrage", nom="Ancrage")
        payload = signup_payload()
        self.client.post("/api/register/", payload, format="json")
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any("inscription" in s.lower() for s in subjects))
        recipients = {addr for message in mail.outbox for addr in message.to}
        self.assertIn(payload["email"], recipients)


class PublicCatalogApiTests(BaseApiTestCase):
    def test_list_applications(self):
        managed = make_application(slug="ancrage", nom="Ancrage")
        external = make_application(slug="naturadapt", nom="Natur'Adapt", managed_by_si=False)
        response = self.client.get("/api/applications/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = {row["slug"] for row in response.json()}
        self.assertIn(managed.slug, slugs)
        self.assertIn(external.slug, slugs)

    def test_keycloak_public_config(self):
        response = self.client.get("/api/auth/keycloak-config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("keycloakUrl", data)
        self.assertIn("realm", data)
        self.assertIn("clientId", data)
