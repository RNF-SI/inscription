import { inject, Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, CanActivateFn } from '@angular/router';
import { Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';
import { AuthService } from './auth-service.service';

@Injectable({
  providedIn: 'root',
})
export class LazyDialogLoader {
  constructor(private auth: AuthService, private router: Router) {}

  canActivate(_next: ActivatedRouteSnapshot, _state: RouterStateSnapshot): Observable<boolean> {
    if (this.auth.authenticated) {
      this.router.navigateByUrl('/');
      return of(false);
    }
    return this.auth.restoreSession().pipe(
      map((ok) => {
        if (ok) {
          this.router.navigateByUrl('/');
          return false;
        }
        // Ne pas passer state.url (/login) : sinon post_login_redirect relance ce garde en boucle après OIDC.
        this.auth.beginKeycloakLogin();
        return false;
      })
    );
  }
}

export const LazyDialog: CanActivateFn = (next, state) => {
  return inject(LazyDialogLoader).canActivate(next, state);
};
