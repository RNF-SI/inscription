"""Alignement de ``t_roles`` sur Keycloak pour les comptes d'annuaire.

Un compte fédéré porte l'identifiant que lui donne le LDAP. La plateforme ne peut pas
le renommer : le bandeau de « Mon compte » n'aurait aucun effet, c'est donc la base
historique qu'on aligne. L'``UPDATE`` déclenche la chaîne de triggers vers les bases
satellites, d'où le rapport seul par défaut et les refus plutôt que les écrasements.
"""

from unittest import mock

from django.test import TestCase

from inscriptions.services import legacy_writer
from inscriptions.tests.helpers import legacy_user_row


class AlignementAnnuaireTests(TestCase):
    """Un compte d'annuaire porte l'identifiant que lui donne le LDAP ; la plateforme
    ne peut pas le renommer, c'est donc ``t_roles`` qu'on aligne sur Keycloak.

    L'UPDATE déclenche la chaîne de triggers vers les bases satellites : d'où le
    rapport seul par défaut, et les refus plutôt que les écrasements."""

    def _lancer(self, *, comptes, lignes, occupant=None, apply=False):
        from io import StringIO

        from django.core.management import call_command

        sortie = StringIO()
        kc = mock.MagicMock()
        kc.is_configured.return_value = True
        kc.list_all_users.return_value = comptes
        with mock.patch.object(legacy_writer, "is_enabled", return_value=True), \
             mock.patch.object(legacy_writer, "find_role_id", return_value=occupant), \
             mock.patch.object(legacy_writer, "update_role_profile") as ecriture, \
             mock.patch(
                 "inscriptions.management.commands.aligner_identifiants_annuaire"
                 ".KeycloakAdminClient",
                 return_value=kc,
             ), \
             mock.patch(
                 "inscriptions.management.commands.aligner_identifiants_annuaire"
                 ".load_legacy_users",
                 return_value=lignes,
             ):
            args = ["--apply"] if apply else []
            call_command("aligner_identifiants_annuaire", *args, stdout=sortie, stderr=sortie)
        return sortie.getvalue(), ecriture

    def _compte(self, username, *, federe=True, id_role=42):
        compte = {
            "username": username,
            "email": f"compte{id_role}@example.org",
            "attributes": {"legacy_id_role": [str(id_role)]},
        }
        if federe:
            compte["federationLink"] = "ldap-rnf"
        return compte

    def test_compte_federe_est_aligne(self):
        sortie, ecriture = self._lancer(
            comptes=[self._compte("zmoulin")],
            lignes=[legacy_user_row("zacharie.moulin")],
            apply=True,
        )
        ecriture.assert_called_once_with(42, identifiant="zmoulin")
        self.assertIn("1 identifiant(s) aligné(s)", sortie)

    def test_rapport_seul_par_defaut(self):
        """L'écriture change le login sur toutes les applications RNF à la fois :
        elle ne doit jamais partir sans --apply."""
        sortie, ecriture = self._lancer(
            comptes=[self._compte("zmoulin")],
            lignes=[legacy_user_row("zacharie.moulin")],
        )
        ecriture.assert_not_called()
        self.assertIn("Rapport seul", sortie)

    def test_compte_non_federe_est_laisse_tranquille(self):
        """Son titulaire peut régulariser lui-même depuis « Mon compte » : lui
        imposer un identifiant serait gratuit."""
        _, ecriture = self._lancer(
            comptes=[self._compte("paul.lesiak", federe=False)],
            lignes=[legacy_user_row("Paul Lesiak")],
            apply=True,
        )
        ecriture.assert_not_called()

    def test_difference_de_casse_seule_nest_pas_alignee(self):
        _, ecriture = self._lancer(
            comptes=[self._compte("amelieptj")],
            lignes=[legacy_user_row("Amelieptj")],
            apply=True,
        )
        ecriture.assert_not_called()

    def test_identifiant_cible_deja_pris_est_refuse(self):
        sortie, ecriture = self._lancer(
            comptes=[self._compte("zmoulin")],
            lignes=[legacy_user_row("zacharie.moulin")],
            occupant=926,
            apply=True,
        )
        ecriture.assert_not_called()
        self.assertIn("conflit", sortie.lower())
        self.assertIn("926", sortie)

    def test_realm_sans_annuaire_ne_fait_rien(self):
        sortie, ecriture = self._lancer(
            comptes=[self._compte("paul.lesiak", federe=False)],
            lignes=[legacy_user_row("Paul Lesiak")],
            apply=True,
        )
        ecriture.assert_not_called()
        self.assertIn("Aucun compte d'annuaire", sortie)
