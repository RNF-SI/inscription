export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api',
  /** Repli si GET /api/auth/keycloak-config/ échoue (réseau) — la source de vérité est le .env Django. */
  keycloakUrl: 'http://localhost:8080',
  keycloakRealm: 'master',
  keycloakClientId: 'inscription-spa',

  /**
   * Pas de mesure d'audience en développement : les allers-retours de
   * `npm start` n'ont rien à faire dans les statistiques de production, et
   * `null` suffit à désactiver entièrement le traqueur (cf.
   * `services/matomo.service.ts`). Pour vérifier le câblage en local, lui
   * donner temporairement l'URL de l'instance et lire `window._paq` dans la
   * console.
   */
  matomoUrl: null as string | null,
  matomoSiteId: '',
};
