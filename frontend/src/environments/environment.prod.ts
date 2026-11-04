export const environment = {
  production: true,
  apiUrl: 'https://plateformes.reserves-naturelles.org/api',
  /** Repli si GET /api/auth/keycloak-config/ échoue (réseau) — la source de vérité est le .env Django. */
  keycloakUrl: 'https://keycloak.reserves-naturelles.org',
  keycloakRealm: 'si-rnf',
  keycloakClientId: 'inscription-spa',

  /**
   * Instance Matomo de Réserves naturelles de France, qui héberge la mesure
   * d'audience des applications du SI. Sans slash final : le service y ajoute
   * lui-même `/matomo.php` et `/matomo.js`.
   */
  matomoUrl: 'https://matomo.reserves-naturelles.org' as string | null,

  /**
   * Identifiant du site « Plateformes RNF » dans cette instance. Le vider
   * désactive la mesure, plutôt que de compter les visites sur le site d'une
   * autre application.
   */
  matomoSiteId: '12',
};
