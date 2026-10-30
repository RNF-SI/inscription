import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, finalize, map, shareReplay, tap } from 'rxjs/operators';
import { environment } from 'src/environments/environment';
import { ApiService, KeycloakPublicConfig, MeResponse } from 'src/app/services/api.service';

import { User } from './user.model';

const LS_ACCESS = 'access_token';
const LS_ID = 'tk_id_token';
const LS_EXPIRES = 'expires_at';
const LS_REFRESH = 'refresh_token';
const LS_REFRESH_EXPIRES = 'refresh_expires_at';
const LS_CURRENT_USER = 'current_user';
const LS_ME = 'me_snapshot';
const LS_KC_CONFIG = 'keycloak_public_config';

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  public loginError = false;
  public isLoading = false;

  private kcResolved: KeycloakPublicConfig | null = null;
  private restoreInFlight: Observable<boolean> | null = null;

  constructor(private api: ApiService) {}

  /** Config Keycloak : priorité au backend (.env), puis cache session, puis environment.ts. */
  private defaultKc(): KeycloakPublicConfig {
    return {
      keycloakUrl: environment.keycloakUrl.replace(/\/$/, ''),
      realm: environment.keycloakRealm,
      clientId: environment.keycloakClientId,
    };
  }

  private mergeKc(partial: Partial<KeycloakPublicConfig> | null | undefined): KeycloakPublicConfig {
    const d = this.defaultKc();
    if (!partial) {
      return d;
    }
    return {
      keycloakUrl: (partial.keycloakUrl || d.keycloakUrl).replace(/\/$/, ''),
      realm: partial.realm || d.realm,
      clientId: partial.clientId || d.clientId,
    };
  }

  getKeycloakConfig$(): Observable<KeycloakPublicConfig> {
    if (this.kcResolved) {
      return of(this.kcResolved);
    }
    try {
      const raw = sessionStorage.getItem(LS_KC_CONFIG);
      if (raw) {
        this.kcResolved = this.mergeKc(JSON.parse(raw) as KeycloakPublicConfig);
        return of(this.kcResolved);
      }
    } catch {
      sessionStorage.removeItem(LS_KC_CONFIG);
    }
    return this.api.getKeycloakPublicConfig().pipe(
      tap((cfg) => {
        this.kcResolved = this.mergeKc(cfg);
        sessionStorage.setItem(LS_KC_CONFIG, JSON.stringify(this.kcResolved));
      }),
      catchError(() => {
        this.kcResolved = this.defaultKc();
        return of(this.kcResolved);
      })
    );
  }

  /** À appeler après un changement d’URL Keycloak côté serveur. */
  clearKeycloakConfigCache(): void {
    this.kcResolved = null;
    sessionStorage.removeItem(LS_KC_CONFIG);
  }

  /**
   * Évite la boucle OIDC : ne pas renvoyer vers /login (LazyDialogLoader) ni /auth/callback ni /logout.
   */
  normalizeReturnUrl(returnUrl?: string | null): string | null {
    if (returnUrl == null || !String(returnUrl).trim()) {
      return null;
    }
    const path = String(returnUrl).split('?')[0].split('#')[0];
    const blocked = ['/login', '/logout', '/auth/callback'];
    if (blocked.some((b) => path === b || path.startsWith(`${b}/`))) {
      return null;
    }
    if (path === '/' || path === '') {
      return null;
    }
    return returnUrl;
  }

  /** Cible après callback : toujours une route sûre. */
  safePostLoginTarget(stored: string | null): string {
    const n = this.normalizeReturnUrl(stored);
    return n || '/';
  }

  beginKeycloakLogin(returnUrl?: string): void {
    const ru = `${window.location.origin}/auth/callback`;
    const safe = this.normalizeReturnUrl(returnUrl);
    if (safe) {
      sessionStorage.setItem('post_login_redirect', safe);
    } else {
      sessionStorage.removeItem('post_login_redirect');
    }
    this.getKeycloakConfig$().subscribe((kc) => {
      const params = new URLSearchParams({
        client_id: kc.clientId,
        redirect_uri: ru,
        response_type: 'code',
        scope: 'openid profile email',
      });
      window.location.href = `${kc.keycloakUrl}/realms/${kc.realm}/protocol/openid-connect/auth?${params.toString()}`;
    });
  }

  handleOAuthCallback(code: string): Observable<unknown> {
    const redirectUri = `${window.location.origin}/auth/callback`;
    return this.api.exchangeCode(code, redirectUri).pipe(
      tap((tokens: any) => {
        const access = tokens['access_token'] as string;
        const idTok = tokens['id_token'] as string;
        const refresh = tokens['refresh_token'] as string;
        const exp = tokens['expires_in'] ? String(Date.now() + Number(tokens['expires_in']) * 1000) : '';
        const refreshExp = tokens['refresh_expires_in']
          ? String(Date.now() + Number(tokens['refresh_expires_in']) * 1000)
          : '';
        if (access) {
          localStorage.setItem(LS_ACCESS, access);
        }
        if (idTok) {
          localStorage.setItem(LS_ID, idTok);
        }
        if (refresh) {
          localStorage.setItem(LS_REFRESH, refresh);
        }
        if (exp) {
          localStorage.setItem(LS_EXPIRES, exp);
        }
        if (refreshExp) {
          localStorage.setItem(LS_REFRESH_EXPIRES, refreshExp);
        }
      }),
      map(() => true)
    );
  }

  private parseMs(key: string): number {
    const raw = localStorage.getItem(key);
    if (!raw) {
      return 0;
    }
    const n = Number(raw);
    return Number.isFinite(n) ? n : 0;
  }

  isAccessTokenExpired(skewSec = 20): boolean {
    const token = localStorage.getItem(LS_ACCESS);
    if (!token) {
      return true;
    }
    const exp = this.parseMs(LS_EXPIRES);
    if (!exp) {
      return true;
    }
    return Date.now() + skewSec * 1000 >= exp;
  }

  hasRefreshTokenValid(skewSec = 20): boolean {
    const token = localStorage.getItem(LS_REFRESH);
    if (!token) {
      return false;
    }
    const exp = this.parseMs(LS_REFRESH_EXPIRES);
    if (!exp) {
      // Si l'expiration n'est pas fournie, on tente quand même un refresh.
      return true;
    }
    return Date.now() + skewSec * 1000 < exp;
  }

  refreshAccessToken(): Observable<boolean> {
    const refresh = localStorage.getItem(LS_REFRESH);
    if (!refresh || !this.hasRefreshTokenValid()) {
      this.cleanLocalStorage();
      return of(false);
    }
    return this.api.refreshToken(refresh).pipe(
      tap((tokens: any) => {
        const access = tokens['access_token'] as string;
        const idTok = tokens['id_token'] as string;
        const newRefresh = tokens['refresh_token'] as string;
        const exp = tokens['expires_in'] ? String(Date.now() + Number(tokens['expires_in']) * 1000) : '';
        const refreshExp = tokens['refresh_expires_in']
          ? String(Date.now() + Number(tokens['refresh_expires_in']) * 1000)
          : '';
        if (access) {
          localStorage.setItem(LS_ACCESS, access);
        }
        if (idTok) {
          localStorage.setItem(LS_ID, idTok);
        }
        if (newRefresh) {
          localStorage.setItem(LS_REFRESH, newRefresh);
        }
        if (exp) {
          localStorage.setItem(LS_EXPIRES, exp);
        }
        if (refreshExp) {
          localStorage.setItem(LS_REFRESH_EXPIRES, refreshExp);
        }
      }),
      map(() => true),
      catchError(() => {
        this.cleanLocalStorage();
        return of(false);
      })
    );
  }

  ensureFreshToken(): Observable<boolean> {
    if (!this.isAccessTokenExpired()) {
      return of(true);
    }
    return this.refreshAccessToken();
  }

  /** Restaure la session locale (refresh silencieux + profil) après un rechargement de page. */
  restoreSession(): Observable<boolean> {
    if (!this.restoreInFlight) {
      this.restoreInFlight = this.doRestoreSession().pipe(
        shareReplay(1),
        finalize(() => {
          this.restoreInFlight = null;
        })
      );
    }
    return this.restoreInFlight;
  }

  private doRestoreSession(): Observable<boolean> {
    const hasAccess = !!localStorage.getItem(LS_ACCESS);
    const hasRefresh = !!localStorage.getItem(LS_REFRESH);
    if (!hasAccess && !hasRefresh) {
      return of(false);
    }

    this.syncUserFromSnapshot();

    if (!this.isAccessTokenExpired()) {
      return of(true);
    }

    if (!this.hasRefreshTokenValid()) {
      this.cleanLocalStorage();
      return of(false);
    }

    return this.refreshAccessToken().pipe(
      tap((ok) => {
        if (ok) {
          this.syncUserFromSnapshot();
        }
      })
    );
  }

  private syncUserFromSnapshot(): void {
    if (localStorage.getItem(LS_CURRENT_USER)) {
      return;
    }
    const me = this.getMeSnapshot();
    if (me) {
      localStorage.setItem(LS_CURRENT_USER, JSON.stringify(this.mapMeToUser(me)));
    }
  }

  refreshMeFromApi(): Observable<MeResponse> {
    return this.api.getMe().pipe(
      tap((me) => {
        localStorage.setItem(LS_ME, JSON.stringify(me));
        const u = this.mapMeToUser(me);
        localStorage.setItem(LS_CURRENT_USER, JSON.stringify(u));
      })
    );
  }

  mapMeToUser(me: MeResponse): User {
    const p = me.profile;
    const u = new User(
      p.keycloak_sub,
      0,
      p.first_name || '',
      p.last_name || '',
      p.username || p.email
    );
    (u as any).email = p.email;
    (u as any).is_super_admin = p.is_super_admin;
    (u as any).is_app_admin = me.is_app_admin;
    return u;
  }

  getMeSnapshot(): MeResponse | null {
    const raw = localStorage.getItem(LS_ME);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as MeResponse;
    } catch {
      return null;
    }
  }

  updateMeSnapshotUnreadCount(count: number): void {
    const me = this.getMeSnapshot();
    if (!me) {
      return;
    }
    me.unread_notifications = Math.max(0, Number(count) || 0);
    localStorage.setItem(LS_ME, JSON.stringify(me));
  }

  setCurrentUser(user: any, token: any, expireDate: any) {
    localStorage.setItem(LS_CURRENT_USER, JSON.stringify(user));
    localStorage.setItem(LS_ID, token);
    localStorage.setItem(LS_EXPIRES, expireDate);
  }

  getCurrentUser(): any {
    // Les instantanés de localStorage survivent à la disparition des jetons : session
    // expirée, nettoyage partiel, ou onglet rouvert longtemps après. Sans ce garde,
    // l'interface croit l'utilisateur connecté — badges d'accès sur les applications,
    // menu du compte — alors qu'aucune session n'existe. On en profite pour purger le
    // résidu, sinon getCurrentUser() le recopierait dans `current_user` à chaque appel.
    if (!this.authenticated) {
      if (localStorage.getItem(LS_CURRENT_USER) || localStorage.getItem(LS_ME)) {
        this.cleanLocalStorage();
      }
      return null;
    }
    const currentUser = localStorage.getItem(LS_CURRENT_USER);
    if (currentUser) {
      return JSON.parse(currentUser);
    }
    const me = this.getMeSnapshot();
    if (me) {
      const u = this.mapMeToUser(me);
      localStorage.setItem(LS_CURRENT_USER, JSON.stringify(u));
      return u;
    }
    return null;
  }

  public get authenticated(): boolean {
    const hasAccess = !!localStorage.getItem(LS_ACCESS);
    const hasRefresh = !!localStorage.getItem(LS_REFRESH);
    if (!hasAccess && !hasRefresh) {
      return false;
    }
    if (this.hasRefreshTokenValid()) {
      return true;
    }
    return !this.isAccessTokenExpired();
  }

  signinUser(_identifiant: string, _password: string): Observable<any> {
    this.beginKeycloakLogin();
    return of(null);
  }

  loginOrPwdRecovery(_data: any): Observable<any> {
    this.getKeycloakConfig$().subscribe((kc) => {
      const reset = `${kc.keycloakUrl}/realms/${kc.realm}/login-actions/reset-credentials`;
      window.open(reset, '_blank');
    });
    return of(null);
  }

  logout(): void {
    const idToken = localStorage.getItem(LS_ID) || '';
    const ru = encodeURIComponent(window.location.origin + '/');
    this.cleanLocalStorage();
    this.getKeycloakConfig$().subscribe((kc) => {
      const params = new URLSearchParams();
      // Param OIDC moderne (Keycloak récent)
      params.set('post_logout_redirect_uri', decodeURIComponent(ru));
      // Compat anciens comportements Keycloak
      params.set('redirect_uri', decodeURIComponent(ru));
      if (idToken) {
        params.set('id_token_hint', idToken);
      }
      window.location.href = `${kc.keycloakUrl}/realms/${kc.realm}/protocol/openid-connect/logout?${params.toString()}`;
    });
  }

  private cleanLocalStorage() {
    localStorage.removeItem(LS_CURRENT_USER);
    localStorage.removeItem(LS_ID);
    localStorage.removeItem(LS_ACCESS);
    localStorage.removeItem(LS_EXPIRES);
    localStorage.removeItem(LS_REFRESH);
    localStorage.removeItem(LS_REFRESH_EXPIRES);
    localStorage.removeItem(LS_ME);
  }
}
