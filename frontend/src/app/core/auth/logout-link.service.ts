import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { AuthService } from './auth-service.service';


@Injectable({
  providedIn: 'root'
})
export class LogoutLinkService {
  constructor(private auth: AuthService, private router: Router) { }

  canActivate() {

    // Do nothing if already out
    if(!this.auth.authenticated) { return false; }

    // Signs-out and redirects to home
    this.auth.logout();

    return this.router.createUrlTree(['/']);
  }
}
