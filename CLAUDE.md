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

`frontend/src/app/home-rnf/` est un **sous-module git** (`RNF-SI/home-rnf`) partagé entre les
applications RNF : il fournit le layout (`NavHomeComponent`), les guards (`AuthGuard`, `AdminGuard`)
et surtout `AuthService` (flux OIDC complet). Les modifications qui y sont faites concernent tous
les projets RNF — les committer et pousser séparément dans le sous-module.

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

Autres commandes de gestion : `promote_super --email=…`, `import_application_images`,
`migrate_legacy`, `migrate_legacy_users_to_keycloak` (voir README.md §4 — destructif, `--dry-run` d'abord).

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
- Frontend : `src/environments/environment{,.prod}.ts` (apiUrl + repli Keycloak) et
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

1. `AuthService` (sous-module `home-rnf`) lit `GET /api/auth/keycloak-config/` — le `.env` Django est
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

Côté Angular : NgModules classiques (pas de standalone), `app.module.ts` déclare tout,
`api.service.ts` centralise les appels HTTP, `admin-dashboard.component.ts` (~1550 lignes) porte
l'ensemble de l'interface d'administration par onglets.

## Conventions

- Le code, les commentaires, les messages utilisateur et les commits sont **en français**.
- Ne pas introduire de modèle utilisateur Django ni dupliquer en base une information dont
  Keycloak est la source de vérité.
- Les erreurs Keycloak sont journalisées côté Django avec leur cause interne mais renvoyées au
  client sous forme générique (`KeycloakAdminError` → message neutre).
- `DEFAULT_PERMISSION_CLASSES` vaut `AllowAny` : **toute nouvelle vue est publique par défaut**.
  Déclarer explicitement `permission_classes` (les vues `admin/*` le font) ou, pour les vues
  `me/*` et `notifications/*`, garder la garde manuelle `require_keycloak_user(request)` → 401.
- `db.sqlite3` n'est plus versionné : c'est le repli local quand `DATABASE_URL` est absent,
  la production utilise PostgreSQL.
- Toute erreur réseau vers Keycloak doit ressortir en `KeycloakAdminError` (le client
  l'enveloppe dans `_send`) : c'est ce qui permet aux appelants de dégrader gracieusement
  plutôt que de renvoyer une 500.
