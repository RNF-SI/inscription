import { Injectable, NgZone } from '@angular/core';
import {
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest,
} from '@angular/common/http';
import { Observable, of, throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { AuthService } from '../home-rnf/services/auth-service.service';

@Injectable()
export class MyCustomInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService, private ngZone: NgZone) {}

  /** Réponses HttpClient (fetch) hors zone.js → forcer la détection de changements. */
  private runInZone<T>(source: Observable<T>): Observable<T> {
    return new Observable((observer) => {
      const subscription = source.subscribe({
        next: (value) => this.ngZone.run(() => observer.next(value)),
        error: (error) => this.ngZone.run(() => observer.error(error)),
        complete: () => this.ngZone.run(() => observer.complete()),
      });
      return () => subscription.unsubscribe();
    });
  }

  private unauthorizedError(): { status: number } {
    return { status: 401 };
  }

  /** Endpoints accessibles sans session (AllowAny côté API). */
  private isPublicApiRequest(url: string): boolean {
    const path = url.split('?')[0];
    if (path.includes('/auth/keycloak-config')) {
      return true;
    }
    if (path.endsWith('/register') || path.endsWith('/register/')) {
      return true;
    }
    if (path.endsWith('/organismes') || path.endsWith('/organismes/')) {
      return true;
    }
    if (/\/organisme\/\d+\/?$/.test(path)) {
      return true;
    }
    if ((path.endsWith('/applications') || path.endsWith('/applications/')) && !path.includes('/admin/')) {
      return true;
    }
    return false;
  }

  intercept(request: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    const isAuthEndpoint =
      request.url.includes('/auth/token/') ||
      request.url.includes('/auth/refresh/') ||
      request.url.includes('/auth/keycloak-config/');

    const addBearer = (req: HttpRequest<unknown>): HttpRequest<unknown> => {
      const access = localStorage.getItem('access_token');
      const idToken = localStorage.getItem('tk_id_token');
      // L'API Django valide l'access_token ; l'id_token peut être expiré plus tôt.
      const bearer = access || idToken;
      let r = req.clone({ withCredentials: true });
      if (bearer) {
        r = r.clone({ headers: r.headers.set('Authorization', 'Bearer ' + bearer) });
      }
      return r;
    };

    if (isAuthEndpoint || this.isPublicApiRequest(request.url)) {
      return this.runInZone(next.handle(addBearer(request)));
    }

    const tokenRefresh$ = this.authService.ensureFreshToken();

    return this.runInZone(
      tokenRefresh$.pipe(
        switchMap((ok) => {
          if (!ok) {
            return throwError(() => this.unauthorizedError());
          }
          return next.handle(addBearer(request));
        }),
        catchError((err: unknown) => {
          const status = (err as { status?: number })?.status;
          if (status === 401 && this.authService.hasRefreshTokenValid()) {
            return this.authService.refreshAccessToken().pipe(
              switchMap((refreshed) => {
                if (!refreshed) {
                  return throwError(() => err);
                }
                return next.handle(addBearer(request));
              }),
            );
          }
          return throwError(() => err);
        }),
      ),
    );
  }
}
