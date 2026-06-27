Backend Django — plateforme d’inscription
=========================================

Installation
------------
  cd inscription_backend
  python3 -m venv .venv
  . .venv/bin/activate
  pip install -r requirements.txt
  cp .env.example .env   # adapter les variables

Lancer le serveur API
---------------------
  python manage.py migrate
  python manage.py seed_catalog
  python manage.py import_application_images   # une fois : copie les PNG depuis assets/ vers media/
  python manage.py runserver 0.0.0.0:8000

Les routes HTTP sont sous le préfixe /api/ (voir config/urls.py).

Commandes utiles
----------------
  python manage.py migrate_legacy          # si LEGACY_DATABASE_URL (PostgreSQL legacy)
  python manage.py import_application_images  # vignettes catalogue → media/application-images/
  python manage.py promote_super --email=vous@exemple.org

Documentation
---------------
  docs/keycloak-v1-spec.txt — conventions groupes / ensure_group_path
  docs/runbook-cutover.txt — cutover et rollback

Vignettes applications
----------------------
  Stockées dans media/application-images/ (hors git). Servies sur GET /media/application-images/<fichier>.
  En production, configurer nginx pour servir ce dossier (alias) ou laisser Django le faire.
  Les assets Angular (embleme, bannière, fond) restent dans frontend/src/assets/images/.
