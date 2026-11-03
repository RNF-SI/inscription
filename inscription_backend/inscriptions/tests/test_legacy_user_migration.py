from unittest import mock

from django.test import SimpleTestCase

from inscriptions.keycloak_client import KeycloakAdminError
from inscriptions.models import Application
from inscriptions.services.legacy_user_migration import (
    LEGACY_ADMIN_PROFIL_ID,
    LegacyApplicationRow,
    LegacyUserRow,
    _normalize_email,
    build_keycloak_password_credential,
    build_legacy_application_slug_map,
    _create_with_available_username,
    find_existing_keycloak_user,
    link_existing_keycloak_user,
    normalize_username,
)
from inscriptions.tests.helpers import legacy_user_row


def _compte(username="jdupont", email="jean@example.org", id_role=7):
    return LegacyUserRow(
        id_role=id_role, username=username, email=email,
        first_name="Jean", last_name="Dupont", fonction="", id_organisme=None,
    )


class RattachementCompteExistantTests(SimpleTestCase):
    """Les membres de l'équipe sont fédérés depuis l'annuaire : leur compte existe
    avant l'import, souvent sous un autre identifiant. Il faut leur donner les droits
    sans toucher à leur identifiant ni à leur mot de passe."""

    def test_rapprochement_par_attribut_dabord(self):
        """``legacy_id_role`` est le seul lien qui survit au renommage d'un
        identifiant : sans lui, un import rejoué créerait un doublon pour chaque
        compte renommé dépourvu d'adresse exploitable."""
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = "sub-1"
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte()), ("sub-1", "legacy_id_role")
        )
        kc.find_user_by_username.assert_not_called()
        kc.find_user_by_email.assert_not_called()

    def test_rapprochement_par_identifiant_ensuite(self):
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = "sub-1"
        kc.get_user.return_value = {"email": "jean@example.org"}
        self.assertEqual(find_existing_keycloak_user(kc, _compte()), ("sub-1", "identifiant"))
        kc.find_user_by_email.assert_not_called()

    def test_identifiant_identique_mais_autre_adresse_ne_rapproche_pas(self):
        """Le défaut constaté à la bascule du 2026-11-03.

        ``normalize_username()`` replie plusieurs identifiants historiques sur la
        même valeur — un identifiant en forme d'adresse est réduit à sa partie
        locale, et Keycloak replie tout en minuscules. Deux personnes distinctes
        peuvent donc revendiquer le même identifiant Keycloak.

        Ce jour-là, ``contact@reserve-iledugirard.org`` et ``Contact`` — deux
        personnes, deux organismes — ont fusionné sur un seul compte : l'une avait
        les droits des deux, l'autre n'avait plus de compte. L'adresse les sépare.
        """
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = "sub-de-quelqu-un-dautre"
        kc.get_user.return_value = {"email": "contact@reserve-iledugirard.org"}
        kc.find_user_by_email.return_value = None
        compte = _compte(username="Contact", email="contact@adena-bagnas.fr")
        self.assertIsNone(find_existing_keycloak_user(kc, compte))

    def test_identifiant_suffit_si_le_compte_keycloak_na_pas_dadresse(self):
        """Un compte d'annuaire n'a pas toujours d'adresse renseignée : l'identifiant
        reste alors le seul indice, et le refuser créerait un doublon."""
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = "sub-ldap"
        kc.get_user.return_value = {"email": ""}
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte()), ("sub-ldap", "identifiant")
        )

    def test_identifiant_suffit_si_la_ligne_historique_na_pas_dadresse(self):
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = "sub-1"
        kc.get_user.return_value = {"email": "autre@example.org"}
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte(email="")), ("sub-1", "identifiant")
        )

    def test_adresses_comparees_sans_tenir_compte_de_la_casse(self):
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = "sub-1"
        kc.get_user.return_value = {"email": "Jean@Example.ORG"}
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte(email="jean@example.org")),
            ("sub-1", "identifiant"),
        )

    def test_rapprochement_par_email_si_identifiant_different(self):
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = None
        kc.find_user_by_email.return_value = "sub-ldap"
        self.assertEqual(
            find_existing_keycloak_user(kc, _compte(username="ancien.login")),
            ("sub-ldap", "e-mail"),
        )

    def test_email_de_substitution_jamais_rapproche(self):
        """Les adresses @legacy-migration.local sont fabriquées : elles ne désignent
        personne, les rapprocher mélangerait des comptes sans rapport."""
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = None
        compte = _compte(email="jdupont@legacy-migration.local")
        self.assertIsNone(find_existing_keycloak_user(kc, compte))
        kc.find_user_by_email.assert_not_called()

    def test_aucun_rapprochement(self):
        kc = mock.MagicMock()
        kc.find_user_by_attribute.return_value = None
        kc.find_user_by_username.return_value = None
        kc.find_user_by_email.return_value = None
        self.assertIsNone(find_existing_keycloak_user(kc, _compte()))

    def test_rattachement_ne_touche_ni_identifiant_ni_mot_de_passe(self):
        kc = mock.MagicMock()
        with mock.patch(
            "inscriptions.services.legacy_user_migration.assign_legacy_groups"
        ) as droits:
            link_existing_keycloak_user(kc, _compte(), "sub-ldap")
        kc.create_user.assert_not_called()
        kc.update_user_profile.assert_not_called()
        droits.assert_called_once()

    def test_attribut_non_posable_nempeche_pas_les_droits(self):
        """Un compte fédéré en lecture seule refuse l'écriture d'attributs ; les
        droits, eux, vivent côté Keycloak et doivent être attribués quand même."""
        kc = mock.MagicMock()
        kc.set_user_attribute.side_effect = KeycloakAdminError("update_user_failed:400")
        with mock.patch(
            "inscriptions.services.legacy_user_migration.assign_legacy_groups"
        ) as droits:
            link_existing_keycloak_user(kc, _compte(), "sub-ldap")
        droits.assert_called_once()


