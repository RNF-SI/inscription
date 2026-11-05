"""Refus du doublon à l'inscription, et non plus à la validation.

Le défaut constaté en production : une personne déjà titulaire d'un compte — reprise
de la base historique à la bascule — s'inscrit à nouveau. Le formulaire accepte,
puisqu'il ne contrôlait que la forme de l'identifiant. Des jours plus tard, le
super-admin valide et reçoit « Identifiant déjà utilisé » : c'est ``partialImport``
qui répond 409, pour l'adresse, et son message ne nomme que l'identifiant.
"""

from unittest import mock

from django.test import TestCase, override_settings
from rest_framework import status

from inscriptions.keycloak_client import KeycloakAdminError
from inscriptions.models import RegistrationRequest
from inscriptions.services import comptes_existants, workflows
from inscriptions.tests.helpers import (
    BaseApiTestCase,
    auth_client,
    make_application,
    make_profile,
    make_registration,
    signup_payload,
)


class FauxLegacy:
    """``t_roles`` bouchonné : les comptes qu'il connaît, par e-mail et identifiant."""

    def __init__(self, *, emails=(), identifiants=(), actif=True):
        self.emails = {e.lower() for e in emails}
        self.identifiants = {i.lower() for i in identifiants}
        self.actif = actif

    def is_enabled(self):
        return self.actif

    def find_role_id(self, *, email="", identifiant=""):
        if email and email.lower() in self.emails:
            return 4242
        if identifiant and identifiant.lower() in self.identifiants:
            return 4243
        return None


def faux_keycloak(*, emails=(), identifiants=(), erreur=False):
    kc = mock.MagicMock()
    if erreur:
        kc.find_user_by_email.side_effect = KeycloakAdminError("search_failed")
        kc.find_user_by_username.side_effect = KeycloakAdminError("search_failed")
    else:
        kc.find_user_by_email.side_effect = lambda e: (
            "sub-existant" if (e or "").lower() in {x.lower() for x in emails} else None
        )
        kc.find_user_by_username.side_effect = lambda u: (
            "sub-existant" if (u or "").lower() in {x.lower() for x in identifiants} else None
        )
    return kc


@override_settings(KEYCLOAK_SYNC_ENABLED=True)
class CompteExistantTests(TestCase):
    def _sans_legacy(self):
        return mock.patch.object(comptes_existants, "legacy_writer", FauxLegacy(actif=False))

    def test_adresse_connue_de_keycloak(self):
        with self._sans_legacy():
            conflit = comptes_existants.compte_existant(
                email="jean@example.org",
                identifiant="jdupont",
                kc=faux_keycloak(emails=["jean@example.org"]),
            )
        self.assertEqual(conflit.champ, "email")
        self.assertIn("Mot de passe oublié", conflit.message)

    def test_adresse_insensible_a_la_casse(self):
        with self._sans_legacy():
            conflit = comptes_existants.compte_existant(
                email="Jean@Example.ORG",
                kc=faux_keycloak(emails=["jean@example.org"]),
            )
        self.assertEqual(conflit.champ, "email")

    def test_adresse_connue_de_la_base_historique_seule(self):
        """Un compte peut exister pour les applications RNF sans être dans le realm."""
        with mock.patch.object(
            comptes_existants, "legacy_writer", FauxLegacy(emails=["jean@example.org"])
        ):
            conflit = comptes_existants.compte_existant(
                email="jean@example.org", kc=faux_keycloak()
            )
        self.assertEqual(conflit.champ, "email")

    def test_identifiant_pris(self):
        with self._sans_legacy():
            conflit = comptes_existants.compte_existant(
                email="libre@example.org",
                identifiant="jdupont",
                kc=faux_keycloak(identifiants=["jdupont"]),
            )
        self.assertEqual(conflit.champ, "identifiant")
        self.assertIn("déjà utilisé", conflit.message)

    def test_adresse_avant_identifiant(self):
        """Les deux sont pris : c'est « vous avez déjà un compte » qu'il faut dire."""
        with self._sans_legacy():
            conflit = comptes_existants.compte_existant(
                email="jean@example.org",
                identifiant="jdupont",
                kc=faux_keycloak(emails=["jean@example.org"], identifiants=["jdupont"]),
            )
        self.assertEqual(conflit.champ, "email")

    def test_tout_libre(self):
        with self._sans_legacy():
            self.assertIsNone(
                comptes_existants.compte_existant(
                    email="neuf@example.org", identifiant="neuf", kc=faux_keycloak()
                )
            )

    def test_keycloak_injoignable_ne_bloque_pas(self):
        """Le 409 de la validation reste le dernier filet ; une panne ne doit pas
        empêcher les inscriptions."""
        with self._sans_legacy():
            self.assertIsNone(
                comptes_existants.compte_existant(
                    email="jean@example.org", identifiant="jdupont", kc=faux_keycloak(erreur=True)
                )
            )

    @override_settings(KEYCLOAK_SYNC_ENABLED=False)
    def test_sans_keycloak_aucun_appel(self):
        kc = faux_keycloak(emails=["jean@example.org"])
        with self._sans_legacy():
            self.assertIsNone(
                comptes_existants.compte_existant(email="jean@example.org", kc=kc)
            )
        kc.find_user_by_email.assert_not_called()


