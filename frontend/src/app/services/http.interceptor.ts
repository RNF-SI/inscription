import { Observable, throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { Injectable } from '@angular/core';
import {
  HttpInterceptor,
  HttpRequest,
  HttpHandler,
  HttpEvent,
} from '@angular/common/http';
import { AuthService } from '../home-rnf/services/auth-service.service';

@Injectable()
export class MyCustomInterceptor implements HttpInterceptor {
  constructor(private authService: AuthService) {}

  private decodeJwtPayload(token: string | null): Record<string, unknown> | null {
    if (!token) {
      return null;
    }
    const parts = token.split('.');
    if (parts.length < 2 || !parts[1]) {
      return null;
    }
    try {
      const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
      return JSON.parse(atob(padded)) as Record<string, unknown>;
    } catch {
      return null;
    }
  }

  private tokenHasGroups(token: string | null): boolean {
    const payload = this.decodeJwtPayload(token);
    return Array.isArray(payload?.['groups']) && (payload?.['groups'] as unknown[]).length > 0;
  }

//   private handleError(error: any) {
//     let errTitle: string;
//     let errMsg: string;
//     let enableHtml: boolean = false;
//     if (error instanceof HttpErrorResponse) {
//       if ([401, 404].includes(error.status)) return;
//       if (error.status == 502) {
//         errTitle = 'Timeout';
//         errMsg = 'La requête n’a pas abouti dans le temps imparti';
//       } else if (
//         typeof error.error === 'object' &&
//         'name' in error.error &&
//         'description' in error.error
//       ) {
//         errTitle = error.error.name;
//         errMsg = error.error.description;
//         enableHtml = true;
//         if ('request_id' in error.error) {
//           errMsg += `<br><b>Requête :</b> ${error.error.request_id}`;
//         }
//       } else {
//         errTitle = error.name;
//         errMsg = error.message;
//       }
//     } else {
//       errTitle = 'Erreur';
//       errMsg = 'Une erreur inconnue est survenue.';
//     }
//     this._toastrService.error(errMsg, errTitle, {
//       disableTimeOut: true,
//       tapToDismiss: false,
//       closeButton: true,
//       easeTime: 0,
//       enableHtml: enableHtml,
//     });
//   }

  intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    const isAuthEndpoint =
      request.url.includes('/auth/token/') ||
      request.url.includes('/auth/refresh/') ||
      request.url.includes('/auth/keycloak-config/');

    const addBearer = (req: HttpRequest<any>): HttpRequest<any> => {
      const access = localStorage.getItem('access_token');
      const idToken = localStorage.getItem('tk_id_token');
      // Selon la config Keycloak, `groups` peut être dans access_token OU id_token.
      let bearer = idToken || access;
      if (this.tokenHasGroups(access)) {
        bearer = access;
      } else if (this.tokenHasGroups(idToken)) {
        bearer = idToken;
      }
      let r = req.clone({ withCredentials: true });
      if (bearer) {
        r = r.clone({ headers: r.headers.set('Authorization', 'Bearer ' + bearer) });
      }
      return r;
    };

    if (isAuthEndpoint) {
      return next.handle(addBearer(request));
    }

    return this.authService.ensureFreshToken().pipe(
      switchMap(() => next.handle(addBearer(request))),
      catchError((err: any) => {
        if (err?.status === 401 && this.authService.hasRefreshTokenValid()) {
          return this.authService.refreshAccessToken().pipe(
            switchMap((ok) => {
              if (!ok) {
                return throwError(() => err);
              }
              return next.handle(addBearer(request));
            })
          );
        }
        return throwError(() => err);
      })
    );
  }

}