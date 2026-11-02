export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api',
  /** Repli si GET /api/auth/keycloak-config/ échoue (réseau) — la source de vérité est le .env Django. */
  keycloakUrl: 'http://localhost:8080',
  keycloakRealm: 'master',
  keycloakClientId: 'inscription-spa',
};
