export const environment = {
  production: true,
  apiUrl: 'https://plateformes.reserves-naturelles.org/api',
  keycloakUrl: 'https://auth.reserves-naturelles.org',
  keycloakRealm: 'rnf',
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
