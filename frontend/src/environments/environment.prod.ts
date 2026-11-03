export const environment = {
  production: true,
  apiUrl: 'https://plateformes.reserves-naturelles.org/api',
  /** Repli si GET /api/auth/keycloak-config/ échoue (réseau) — la source de vérité est le .env Django. */
  keycloakUrl: 'https://keycloak.reserves-naturelles.org',
  keycloakRealm: 'si-rnf',
  keycloakClientId: 'inscription-spa',
};
