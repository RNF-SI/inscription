# inscription

Plateforme d'inscription au SI de RNF, reliée à Keycloak.

## Architecture

| Composant | Rôle | Emplacement |
|-----------|------|-------------|
| **Frontend** | SPA Angular 15 | `frontend/` → servi en statique (ex. `https://plateformes.reserves-naturelles.org`) |
| **Backend** | API Django REST sous `/api` | `inscription_backend/` → WSGI (ex. Gunicorn) |
| **Keycloak** | Authentification, groupes, rôles | Realm dédié (ex. `rnf` sur `https://auth.reserves-naturelles.org`) |
| **PostgreSQL** | Données métier (inscriptions, catalogue, notifications) | `DATABASE_URL` |
| **PostgreSQL legacy** *(optionnel)* | Ancienne base UsersHub pour import | `LEGACY_DATABASE_URL` |

Le frontend récupère la config Keycloak via `GET /api/auth/keycloak-config/` (source de vérité : `.env` Django). Les valeurs dans `environment.prod.ts` ne servent qu'en repli si cet appel échoue.

---

## Prérequis

- Python 3.11+ et un environnement virtuel
- Node.js 18+ et npm (Angular CLI 15)
- PostgreSQL (production)
- Instance Keycloak accessible depuis le backend
- Reverse proxy (nginx ou équivalent) pour :
  - servir le build Angular ;
  - proxyfier `/api` vers Django ;
  - exposer `/media/application-images/` si besoin.

---

## 1. Configuration Keycloak

### Realm et clients

Créer ou utiliser un realm (ex. `rnf`).

**Client SPA `inscription-spa`** (frontend) :
- Type : **public** (Standard flow)
- Valid redirect URIs : `https://plateformes.reserves-naturelles.org/auth/callback` (+ URL de préprod si applicable)
- Web origins : origine du frontend
- PKCE recommandé

**Client de service `inscription-admin`** (backend — Admin API) :
- Type : **confidential**, **Service accounts enabled**
- Rôles du compte de service → `realm-management` :
  - `view-users`, `manage-users`
  - `view-groups`, `manage-groups`
  - (`query-users`, `query-groups` utiles pour la recherche)
- Secret → `KEYCLOAK_ADMIN_CLIENT_SECRET`

### Groupes et mappers

Structure attendue par l'application :

```
/organismes/<slug>          (attributs : id_organisme, nom_organisme, uuid_organisme)
/reserves/<code>
/reserves/<code>/referent
/applications/<slug>
/applications/<slug>/admin
/super-admin
```

Configurer un **mapper de groupes** sur le client SPA pour inclure les groupes dans le JWT (`groups` claim), ou s'assurer que le backend peut les charger via l'Admin API (fallback déjà implémenté).

### Variables alignées Keycloak ↔ backend

Copier `inscription_backend/.env.example` vers `.env` et renseigner au minimum :

```bash
DJANGO_SECRET_KEY=…
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=plateformes.reserves-naturelles.org
DATABASE_URL=postgres://USER:PASS@HOST:5432/inscription

CORS_ALLOWED_ORIGINS=https://plateformes.reserves-naturelles.org

KEYCLOAK_BASE_URL=https://auth.reserves-naturelles.org
KEYCLOAK_REALM=rnf
KEYCLOAK_ADMIN_CLIENT_ID=inscription-admin
KEYCLOAK_ADMIN_CLIENT_SECRET=…
KEYCLOAK_APP_CLIENT_ID=inscription-spa
KEYCLOAK_APP_CLIENT_SECRET=          # vide si client public
KEYCLOAK_SYNC_ENABLED=1

FRONTEND_PUBLIC_URL=https://plateformes.reserves-naturelles.org

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=…
EMAIL_PORT=587
EMAIL_USE_TLS=1
EMAIL_HOST_USER=…
EMAIL_HOST_PASSWORD=…
DEFAULT_FROM_EMAIL=noreply@reserves-naturelles.org
SUPERADMIN_NOTIFY_EMAILS=admin@reserves-naturelles.org

# Import legacy (cutover uniquement)
LEGACY_DATABASE_URL=postgres://USER:PASS@HOST:5432/usershub
```

> Ne pas mettre de commentaire en fin de ligne sur une variable — `django-environ` ne les ignore pas.

---

## 2. Déploiement backend

```bash
cd inscription_backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis éditer
```

### Base de données

```bash
python manage.py migrate
python manage.py seed_catalog
```

`seed_catalog` charge le catalogue des applications (idempotent).

### Import catalogue géographique legacy *(si cutover depuis UsersHub)*

```bash
# LEGACY_DATABASE_URL doit être défini
python manage.py migrate_legacy
```

Importe organismes, réserves et liens depuis les schémas `utilisateurs`, `ref_geo`, `complement_rnf`.

