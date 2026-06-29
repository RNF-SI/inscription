# Tests — inscription_backend
#
# Tests unitaires (58 tests, sans Keycloak réel) :
#   DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test inscriptions.tests
#
# En dev local : mettre KEYCLOAK_REALM=inscription-test (ou test) dans .env
# avec les clients/secrets de ce realm. Pas besoin de .env.test séparé.
#
# Tests d'intégration Keycloak (2 tests, touchent le realm .env) :
#   export KEYCLOAK_TEST_INTEGRATION=1
#   DJANGO_SETTINGS_MODULE=config.settings python manage.py test inscriptions.tests.test_keycloak_integration
#
# Les tests d'intégration refusent si KEYCLOAK_REALM est si-rnf, rnf, master, etc.
#
# Configuration Keycloak requise (realm de test, ex. inscription-test) :
#   Client inscription-admin — Access type: confidential, Service accounts enabled: ON
#   Onglet Service account roles → Client roles → realm-management :
#     view-groups, manage-groups, view-users, manage-users
#   (query-groups / query-users optionnels mais utiles pour la recherche utilisateurs)
#   Le secret doit correspondre à KEYCLOAK_ADMIN_CLIENT_SECRET dans .env.