@override_settings(KEYCLOAK_SYNC_ENABLED=True)
class InscriptionRefuseeTests(BaseApiTestCase):
    def setUp(self):
        super().setUp()
        make_application(slug="ancrage", nom="Ancrage")

    def _poster(self, kc, legacy=None, **overrides):
        legacy = legacy or FauxLegacy(actif=False)
        with mock.patch.object(comptes_existants, "KeycloakAdminClient", return_value=kc), \
             mock.patch.object(comptes_existants, "legacy_writer", legacy):
            return self.client.post("/api/register/", signup_payload(**overrides), format="json")

    def test_adresse_deja_prise_refusee(self):
        reponse = self._poster(faux_keycloak(emails=["tuser@example.org"]), email="tuser@example.org")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        message = reponse.json()["errors"]["email"][0]
        self.assertIn("Mot de passe oublié", message)
        self.assertFalse(RegistrationRequest.objects.exists())

    def test_identifiant_deja_pris_refuse(self):
        reponse = self._poster(faux_keycloak(identifiants=["tuser"]), identifiant="tuser")
        self.assertEqual(reponse.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("identifiant", reponse.json()["errors"])
        self.assertFalse(RegistrationRequest.objects.exists())

    def test_compte_neuf_accepte(self):
        reponse = self._poster(faux_keycloak())
        self.assertEqual(reponse.status_code, status.HTTP_201_CREATED)
        self.assertTrue(RegistrationRequest.objects.exists())


@override_settings(KEYCLOAK_SYNC_ENABLED=True)
class ValidationSuperAdminTests(BaseApiTestCase):
    """Les demandes déposées avant ce contrôle sont toujours en attente : leur refus
    doit être lisible, et ne rien écrire."""

    def test_approve_refuse_le_doublon_sans_rien_ecrire(self):
        reg = make_registration(email="jean@example.org")
        actor = make_profile(is_super_admin=True)
        kc = faux_keycloak(emails=["jean@example.org"])
        with mock.patch.object(workflows, "KeycloakAdminClient", return_value=kc), \
             mock.patch.object(comptes_existants, "legacy_writer", FauxLegacy(actif=False)), \
             mock.patch.object(workflows.mirror, "create_legacy_role") as create_legacy:
            with self.assertRaises(workflows.CompteDejaExistant) as capture:
                workflows.super_admin_approve(reg, actor.keycloak_sub)

        self.assertIn("Mot de passe oublié", capture.exception.message)
        create_legacy.assert_not_called()
        kc.create_user.assert_not_called()
        reg.refresh_from_db()
        self.assertEqual(reg.status, RegistrationRequest.STATUS_PENDING_SUPER)

    def test_route_repond_409_avec_le_motif(self):
        reg = make_registration(email="jean@example.org")
        actor = make_profile(is_super_admin=True)
        auth_client(self.client, actor)
        kc = faux_keycloak(emails=["jean@example.org"])
        with mock.patch.object(workflows, "KeycloakAdminClient", return_value=kc), \
             mock.patch.object(comptes_existants, "legacy_writer", FauxLegacy(actif=False)):
            reponse = self.client.post(
                f"/api/admin/registration-requests/{reg.public_id}/super-approve/"
            )
        self.assertEqual(reponse.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Mot de passe oublié", reponse.json()["detail"])
