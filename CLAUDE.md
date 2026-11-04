# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Vue d'ensemble

Plateforme d'inscription au SI de Réserves Naturelles de France, adossée à Keycloak.
Le dépôt contient trois dossiers de code :

| Dossier | Rôle |
|---|---|
| `inscription_backend/` | **Backend actif** : API Django REST servie sous `/api` |
| `frontend/` | **Frontend actif** : SPA Angular 22 |
| `backend/` | **Ancien backend Flask/UsersHub**, conservé pour rollback uniquement — ne pas y développer |

`frontend/src/app/core/` est le **socle internalisé** : l'ancien sous-module `RNF-SI/home-rnf` a
été repris dans le dépôt (comme dans `socle-v2`), il n'y a donc plus de sous-module git. Il fournit
le layout (`NavHomeComponent`), les guards et `AuthService` (flux OIDC complet) :

| Dossier | Contenu |
|---|---|
| `core/auth/` | `AuthService`, `AuthGuard`, `AdminGuard`, `LazyDialog`, `LogoutLinkService`, `User` |
| `core/components/` | `nav-home`, `login`, `logout`, `forgot-password`, `loading-spinner`, `toast` |
| `core/services/` | `notification-badge`, `contact`, `search`, `redirect`, `toast` |
| `core/pipes/` | `inputError` (utilisé par le template de `login`) |

Ces composants sont `standalone: false` et sont déclarés dans `app.module.ts`, qui reprend aussi ce
que fournissait `HomeRnfModule` : les modules Material correspondants, les bouchons
`MAT_DIALOG_DATA`/`MatDialogRef` (`LoginComponent` est routé, pas ouvert en dialogue) et
`library.addIconPacks(fab, fas, far)` — le menu lit ses icônes depuis `AppConfig`, elles ne sont
pas dans la liste explicite d'`addIcons`.

Documentation détaillée : `README.md` (déploiement, cutover), `inscription_backend/docs/keycloak-v1-spec.txt`
(conventions de groupes Keycloak), `inscription_backend/docs/runbook-cutover.txt`.

## Commandes

### Backend (`inscription_backend/`, venv dans `venv/`)

```bash
source venv/bin/activate
python manage.py migrate
python manage.py seed_catalog            # catalogue applications (idempotent)
python manage.py runserver               # http://localhost:8000, API sous /api/
```

Tests (SQLite en mémoire, Keycloak désactivé via `config.settings_test`) :

```bash
pip install -r requirements-dev.txt               # pytest n'est pas dans requirements.txt
pytest                                            # tout (testpaths = inscriptions/tests)
pytest inscriptions/tests/test_workflows.py       # un fichier
pytest inscriptions/tests/test_workflows.py -k approve   # un test
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test inscriptions.tests  # équivalent
```

La suite unitaire est hermétique : `settings_test` force `KEYCLOAK_BASE_URL` sur un hôte non
routable, donc aucun test ne peut joindre un vrai Keycloak (elle tourne en <1 s). Un test qui
active `KEYCLOAK_SYNC_ENABLED` doit patcher les points d'entrée qu'il exerce.

Les tests d'intégration Keycloak touchent un **vrai realm** et sont exclus par défaut :

```bash
KEYCLOAK_TEST_INTEGRATION=1 DJANGO_SETTINGS_MODULE=config.settings \
  python manage.py test inscriptions.tests.test_keycloak_integration
```

Ils refusent de s'exécuter sur `rnf`, `si-rnf`, `master`… En local, pointer `KEYCLOAK_REALM`
vers un realm de test (`inscription-test`) dans `.env`.

Les tests d'intégration de l'écriture miroir **effacent des schémas entiers** : ils refusent
toute base dont le nom ne contient pas « test », et le `.env` pointant sur la production,
il faut écraser `LEGACY_DATABASE_URL` dans l'environnement (django-environ lit le `.env`
en `overwrite=False`, la variable exportée gagne donc) :

```bash
createdb -T template0 inscription_legacy_test
export LEGACY_TEST_INTEGRATION=1
LEGACY_DATABASE_URL=postgres://user:pass@localhost:5432/inscription_legacy_test \
  DJANGO_SETTINGS_MODULE=config.settings \
  python manage.py test inscriptions.tests.test_legacy_integration
```

Ils chargent `inscriptions/tests/sql/legacy_schema.sql`, qui reproduit le schéma historique
**avec ses triggers de production** : c'est ce qui permet de vérifier que `cor_role_rn` est
bien peuplé par le trigger, sans doublon, et que les bases satellites reçoivent le compte.