class LegacyUserMigrationMappingTests(SimpleTestCase):
    def test_build_legacy_application_slug_map_fuzzy(self):
        """Le rapprochement par nom suffit : plus aucune correspondance codée en dur."""
        legacy_apps = [
            LegacyApplicationRow(4, "GNS", "GeoNature saisie"),
            LegacyApplicationRow(99, "waterwise-db", "Waterwise DB management"),
        ]
        django_apps = [
            Application(slug="geonature-saisie", nom="GeoNature Saisie"),
            Application(slug="waterwise", nom="Waterwise DB management"),
        ]
        mapping = build_legacy_application_slug_map(legacy_apps, django_apps)
        self.assertEqual(mapping[4], "geonature-saisie")
        self.assertEqual(mapping[99], "waterwise")

    def test_communaute_rnf_nest_pas_rapprochee_de_geonature(self):
        """id 14 = Communauté RNF en production : il ne doit rien accorder."""
        legacy_apps = [LegacyApplicationRow(14, "COMM_RNF", "Communauté RNF")]
        django_apps = [Application(slug="geonature-saisie", nom="GeoNature Saisie")]
        mapping = build_legacy_application_slug_map(legacy_apps, django_apps)
        self.assertNotIn(14, mapping)

    def test_normalize_email_fallback(self):
        self.assertEqual(_normalize_email("", "jean.dupont"), "jean.dupont@legacy-migration.local")
        self.assertEqual(_normalize_email("a@b.com", "jean"), "a@b.com")

    def test_legacy_user_row_defaults(self):
        user = LegacyUserRow(
            id_role=1,
            username="agent",
            email="agent@test.local",
            first_name="Jean",
            last_name="Dupont",
            fonction="Référent",
            id_organisme=12,
            password_bcrypt="$2b$12$abcdefghijklmnopqrstuv",
            app_member_slugs={"socle"},
            app_admin_slugs={"waterwise"},
            is_super_admin=True,
        )
        self.assertEqual(user.app_member_slugs, {"socle"})
        self.assertEqual(user.app_admin_slugs, {"waterwise"})
        self.assertTrue(user.is_super_admin)
        self.assertEqual(LEGACY_ADMIN_PROFIL_ID, 6)

    def test_build_keycloak_password_credential_bcrypt(self):
        cred = build_keycloak_password_credential(
            password_bcrypt="$2b$12$abcdefghijklmnopqrstuv",
            password_md5=None,
        )
        self.assertIsNotNone(cred)
        self.assertEqual(cred["type"], "password")
        self.assertIn("bcrypt", cred["credentialData"])

    def test_build_keycloak_password_credential_md5(self):
        cred = build_keycloak_password_credential(
            password_bcrypt=None,
            password_md5="5f4dcc3b5aa765d61d8327deb882cf99",
        )
        self.assertIsNotNone(cred)
        self.assertIn("md5", cred["credentialData"])


