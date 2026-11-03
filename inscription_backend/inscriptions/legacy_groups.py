"""Correspondance application du catalogue → groupe de ``utilisateurs.t_roles``.

C'est ce groupe qui porte l'accès côté historique : ``cor_role_app_profil`` n'est
plus alimenté en production (31 lignes pour 993 comptes, aucune depuis 2025), donc
``Application.legacy_group_id_role`` est la seule correspondance qui compte.

Les valeurs ne sont pas devinées. Elles viennent d'une corrélation sur la base de
production entre les cases cochées dans ``champs_addi`` par l'ancien formulaire
d'inscription et les groupes dont les demandeurs sont ensuite membres :

    case cochée        groupe retenu                  concordance
    ancrage            64  Grp_ancrage                279/300  (93 %)
    psdrf              1   Grp_global_et_psdrf        180/199  (90 %)
    geonature_saisie   14  Grp_saisie                 170/255  (67 %)
    waterwise          819 waterwise                   15/24   (62 %)
    opnl               36  Grp_opnl                    34/56   (61 %)
    syrphes            794 Grp_syrphes                  3/22   (14 %)

Les concordances inférieures à 100 % s'expliquent : cocher la case ne garantissait
pas que la demande soit acceptée. ``syrphes`` est la seule valeur faiblement étayée
— c'est cependant le seul groupe portant ce nom, et sans lui l'accès à cette
application n'accorderait rien.

Rien n'est posé pour ``socle``, ``tourbieres`` et ``site-internet`` : aucun groupe ne
leur correspond. Les deux premières ne passent de toute façon pas par une demande
d'accès. ``site-internet`` si, mais son accès ne tient pas à un groupe : c'est le
trigger ``complement_rnf.user_change()`` qui insère le compte dans
``site_internet_utilisateurs`` dès qu'il existe, et son rattachement aux réserves qui
détermine ce qu'il y voit. Vérifié en production le 2026-11-03, par une connexion au
site avec un compte créé par la plateforme.

Ce module est la **source vivante** de la correspondance, appliquée par
``seed_catalog``. La migration 0011 en garde une copie figée, comme toute migration ;
elle ne s'applique qu'aux bases où le catalogue existait déjà avant elle.
"""

# Applications à demande d'accès dont l'absence de groupe est **normale** : les
# signaler à chaque déploiement apprendrait à ignorer l'avertissement.
SANS_GROUPE_HISTORIQUE: dict[str, str] = {
    "site-internet": (
        "le trigger complement_rnf.user_change() insère le compte dans "
        "site_internet_utilisateurs dès qu'il existe ; ses réserves font le reste"
    ),
}

# slug du catalogue → utilisateurs.t_roles.id_role du groupe (groupe = true)
GROUPES_HISTORIQUES: dict[str, int] = {
    "ancrage": 64,
    "geonature-global": 1,
    "geonature-psdrf": 1,
    "geonature-saisie": 14,
    "opnl": 36,
    "syrphes": 794,
    "waterwise": 819,
}