Autres commandes de gestion : `promote_super --email=…`, `import_application_images`,
`synchro_radis` (référentiel réserves/organismes depuis RADIS, `--a-blanc` d'abord),
`migrate_legacy` (amorçage du référentiel depuis la base historique), `migrate_legacy_users_to_keycloak` (voir README.md §4 — destructif, `--dry-run` d'abord),
`reconcile_legacy_keycloak` (compare base historique et Keycloak ; rapport seul, `--apply`
se limite à reposer l'attribut `legacy_id_role`), `audit_identifiants` (lecture seule :
comptes dont l'identifiant Keycloak diffère de l'identifiant historique, `--csv` pour la
liste complète), `aligner_identifiants_annuaire` (écrit dans `t_roles` l'identifiant
Keycloak des comptes fédérés — rapport seul, `--apply` pour écrire).

### Frontend (`frontend/`)

```bash
nvm use          # Node 22 requis par Angular 22
npm start        # http://localhost:4200
npm run build    # → dist/inscription/
npm test         # Karma/Jasmine
```

### Configuration

- Backend : `inscription_backend/.env` (`django-environ`). **Ne jamais mettre de commentaire en fin
  de ligne** — django-environ ne les ignore pas.
- Frontend : `src/environments/environment{,.prod}.ts` (apiUrl, repli Keycloak, instance Matomo —
  `matomoUrl` à `null` en développement désactive la mesure d'audience) et
  `src/conf/app.config.ts` (libellés, menu, feature flags, intervalle de polling des notifications).

## Architecture

### Keycloak est la source de vérité des droits

Django ne stocke **pas** d'utilisateurs (`AUTH_USER_MODEL` Django n'est pas utilisé pour l'API).
L'authentification passe par `KeycloakJWTAuthentication` (`inscriptions/authentication.py`) qui
valide le JWT via JWKS et expose un `KeycloakUser` (porteur de `sub` + `claims`). Les droits
découlent des **chemins de groupes Keycloak**, pas de tables locales :

```
/organismes/<slug>                (attributs id_organisme, nom_organisme, uuid_organisme)
/reserves/<code>                  ex. /reserves/RNN41
/reserves/<code>/referent
/applications/<slug>              droit d'accès à l'application
/applications/<slug>/admin        validateur applicatif
/super-admin
```

`inscriptions/roles.py` traduit ces chemins en rôles (`is_super_admin`, `is_app_admin`,
`admin_application_slugs`). Les groupes viennent du claim `groups` du JWT, avec **repli** sur
l'Admin API Keycloak quand le mapper n'est pas configuré (`effective_groups_from_claims`).
`inscriptions/permissions.py` expose les permissions DRF correspondantes.

Le JWT doit avoir été émis pour le client SPA : `aud` contenant `KEYCLOAK_APP_CLIENT_ID`, ou à
défaut `azp` égal à ce client (Keycloak met souvent `account` dans `aud`). Un token valide du
realm mais émis pour un autre client est refusé. Les clés de signature JWKS sont mises en cache
par URL au niveau module (`reset_jwks_cache()` après changement de realm).

Toutes les écritures Keycloak passent par `KeycloakAdminClient` (`inscriptions/keycloak_client.py`,
client de service `inscription-admin`), dont les `ensure_*_group` sont idempotents.
`KEYCLOAK_SYNC_ENABLED=0` désactive ces appels (diagnostic, tests).

Conséquence pratique : les demandes en attente (référent, retrait de membre) sont **supprimées**
une fois traitées — l'état final vit dans Keycloak, pas en base.

### Écriture miroir vers la base historique

Les autres applications RNF lisent encore leurs comptes dans `geonature_global`
(schémas `utilisateurs` et `complement_rnf`). Toute mutation faite ici y est donc
répercutée, en plus de Keycloak — qui n'est pour l'instant consommé que par cette
application. `inscriptions/services/legacy_writer.py` porte **toutes** les écritures
historiques, `services/mirror.py` les orchestre avec Keycloak.

Règles qui gouvernent ce code :

- **Tout ou rien.** `mirror.atomic_mirror()` ouvre une transaction sur chaque base et
  tient une pile d'annulations pour ce que Keycloak a déjà fait. L'écriture
  historique passe **avant** l'appel Keycloak : PostgreSQL sait annuler, l'API Admin
  non, donc un échec Keycloak laisse la base intacte.
- **`cor_role_rn` est peuplé par un trigger à la création.**
  `complement_rnf.after_insert_user_function()` lit `champs_addi->'reserves'` à
  l'INSERT de `t_roles`. On écrit donc `champs_addi` et on laisse faire ; écrire aussi
  les lignes produirait des doublons. `sync_reserves()` ne sert qu'aux modifications
  ultérieures.
- **Colonnes à ne jamais écrire** : `id_role`, `uuid_role`, `active`, `groupe` (valeurs
  par défaut PostgreSQL), `date_insert` et `date_update` (triggers `tri_modify_date_*`).
- **Ne pas vider `pass_plus`** : `complement_rnf.user_change()` conditionne l'insertion
  dans `site_internet_utilisateurs` à `pass_plus IS NOT NULL`.
- **`cor_role_rn.rn_id` est le code textuel** de la réserve (`RNN41`), clé étrangère
  vers `ref_geo.l_areas.area_code` : aucune conversion vers un identifiant numérique.
- Le mot de passe en clair n'existe qu'à l'instant du déchiffrement Fernet dans
  `super_admin_approve` : c'est le seul endroit où le bcrypt historique peut être
  calculé (`$2b$`, coût 12, comme le produisait UsersHub).

Le lien entre les deux mondes est l'attribut Keycloak `legacy_id_role`, posé à la
création et par l'import. `mirror.legacy_id_role_for()` le lit, avec repli sur l'e-mail
puis l'identifiant.

**L'identifiant du compte Keycloak est l'`uuid_role` de sa ligne `t_roles`.** Le `sub`
des jetons est donc directement la clé de jointure vers la base historique : pas
d'attribut à lire, pas de requête supplémentaire, et la correspondance survit au
changement d'adresse comme d'identifiant. `create_role()` renvoie les deux clés
(`NouveauRole`), et c'est pour cela que l'écriture historique précède l'appel Keycloak :
l'`uuid_role` est généré par PostgreSQL (`uuid_generate_v4()`), il faut que la ligne
existe pour le connaître.

Keycloak ne l'accepte que par un chemin particulier. `POST /users` **ignore** le champ
`id` qu'on lui donne et en génère un autre ; `PUT /users/{id}` ne permet pas de le
changer. Seul `POST /admin/realms/<realm>/partialImport` respecte l'`id` fourni, d'où
`KeycloakAdminClient._create_user_with_id()`, emprunté dès que `create_user(user_id=…)`
est appelé. Il emporte le mot de passe (en clair, qu'il hache, ou en hash importé), les
groupes, les attributs, `requiredActions` et `emailVerified`. Trois particularités :

- `ifResourceExists` reste à **`FAIL`**. `OVERWRITE` réécrit bien l'`id` d'un compte
  existant, mais en supprimant et recréant : tout ce que la charge utile ne redonne pas
  est perdu — mot de passe, attributs, appartenances aux groupes. Un identifiant déjà
  pris doit ressortir en 409, pour que la boucle de suffixe de l'import retente.
- Un 200 ne vaut pas succès : c'est le rapport (`added`, `results[].id`) qui dit ce qui
  a été fait. Un `id` rendu différent de celui demandé est refusé, un compte mal
  identifié ruinerait la jointure.
- Ce chemin **ne passe pas les validateurs d'identifiant du realm** (un espace y est
  accepté, replié en minuscules) mais applique bien la déclaration des attributs du
  profil utilisateur.

Les comptes qui existaient déjà dans le realm — l'équipe, fédérée depuis l'annuaire —
ne peuvent pas être réidentifiés : leur `id` est antérieur. Ils portent donc
l'`uuid_role` en attribut (`mirror.UUID_ROLE_ATTRIBUTE`), posé par
`link_existing_keycloak_user()`, pour que la jointure reste possible dans les deux cas.
Comme `legacy_id_role`, **cet attribut doit être déclaré dans le profil utilisateur du
realm**, sinon il est silencieusement jeté.

⚠️ **Cet attribut n'est conservé que si le realm l'accepte.** Le profil utilisateur de
Keycloak ne déclare par défaut que `username`, `email`, `firstName`, `lastName` et
`function` : tout autre attribut est accepté par l'API puis **silencieusement jeté**.
Déclarer `legacy_id_role` dans *Realm settings → User profile* (comme l'est déjà
`function`), sinon chaque résolution retombe sur la recherche par e-mail — ce qui
fonctionne, mais coûte une requête de plus et casse si l'adresse change.

L'import rattache les comptes déjà présents dans le realm — les membres de l'équipe,
fédérés depuis l'annuaire — au lieu d'en créer des doubles :
`find_existing_keycloak_user()` cherche par `legacy_id_role`, puis par identifiant,
puis par e-mail, et `link_existing_keycloak_user()` n'attribue que les droits, sans
toucher à l'identifiant, au mot de passe ni au profil, gérés par l'annuaire. Les
adresses de substitution `@legacy-migration.local` ne sont jamais rapprochées.
L'attribut passe en premier parce que c'est le seul lien qui survit au renommage d'un
identifiant (ci-dessous) : sans lui, un import rejoué créerait un doublon pour chaque
compte renommé dépourvu d'adresse exploitable.

### Les identifiants qu'UsersHub acceptait et que Keycloak refuse

`utilisateurs.t_roles.identifiant` n'a jamais été contraint : une centaine de comptes
portent un espace, d'autres un `!` ou un `/`, quelques-uns tiennent en deux lettres.
Keycloak les refuse, et ces comptes resteraient absents du realm.

`legacy_user_migration.normalize_username()` en dérive donc un identifiant acceptable
— minuscules, `[a-z0-9._-]`, trois caractères au moins, partie locale seule si
l'identifiant a la forme d'une adresse — et `_create_with_available_username()`
suffixe `.2`, `.3`… sur conflit plutôt que de réimplémenter les règles d'unicité de
Keycloak (un identifiant ne peut pas non plus égaler l'adresse d'un autre compte quand
la connexion par e-mail est active).

**L'identifiant historique n'est pas touché** : les applications qui lisent
`t_roles` continuent d'authentifier avec l'ancien nom. Ces comptes portent donc deux
noms, et le rattrapage tient en trois pièces :

- `--username-report <csv>` sur `migrate_legacy_users_to_keycloak` écrit la liste des
  comptes renommés (nom, prénom, ancien login, nouveau login, e-mail) pour pouvoir
  les contacter.
- `mirror.legacy_username_state()` renvoie l'identifiant historique et dit s'il faut
  inviter son titulaire à régulariser ; `/api/me/` l'expose en `legacy_username` et
  `username_diverges`, et « Mon compte » affiche l'ancien, pas celui de Keycloak.
  **La comparaison est insensible à la casse** : Keycloak replie les identifiants en
  minuscules, et 280 comptes ne divergent que par là — chaque monde authentifie le
  sien, il n'y a rien à corriger. Un compte fédéré est exclu : son identifiant
  appartient à l'annuaire, le bandeau ne disparaîtrait jamais.
- `audit_identifiants` (lecture seule, `--csv`) donne l'état des lieux ; la liste
  rétrécit à mesure que les gens régularisent.

Les **comptes d'annuaire** font exception et vont dans l'autre sens. Un compte fédéré
depuis le LDAP porte l'identifiant que l'annuaire lui donne : la plateforme ne peut pas
le renommer, le bandeau n'aurait aucun effet. C'est donc `t_roles` qu'on aligne sur
Keycloak, avec `aligner_identifiants_annuaire` (rapport seul par défaut, `--apply` pour
écrire, `--legacy-id` pour un essai). Ces comptes sont ceux de l'équipe : leur imposer
le changement coûte moins que de laisser deux identifiants coexister.

⚠️ **Cet `UPDATE` change leur login sur toutes les applications RNF à la fois**, via la
chaîne de triggers de `t_roles` (`utilisateurs_saisie`, `utilisateurs_sinp`,
`site_internet_utilisateurs`). C'est pourquoi l'alignement est une commande à part et
non une étape de l'import, qui reste en lecture seule côté historique. La commande
refuse d'écraser un identifiant déjà porté par un autre `id_role`, et un `UPDATE` par
compte évite qu'un échec annule les alignements déjà propagés.

`MeUpdateSerializer.validate_username` applique la même règle que la normalisation,
et `_identifiant_deja_pris()` (dans `views.py`) vérifie l'unicité **des deux côtés**
avant d'écrire : deux comptes partageant un identifiant casseraient la connexion aux
applications qui le lisent dans `t_roles`.

Ce que la base de production montre, et que les réglages reproduisent :

- **Les groupes portent les droits, pas `cor_role_app_profil`.** Cette table ne compte
  que 31 lignes pour 993 comptes, posées à la main entre 2022 et 2024 ; aucune depuis
  2025. `LEGACY_INSCRIPTION_APP_ID` vaut donc 0 par défaut. C'est
  `legacy_group_id_role` sur `Application` qui compte, pas `legacy_id_application`.
- **Tout compte créé entre dans `Grp_all`** (202 des 211 comptes de 2026) :
  `LEGACY_DEFAULT_GROUP_IDS` vaut `[69]`. L'omettre priverait les inscrits de ce que ce
  groupe confère. `add_to_groups()` vérifie l'existence de chaque groupe avant insertion,
  une clé étrangère en défaut ferait échouer toute la création.
- **Le md5 est toujours alimenté** : les comptes les plus récents en portent un, d'où
  `LEGACY_WRITE_PASS_MD5` à `True` par défaut.
- **La chaîne de triggers est profonde.** Un INSERT dans `t_roles` écrit en cascade dans
  `utilisateurs_saisie`, `utilisateurs_sinp` (tables distantes vers deux autres bases
  GeoNature), `complement_rnf.cor_role_rn`, puis `site_internet_utilisateurs` et
  `site_internet_cor_utilisateur_rn` (tables distantes vers MySQL). Une création de
  compte fait donc plusieurs écritures distantes synchrones dans la transaction.

Une application ne répercute ses accès que si `legacy_id_application` est renseigné sur
son enregistrement `Application` (avec `legacy_id_profil`, 1 = Lecteur, et
`legacy_group_id_role` pour `utilisateurs.cor_roles`). Sans cette correspondance, rien
n'est écrit côté historique.

**Le mot de passe se change par `POST /api/me/password/`, et nulle part ailleurs.**
`mirror.change_password()` écrit le bcrypt dans `t_roles.pass_plus` puis le pose dans
Keycloak. La console de compte Keycloak n'écrirait que dans Keycloak : l'usager
garderait son ancien mot de passe sur toutes les applications qui lisent la base
historique. Retirer `manage-account` des rôles par défaut du realm ferme ce chemin.

Le mot de passe actuel est vérifié contre le bcrypt historique, et non par Keycloak :
le client SPA n'autorise pas le « direct grant », et l'activer pour cela affaiblirait
le realm. Un compte fédéré depuis un annuaire (`federationLink` posé) est refusé — son
mot de passe ne nous appartient pas.

Le parcours « mot de passe oublié » est porté par la plateforme pour la même raison :
`POST /api/password-reset/` puis `POST /api/password-reset/confirm/`, routes publiques
limitées en débit (`password_reset`). Trois précautions dans
`services/password_reset.py` : la demande répond toujours la même chose, connue ou
non, pour ne pas révéler quelles adresses existent ; seule l'empreinte SHA-256 du
jeton est stockée ; et le jeton est à usage unique, invalidé avec les autres en
attente du même compte. Les deux routes doivent rester dans `isPublicApiRequest` de
l'intercepteur HTTP.

Pour tester sur une copie de production, il faut d'abord **remplacer toutes les tables
distantes par des tables locales** : un `pg_dump` emporte `CREATE SERVER`, `CREATE USER
MAPPING` et `CREATE FOREIGN TABLE`, donc la copie écrit vers les cibles d'origine. Ne
pas couper le lien sans remplacer la table : l'INSERT du trigger échouerait et annulerait
la création de compte.

### Le référentiel des réserves et des organismes vient de RADIS

`Organisme`, `Reserve` et `OrganismeReserveLink` ne sont pas saisis ici : ils
descendent de **RADIS** (equipe-app, `RNF-SI/equipe-app`), l'outil de gestion des
données réserves. `manage.py synchro_radis` les **tire** de son API v1 publique,
comme le fait SOCLE pour ses sites ; `--a-blanc` montre ce qui changerait. Deux
réglages : `RADIS_API_URL` et `RADIS_API_KEY` (header `X-API-Key`, clé à demander au
Pôle SI). Idempotente, destinée à un minuteur nocturne.

`migrate_legacy` ne sert plus qu'à l'amorçage. Il lisait `ref_geo.l_areas`,
`utilisateurs.bib_organismes` et `complement_rnf.cor_rn_og`, c'est-à-dire un *push* de
RADIS vers la base historique : il pousse mais ne réconcilie jamais, et perd ce qu'il
n'a pas vu passer — 465 liens lus pour 451 créés à la bascule, parce que `cor_rn_og`
garde les liaisons terminées et saute les organismes dépourvus d'UUID SINP.

**La synchronisation ne va que dans ce sens.** Cette plateforme porte plus
d'organismes que RADIS — tous ne gèrent pas une réserve — et rien n'est renvoyé
là-bas. Ce que `services/radis.py` ne fait jamais, chaque point répondant à un dégât
possible :

- **supprimer ou désactiver un organisme.** Un organisme absent de la réponse de RADIS
  est indiscernable d'un organisme qui n'en vient pas. Seuls ceux qui portent un
  `radis_id` sont comparés, et leur disparition est signalée, pas appliquée ;
- **créer un organisme.** `Organisme.id_organisme` est la clé primaire de
  `utilisateurs.bib_organismes`, que `legacy_writer` écrit dans `t_roles.id_organisme`
  — colonne qui la référence. Un identifiant inventé ici ferait échouer la création de
  compte de ses membres. Un organisme de RADIS sans correspondance est donc signalé,
  à créer d'abord côté base historique ;
- **recalculer un `keycloak_slug`.** Il est dans le chemin `/organismes/<slug>`, donc
  dans les jetons déjà émis, et `_organisme_for_request` s'en sert en repli. Un
  organisme renommé change de `nom_organisme`, pas de slug ;
- **réécrire ce qui n'a pas changé**, pour qu'un rapport nocturne ne montre que ce qui
  a bougé.

**La liste des réserves de RADIS fait loi.** Une réserve que son inventaire ne
contient pas est supprimée ici ; l'inventaire porte aussi les déclassées, donc une
absence y signifie « cette réserve n'existe pas », pas « elle est sortie du réseau ».
Une réserve **déclassée**, elle, garde sa ligne : elle prend `ancienne_reserve` et
quitte les listes où l'on se rattache, parce que les groupes Keycloak
`/reserves/<code>` et les lignes `cor_role_rn` de ses membres référencent ce code. La
suppression emporte les liens de la réserve et les demandes en attente qui la visent —
d'où `--a-blanc`, qui donne la liste avant qu'elle ne soit appliquée.

**Un organisme créé dans RADIS est créé ici, mais d'abord dans `bib_organismes`.**
`Organisme.id_organisme` **est** la clé primaire de `utilisateurs.bib_organismes`, que
`legacy_writer` écrit dans `t_roles.id_organisme` — colonne qui la référence.
L'identifiant ne peut donc pas être choisi ici : `legacy_writer.create_organisme()`
insère la ligne historique, la séquence donne l'identifiant, et la ligne locale le
reprend. L'ordre est le même que pour les comptes, et pour la même raison. Un
organisme déjà présent dans `bib_organismes` — posé à la main, ou par le push de RADIS
vers GeoNature — est **adopté** plutôt que dupliqué (`find_organisme()`, par UUID puis
par nom insensible à la casse). `--sans-creation` coupe ce comportement, et sans
`LEGACY_WRITE_ENABLED` les manquants sont seulement listés : les créer ici sans ligne
historique ferait échouer la création de compte de chacun de leurs membres.

⚠️ **Dix UUID du SINP sont portés par plusieurs organismes de RADIS**, et ils ne
désignent pas des doublons : « Conservatoire d'espaces naturels de Normandie » et
« Région Normandie » partagent le même, comme l'ONF et deux de ses agences. Rapprocher
par cette valeur renommerait le conservatoire en région. Un UUID partagé n'est donc
pas une clé : les organismes concernés ne sont pas rapprochés, l'UUID n'est pas
recopié à la création, et le rapport les liste pour correction dans RADIS. Le
`radis_id`, lui, passe avant : un organisme déjà rapproché n'est pas affecté.

Les **liens** font exception et se suppriment : ils n'alimentent que
`/api/me/reserve-options/`, la liste des réserves proposées d'après l'organisme. Ce ne
sont pas des droits — ceux-là viennent des groupes Keycloak — et un lien périmé
proposerait une réserve que l'organisme ne gère plus. Seuls les liens d'organismes
connus de RADIS sont réconciliés.

Deux clés rendent tout cela possible, et une seule a demandé un changement :

- **les réserves se joignent telles quelles.** L'`id_local` de RADIS *est* l'`area_code`
  d'ici (`RNN41`), qui est aussi `cor_role_rn.rn_id`, le `site.code` de SOCLE et le
  chemin du groupe Keycloak. Changer de source ne change aucune clé ;
- **les organismes ont demandé d'exposer l'`uuid_organisme`** dans l'API de RADIS
  (`RNF-SI/equipe-app#107`). L'API ne publiait que l'`id` interne de RADIS et
  l'`assoconnect_id`, qui n'existent pas ici ; l'UUID du référentiel des organismes du
  SINP, lui, est la valeur que porte `bib_organismes.uuid_organisme`. Le rapprochement
  se fait par `radis_id` d'abord, puis par cet UUID, **jamais par le nom** — qu'un
  organisme renommé dans Assoconnect rendrait inopérant.

⚠️ **`cor_role_rn.rn_id` est une clé étrangère vers `ref_geo.l_areas.area_code`**, et
c'est un trigger qui l'alimente à l'INSERT de `t_roles`. Une réserve que RADIS connaît
mais qui manque à `l_areas` ferait donc échouer la création de compte tout entière de
celui qui la coche. La synchronisation compare les deux référentiels quand la base
historique est joignable et pose `absente_ref_geo` ; `ReserveListView`,
`/api/me/reserve-options/` et le rattachement l'excluent. Sans la connexion `legacy`,
le marquage est laissé tel quel : « présente » n'est pas une conclusion qu'on peut
tirer d'une base absente.

Ce que la synchronisation ne fait pas encore : mettre à jour l'attribut
`nom_organisme` du groupe Keycloak d'un organisme renommé. Le rapport le signale.
Appeler `ensure_organisme_group` pour chacun créerait des groupes pour des centaines
d'organismes sans membre.

### Workflow d'inscription (le cœur métier)

`inscriptions/services/workflows.py` orchestre une validation en deux étages :

1. `RegisterView` crée une `RegistrationRequest` (`status=pending_super`). Le mot de passe choisi
   est chiffré en base (`password_cipher`, Fernet dérivé de `SECRET_KEY` — voir `crypto_util.py`)
   car le compte Keycloak n'existe pas encore.
2. **Super-admin** approuve (`super_admin_approve`) → création de l'utilisateur Keycloak,
   rattachement organisme/réserves (`services/provisioning.py`), passage à `pending_apps`.
3. **Admins applicatifs** décident item par item (`AccessRequestItem`, `app_admin_decide_item`) →
   ajout/retrait du groupe `/applications/<slug>`.
4. Quand tous les items sont tranchés, `_finalize_registration_if_done` **supprime** la
   `RegistrationRequest` (et ses items en cascade) : l'état final vit dans Keycloak. Ne pas
   compter sur ces tables pour un historique — seul `AuditLog` en garde la trace.

Les demandes d'accès ultérieures d'un utilisateur déjà inscrit réutilisent `AccessRequestItem`
avec `origin=additional` (`create_additional_access_request`), sans `RegistrationRequest`.

Chaque transition émet notification in-app (`services/notifications.py`) + e-mail
(`services/mail.py` avec `services/email_templates.py`) et une trace `AuditLog`.

Une exception : prévenir les référents d'une réserve qu'un membre vient de la
rejoindre (`reserve_notifications.notify_referents_new_member`, appelée à l'inscription
validée, à l'ajout par un admin et à l'ajout par soi-même) est **coupé par défaut**
via `RESERVE_NEW_MEMBER_NOTIFY_ENABLED`. Pendant la bascule, chaque compte repris de
la base historique rejoint ses réserves : le référent d'une réserve très peuplée
recevrait la pile d'un coup. Le garde est posé en tête de la fonction, avant toute
résolution, pour qu'aucun appel Keycloak ne parte pour une notification qui ne sera
pas envoyée. À rallumer une fois le parcours éprouvé.

### Route de contact mutualisée

`POST /api/contact/` sert le formulaire « Contacter le support » de **toutes** les applications
RNF (celles qui utilisent encore le socle `home-rnf` comme celle-ci, détachée). Chaque application déclare dans son
`app.config.ts` l'URL de la route et la boîte support visée :

```ts
"contact": { "apiUrl": "https://…/api/contact/", "recipientEmail": "support@…" }
```

Le destinataire transite par le client mais est validé contre `CONTACT_ALLOWED_RECIPIENTS`
(`.env`) : une adresse hors liste est refusée. Sans ce garde-fou la route serait un relais
SMTP ouvert depuis le domaine RNF. Liste vide = route désactivée (503). La route est publique
(le lien s'affiche sans session), limitée en débit (`ScopedRateThrottle`, scope `contact`,
`CONTACT_THROTTLE_RATE`) et protégée par un champ piège `website`.

Le mail est en **texte brut** (le destinataire est une file de tickets, pas un lecteur) et
porte `X-Zammad-Customer-Email` avec l'adresse de l'usager. Sans cet en-tête Zammad rattache
tous les tickets au `DEFAULT_FROM_EMAIL`, puisqu'il identifie le client par le `From`.
**Zammad n'honore les en-têtes `X-Zammad-*` que sur un canal e-mail déclaré « trusted »** :
sans ce réglage côté Zammad, l'en-tête est ignoré et seul le `Reply-To` permet de joindre
l'usager. Un canal « trusted » accepte ces en-têtes de *tout* expéditeur — préférer une
adresse d'arrivée dédiée à la plateforme plutôt que la boîte support publique.

Deux conséquences pour l'accueil d'une nouvelle application : son origine doit figurer dans
`CORS_ALLOWED_ORIGINS`, et son intercepteur HTTP doit traiter `/contact` comme public (sinon
les visiteurs anonymes sont bloqués avant l'appel). `ContactService` retombe sur le `mailto:`
historique tant qu'une application n'a pas renseigné `apiUrl`.

### Découpage backend

- `views.py` (~1750 lignes) : toutes les vues DRF, montées à plat dans `inscriptions/urls.py`
  (préfixe `/api/`). Trois familles de routes : publiques (`register`, `organismes`, `applications`,
  `auth/*`), `me/*` (utilisateur connecté), `admin/*` (super-admin ou admin applicatif).
- `services/` : toute la logique métier — y ajouter le code plutôt que dans les vues.
  `application_access.py` et `application_admins.py` gèrent l'appartenance aux groupes applicatifs,
  `user_organisme.py` la résolution organisme/réserves, `legacy_user_migration.py` l'import UsersHub.
- `user_identity.py` : `UserInfo` + résolution `sub` ↔ e-mail via l'Admin API. Utiliser ces
  helpers plutôt que de requêter Keycloak directement dans une vue.

### Flux d'authentification frontend

1. `AuthService` (`core/auth`) lit `GET /api/auth/keycloak-config/` — le `.env` Django est
   la source de vérité ; `environment.ts` n'est qu'un repli réseau. La réponse est mise en cache dans
   `sessionStorage` (clé `keycloak_public_config`) : la vider après changement d'URL Keycloak.
2. Redirection Authorization Code vers Keycloak → retour sur `/auth/callback`
   (`AuthCallbackComponent`) → échange du code via `POST /api/auth/token/` (le backend fait
   l'échange, le secret client ne transite pas par le navigateur).
3. Tokens en `localStorage`. `MyCustomInterceptor` (`services/http.interceptor.ts`) ajoute le
   Bearer, appelle `ensureFreshToken()` (refresh via `POST /api/auth/refresh/`) et laisse passer
   sans session les endpoints publics listés dans `isPublicApiRequest`. Il re-entre aussi dans la
   zone Angular (`runInZone`) car HttpClient utilise `fetch`.
4. `GET /api/me/` renvoie l'état consolidé (profil, organisme, réserves, `is_super_admin`,
   `is_app_admin`, compteur de notifications) ; `AuthService` en garde un snapshot.

Les messages transitoires passent par `ToastService` (`core/services/toast.service.ts`), qui ouvre
un `MatSnackBar` rempli par `ToastComponent`. Ses quatre méthodes (`success`, `error`, `warning`,
`info`) prennent le message puis un titre optionnel. La couleur vient des classes
`rnf-toast--<niveau>` définies dans `src/styles/toast.scss` : elles ne font que poser les tokens
`--mat-snack-bar-*` sur le conteneur Material, sans cibler ses classes internes.

Côté Angular : NgModules classiques (pas de standalone), `app.module.ts` déclare tout,
`api.service.ts` centralise les appels HTTP, `admin-dashboard.component.ts` (~1550 lignes) porte
l'ensemble de l'interface d'administration par onglets.

## Conventions

- Le code, les commentaires, les messages utilisateur et les commits sont **en français**.
- Ne pas introduire de modèle utilisateur Django ni dupliquer en base une information dont
  Keycloak est la source de vérité.
- Les erreurs Keycloak sont journalisées côté Django avec leur cause interne mais renvoyées au
  client sous forme générique (`KeycloakAdminError` → message neutre).
- `DEFAULT_PERMISSION_CLASSES` vaut `IsKeycloakAuthenticated` : **toute nouvelle vue exige un JWT
  par défaut**. Une vue réellement publique déclare explicitement `authentication_classes = []` et
  `permission_classes = []`.
- `db.sqlite3` n'est plus versionné : c'est le repli local quand `DATABASE_URL` est absent,
  la production utilise PostgreSQL.
- Toute erreur réseau vers Keycloak doit ressortir en `KeycloakAdminError` (le client
  l'enveloppe dans `_send`) : c'est ce qui permet aux appelants de dégrader gracieusement
  plutôt que de renvoyer une 500.
