"""Correspondance application → groupe historique (utilisateurs.cor_roles).

Les valeurs ne sont pas devinées : elles viennent d'une corrélation sur la base de
production entre les cases cochées dans `champs_addi` par l'ancien formulaire
d'inscription et les groupes dont les demandeurs sont ensuite membres.

    case cochée        groupe retenu                  concordance
    ancrage            64  Grp_ancrage                279/300  (93 %)
    psdrf              1   Grp_global_et_psdrf        180/199  (90 %)
    geonature_saisie   14  Grp_saisie                 170/255  (67 %)
    waterwise          819 waterwise                   15/24   (62 %)
    opnl               36  Grp_opnl                    34/56   (61 %)
    syrphes            794 Grp_syrphes                  3/22   (14 %)

Les concordances inférieures à 100 % s'expliquent : cocher la case ne garantissait pas
que la demande soit acceptée. `syrphes` est la seule valeur faiblement étayée — c'est
cependant le seul groupe portant ce nom, et sans lui l'accès à cette application
n'accorderait rien.

Rien n'est posé pour `socle`, `tourbieres` et `site-internet` : aucun groupe ne leur
correspond, et ces applications ne passent de toute façon pas par une demande d'accès.
`legacy_id_application` reste vide partout, la production n'alimentant plus
`cor_role_app_profil`.
"""

from django.db import migrations

# slug du catalogue → utilisateurs.t_roles.id_role du groupe
GROUPES = {
    "ancrage": 64,
    "geonature-global": 1,
    "geonature-psdrf": 1,
    "geonature-saisie": 14,
    "opnl": 36,
    "syrphes": 794,
    "waterwise": 819,
}


def poser_groupes(apps, schema_editor):
    Application = apps.get_model("inscriptions", "Application")
    for slug, id_role in GROUPES.items():
        # Uniquement si rien n'est posé : une valeur saisie à la main fait foi.
        Application.objects.filter(slug=slug, legacy_group_id_role__isnull=True).update(
            legacy_group_id_role=id_role
        )


def retirer_groupes(apps, schema_editor):
    Application = apps.get_model("inscriptions", "Application")
    for slug, id_role in GROUPES.items():
        Application.objects.filter(slug=slug, legacy_group_id_role=id_role).update(
            legacy_group_id_role=None
        )


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0010_application_legacy_mapping"),
    ]

    operations = [
        migrations.RunPython(poser_groupes, retirer_groupes),
    ]