### Super-administrateur

Les droits admin globaux passent par le groupe Keycloak `/super-admin` :

```bash
python manage.py promote_super --email admin@example.org
```

### Vignettes applications

Par défaut : `inscription_backend/media/application-images/`.  
En production, on peut pointer vers un répertoire persistant :

```bash
APPLICATION_IMAGES_DIR=/var/lib/inscription/application-images
```

### Processus WSGI (exemple Gunicorn)

```bash
gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 3 \
  --timeout 120
```

Le reverse proxy doit router :
- `/api/*` → backend ;
- `/media/application-images/*` → backend (ou fichiers statiques nginx).

---

## 3. Déploiement frontend

```bash
cd frontend
npm ci
```

Vérifier `src/environments/environment.prod.ts` (URL API et repli Keycloak) :

```typescript
apiUrl: 'https://plateformes.reserves-naturelles.org/api',
keycloakUrl: 'https://auth.reserves-naturelles.org',
keycloakRealm: 'rnf',
keycloakClientId: 'inscription-spa',
```

Build production :

```bash
npm run build
# Artefacts : frontend/dist/inscription/
```

Déployer le contenu de `dist/inscription/` sur le serveur web.  
Configurer le fallback SPA : toutes les routes non-API renvoient `index.html`.

---

## 4. Migration des utilisateurs legacy → Keycloak

À exécuter **sur un realm de test** d'abord (`inscription-test`), puis en production lors du cutover.

Prérequis : `LEGACY_DATABASE_URL`, `KEYCLOAK_SYNC_ENABLED=1`, `seed_catalog` exécuté.

```bash
# Simulation
python manage.py migrate_legacy_users_to_keycloak --dry-run --limit 20

# Lot de test (supprime les users KC du realm avant import)
python manage.py migrate_legacy_users_to_keycloak --clear --limit 20

# Migration complète
python manage.py migrate_legacy_users_to_keycloak --limit 0

# Comptes sans hash legacy → CSV des mots de passe générés
python manage.py migrate_legacy_users_to_keycloak --limit 0 \
  --password-report /tmp/comptes-sans-hash.csv
```

Comportement :
- **Mots de passe** : import des hash legacy (`pass_plus` bcrypt, sinon `pass` md5) — l'utilisateur garde son mot de passe.
- **Groupes** : création automatique des groupes organismes/réserves/applications et rattachement des utilisateurs.
- **Sécurité** : mot de passe commun désactivé par défaut ; `--allow-shared-password` uniquement en dernier recours.
- **Protection** : refus sur les realms de prod (`rnf`, `si-rnf`, …) sans `--force`.

---

## 5. Séquence de cutover (production)

1. Déployer le backend Django derrière `/api` (sans basculer le trafic utilisateur).
2. Exécuter `migrate`, `seed_catalog`, puis `migrate_legacy` si applicable.
3. Migrer les utilisateurs vers Keycloak (`migrate_legacy_users_to_keycloak`).
4. Promouvoir au moins un super-admin : `promote_super --email …`.
5. Déployer le build frontend.
6. Vérifier en préprod / smoke test :
   - `GET /api/auth/keycloak-config/`
   - connexion OIDC + callback `/auth/callback`
   - inscription test + validation admin
   - e-mails (SMTP)
7. Basculer le DNS / reverse-proxy vers la nouvelle stack.

### Rollback

- Rétablir le proxy `/api` vers l'ancien backend Flask.
- Conserver la nouvelle base PostgreSQL : aucune destruction automatique.
- Les utilisateurs déjà créés dans Keycloak restent — prévoir une stratégie si rollback partiel.

---

## 6. Vérifications post-déploiement

| Test | Attendu |
|------|---------|
| `GET /api/auth/keycloak-config/` | URL Keycloak, realm, clientId cohérents |
| Connexion utilisateur migré | Ancien mot de passe accepté |
| Mon compte | Organisme et réserves visibles |
| Admin inscriptions | Super-admin voit le tableau de bord |
| Notification badge | Compteur non-lus mis à jour |
| E-mail inscription | Reçu par l'utilisateur et les super-admins |

Pour diagnostiquer sans modifier Keycloak : `KEYCLOAK_SYNC_ENABLED=0`.

---

## 7. Développement local

```bash
# Backend
cd inscription_backend
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # KEYCLOAK_REALM=inscription-test recommandé
python manage.py migrate
python manage.py seed_catalog
python manage.py runserver

# Frontend (autre terminal)
cd frontend
npm install
npm start   # http://localhost:4200
```

Tests backend : voir `inscription_backend/inscriptions/tests/README.md`.

Runbook cutover détaillé : `inscription_backend/docs/runbook-cutover.txt`.
