import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ApiService } from 'src/app/services/api.service';
import { AuthService } from './auth-service.service';

/**
 * Les instantanés de session vivent dans localStorage et survivent à la disparition
 * des jetons. getCurrentUser() doit refuser de les croire sans session : sinon
 * l'accueil affiche les badges d'accès et les boutons « Demander l'accès » à un
 * visiteur anonyme, et le menu le croit connecté.
 */
describe('AuthService.getCurrentUser', () => {
  let service: AuthService;

  const instantane = JSON.stringify({
    profile: { username: 'residu', email: 'residu@example.invalid', first_name: 'R', last_name: 'esidu' },
    is_super_admin: false,
    is_app_admin: false,
  });

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: ApiService, useValue: {} }],
    });
    service = TestBed.inject(AuthService);
    localStorage.clear();
  });

  afterEach(() => localStorage.clear());

  it('renvoie null quand aucun jeton n’est présent', () => {
    localStorage.setItem('me_snapshot', instantane);
    expect(service.getCurrentUser()).toBeNull();
  });

  it('purge les instantanés résiduels plutôt que de les recopier', () => {
    localStorage.setItem('me_snapshot', instantane);
    localStorage.setItem('current_user', JSON.stringify({ login: 'residu' }));

    service.getCurrentUser();

    expect(localStorage.getItem('me_snapshot')).toBeNull();
    expect(localStorage.getItem('current_user')).toBeNull();
  });

  it('renvoie null quand le jeton de rafraîchissement est expiré', () => {
    localStorage.setItem('me_snapshot', instantane);
    localStorage.setItem('refresh_token', 'jeton');
    localStorage.setItem('refresh_expires_at', String(Date.now() - 60_000));
    expect(service.getCurrentUser()).toBeNull();
  });

  it('se fie à l’exp du jeton, pas à la durée annoncée', (done) => {
    // Keycloak peut renvoyer un jeton déjà périmé tout en annonçant expires_in=300.
    // Si le client croit la durée annoncée, il envoie un jeton que le serveur
    // rejette, et l'utilisateur se retrouve authentifié ici et inconnu de l'API.
    const expPasse = Math.floor(Date.now() / 1000) - 60;
    const charge = btoa(JSON.stringify({ exp: expPasse })).replace(/=+$/, '');
    const jeton = `entete.${charge}.signature`;

    const api = TestBed.inject(ApiService) as unknown as { exchangeCode: unknown };
    api.exchangeCode = () =>
      of({ access_token: jeton, refresh_token: 'r', expires_in: 300, refresh_expires_in: 1800 });

    service.handleOAuthCallback('un-code').subscribe(() => {
      expect(Number(localStorage.getItem('expires_at'))).toBe(expPasse * 1000);
      expect(service.isAccessTokenExpired()).toBeTrue();
      done();
    });
  });

  it('renvoie l’utilisateur tant que le rafraîchissement reste valide', () => {
    // L'expiration du jeton d'accès ne doit pas déconnecter : le rafraîchissement
    // prendra le relais au prochain appel protégé.
    localStorage.setItem('me_snapshot', instantane);
    localStorage.setItem('refresh_token', 'jeton');
    localStorage.setItem('refresh_expires_at', String(Date.now() + 600_000));

    const user = service.getCurrentUser();

    expect(user).toBeTruthy();
    expect(localStorage.getItem('current_user')).not.toBeNull();
  });
});
