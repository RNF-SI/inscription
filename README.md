# inscription

Plateforme d'inscription au SI de RNF, reliée à Keycloak.

## Architecture

| Composant | Rôle | Emplacement |
|-----------|------|-------------|
| **Frontend** | SPA Angular 22 | `frontend/` → servi en statique (ex. `https://plateformes.reserves-naturelles.org`) |
| **Backend** | API Django REST sous `/api` | `inscription_backend/` → WSGI (ex. Gunicorn) |
| **Keycloak** | Authentification, groupes, rôles | Realm dédié (ex. `rnf` sur `https://auth.reserves-naturelles.org`) |
| **PostgreSQL** | Données métier (inscriptions, catalogue, notifications) | `DATABASE_URL` |
| **PostgreSQL legacy** *(optionnel)* | Ancienne base UsersHub pour import | `LEGACY_DATABASE_URL` |

Le frontend récupère la config Keycloak via `GET /api/auth/keycloak-config/` (source de vérité : `.env` Django). Les valeurs dans `environment.prod.ts` ne servent qu'en repli si cet appel échoue.

---

## Prérequis

- Python 3.11+ et un environnement virtuel
- **Node.js 22.22+** (voir `frontend/.nvmrc`) et npm — requis pour Angular 22
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
nvm use          # Node 22 (fichier .nvmrc)
npm ci
```

Vérifier `src/environments/environment.prod.ts` (URL API, repli Keycloak et
mesure d'audience) :

```typescript
apiUrl: 'https://plateformes.reserves-naturelles.org/api',
keycloakUrl: 'https://auth.reserves-naturelles.org',
keycloakRealm: 'rnf',
keycloakClientId: 'inscription-spa',
matomoUrl: 'https://matomo.reserves-naturelles.org',
matomoSiteId: '12',   // site « Plateformes RNF » dans l'instance Matomo
```

Build production :

```bash
npm run build
# Artefacts : frontend/dist/inscription/
```

Déployer le contenu de `dist/inscription/` sur le serveur web.  
Configurer le fallback SPA : toutes les routes non-API renvoient `index.html`.

### Mesure d'audience

La fréquentation est mesurée par le Matomo de Réserves naturelles de France
(`https://matomo.reserves-naturelles.org`, la même instance que la vitrine
Cicada), piloté par
[`services/matomo.service.ts`](frontend/src/app/services/matomo.service.ts).

Le site y porte le numéro **12**. Vérifier que l'anonymisation des adresses IP
reste active côté instance (Administration → Confidentialité) : c'est le seul
réglage que l'application ne peut pas imposer, et c'est lui qui justifie
l'absence de bandeau de consentement. Vider `matomoSiteId` désactive
entièrement la mesure.

Le traqueur est configuré **sans cookie** (`disableCookies`) et respecte « Do
Not Track » : l'application reste ainsi exemptée de bandeau de consentement.
Aucune donnée de compte n'est transmise (pas de `setUserId`), et seul le chemin
des pages part vers Matomo — jamais la chaîne de requête, qui porte le code
d'autorisation OIDC sur `/auth/callback` et le jeton de réinitialisation sur
`/nouveau-mot-de-passe`.

L'application étant monopage, les pages vues sont signalées à chaque navigation
du routeur, sous le `title` déclaré sur la route. Rien n'est compté en
développement — `matomoUrl` y vaut `null`. Pour vérifier le câblage en local,
lui donner temporairement une valeur dans `src/environments/environment.ts` et
lire `window._paq` dans la console.

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

> Procédure complète, avec les prérequis bloquants, les garde-fous des scripts d'import
> et le rattrapage des identifiants : `inscription_backend/docs/runbook-cutover.txt`.
> Ce qui suit n'en est que le squelette.

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
nvm use          # Node 22
npm install
npm start   # http://localhost:4200
```

Tests backend : voir `inscription_backend/inscriptions/tests/README.md`.

Runbook cutover détaillé : `inscription_backend/docs/runbook-cutover.txt`.

---

## 8. Inventaire des dépendances (SBOM) et suivi des vulnérabilités

Les dépendances des deux composants déployés sont inventoriées au format CycloneDX
et envoyées à l'instance Dependency-Track de RNF
(`https://dependencytrack.reserves-naturelles.org`), qui les rapproche des CVE
publiées.

| Projet Dependency-Track | Source |
|---|---|
| `inscription-backend` | `inscription_backend/requirements.txt` |
| `inscription-frontend` | `frontend/package-lock.json` |

L'ancien backend Flask (`backend/`) est **hors périmètre** : il n'est conservé que
pour rollback et sera supprimé, ses CVE ne seraient que du bruit.

### Régénérer à la main

```bash
./scripts/generate-sbom.sh                # → sbom/*.cdx.json
./scripts/generate-sbom.sh --avec-dev     # inclut les dépendances npm de dev
./scripts/generate-sbom.sh --envoi        # génère puis envoie
```

L'envoi a besoin d'une clé d'API, lue dans `~/.config/dependency-track/api.key`
(ou dans `DT_API_KEY`). À renseigner une fois, pour tous les dépôts :

```bash
mkdir -p -m 700 ~/.config/dependency-track && install -m 600 /dev/null ~/.config/dependency-track/api.key && nano ~/.config/dependency-track/api.key
```

### Les deux notions de version, qu'on confond vite

| Variable | Défaut | Rôle |
|---|---|---|
| `DT_VERSION` | `prod` | version des projets Dependency-Track — **fixe**, c'est l'environnement déployé |
| `APP_VERSION` | dernier tag Git | version applicative inscrite dans les SBOM |

`DT_VERSION` reste fixe délibérément : une version de projet par release créerait
deux projets neufs à chaque publication, à re-tagger et re-rattacher à la main. Le
numéro de release reste tracé par le composant racine du SBOM.

### Pourquoi les plages de `requirements.txt` sont résolues avant

`requirements.txt` déclare des plages (`Django>=4.2,<5.1`), et `cyclonedx-py` ne
résout rien : il produirait des composants **sans version**, que Dependency-Track ne
peut rapprocher d'aucune CVE — le projet s'afficherait vert tout en étant aveugle.
Le script résout donc les plages d'abord, sans rien installer
(`pip install --dry-run --report`), ce qui donne en prime les dépendances
transitives : 19 paquets versionnés au lieu de 11 sans version.

Conséquence : **le Python qui exécute le script doit être celui de production**.
Une autre version mineure peut résoudre un arbre différent, et l'inventaire
décrirait alors du code que personne ne déploie. C'est la raison du
`python-version` figé dans `.github/workflows/sbom.yml`.

### Automatisation

`.github/workflows/sbom.yml` génère et envoie à chaque **release publiée** — pas à
chaque push, on inventorie ce qui est publié. Il demande deux secrets de dépôt :

```bash
gh secret set DT_URL --repo <owner/repo> --body "https://dependencytrack.reserves-naturelles.org"
```

```bash
gh secret set DT_API_KEY --repo <owner/repo>
```

La seconde forme demande la valeur de façon interactive : la clé ne transite ni par
l'historique du shell ni par un fichier du dépôt.
