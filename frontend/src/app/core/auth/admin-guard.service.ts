import { inject, Injectable } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { MeResponse } from 'src/app/services/api.service';
import { AuthService } from './auth-service.service';

@Injectable({ providedIn: 'root' })
export class AdminGuardService {
  constructor(private auth: AuthService, private router: Router) {}

  canActivate(): Observable<boolean | UrlTree> {
    return this.auth.restoreSession().pipe(
      switchMap((restored) => {
        if (!restored && !this.auth.authenticated) {
          return of(this.router.parseUrl('/login'));
        }
        return this.auth.ensureFreshToken().pipe(
          switchMap((ok) => {
            if (!ok) {
              return of(this.router.parseUrl('/login'));
            }
            return this.auth.refreshMeFromApi().pipe(
              map((me) => (this.canAccessAdmin(me) ? true : this.router.parseUrl('/')))
            );
          }),
          catchError(() => of(this.router.parseUrl('/')))
        );
      })
    );
  }

  canAccessAdmin(me: MeResponse | null | undefined): boolean {
    if (!me) {
      return false;
    }
    const isReserveReferent =
      !!me.is_reserve_referent || !!(me.reserves || []).some((reserve) => reserve.referent);
    return !!(me.profile.is_super_admin || me.is_app_admin || isReserveReferent);
  }
}

export const AdminGuard: CanActivateFn = () => inject(AdminGuardService).canActivate();