class NormalisationTests(SimpleTestCase):
    """Chaque cas vient de la base de production, pas d'une hypothèse."""

    def test_cas_reels(self):
        cas = [
            (legacy_user_row("Paul Lesiak"), "paul.lesiak"),
            (legacy_user_row("RNN Tourbière de Mathon"), "rnn.tourbiere.de.mathon"),
            (legacy_user_row("Aventine13!"), "aventine13"),
            (legacy_user_row("Bast/29/08"), "bast.29.08"),
            (legacy_user_row("Rémi Tiné"), "remi.tine"),
            (legacy_user_row("Lou-Anne Viricel"), "lou-anne.viricel"),
            (legacy_user_row("VO_RNRVigny-95"), "vo_rnrvigny-95"),
        ]
        for ligne, attendu in cas:
            with self.subTest(ligne.username):
                self.assertEqual(normalize_username(ligne), attendu)

    def test_tiret_entoure_despaces_ne_laisse_pas_de_separateur_orphelin(self):
        """Sans repli, « Réserve de Monteneuf - Océane » donnerait
        « reserve.de.monteneuf.-.oceane » : le tiret survit à la substitution."""
        for brut, attendu in (
            ("Réserve de Monteneuf - Océane", "reserve.de.monteneuf.oceane"),
            ("Océane PASQUET - Néouvielle", "oceane.pasquet.neouvielle"),
        ):
            with self.subTest(brut):
                self.assertEqual(normalize_username(legacy_user_row(brut)), attendu)

    def test_identifiant_en_forme_dadresse_perd_son_domaine(self):
        """Garder le domaine entrerait en conflit avec l'adresse d'un autre compte :
        la connexion par e-mail rend les deux indistinguables pour Keycloak."""
        ligne = legacy_user_row("valentin.demets@forestallia.com")
        self.assertEqual(normalize_username(ligne), "valentin.demets")

    def test_identifiant_trop_court_repart_de_letat_civil(self):
        ligne = legacy_user_row("OV", first_name="Olivier", last_name="Vannucci")
        self.assertEqual(normalize_username(ligne), "olivier.vannucci")

    def test_dernier_recours_sur_lidentifiant_technique(self):
        ligne = legacy_user_row("!!", first_name="", last_name="", id_role=7)
        self.assertEqual(normalize_username(ligne), "compte.7")


class SuffixeSurConflitTests(SimpleTestCase):
    """Deux comptes peuvent viser le même identifiant normalisé — homonymes, ou
    identifiant égal à l'adresse d'un autre compte. On suffixe plutôt que de
    réimplémenter les règles d'unicité de Keycloak."""

    def test_premier_essai_retenu_quand_libre(self):
        kc = mock.MagicMock()
        kc.create_user.return_value = "sub-1"
        user_id, username = _create_with_available_username(
            kc, legacy_user_row("Paul Lesiak"), password=None, temporary_password=False, credential=None
        )
        self.assertEqual((user_id, username), ("sub-1", "paul.lesiak"))

    def test_conflit_ajoute_un_suffixe(self):
        kc = mock.MagicMock()
        kc.create_user.side_effect = [
            KeycloakAdminError("create_user_failed:409", "User exists with same username"),
            "sub-2",
        ]
        _, username = _create_with_available_username(
            kc, legacy_user_row("valentin.demets@forestallia.com"), password=None,
            temporary_password=False, credential=None,
        )
        self.assertEqual(username, "valentin.demets.2")

    def test_autre_erreur_remonte(self):
        """Un 400 n'est pas un conflit : réessayer sous un autre nom masquerait la cause."""
        kc = mock.MagicMock()
        kc.create_user.side_effect = KeycloakAdminError("create_user_failed:400", "mauvais champ")
        with self.assertRaises(KeycloakAdminError):
            _create_with_available_username(
                kc, legacy_user_row("Paul Lesiak"), password=None, temporary_password=False, credential=None
            )
