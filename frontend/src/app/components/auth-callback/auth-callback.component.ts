import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';

@Component({
  standalone: false,
  selector: 'app-auth-callback',
  templateUrl: './auth-callback.component.html',
  styleUrls: ['./auth-callback.component.scss'],
})
export class AuthCallbackComponent implements OnInit {
  error = false;

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private auth: AuthService,
    private cdr: ChangeDetectorRef,
  ) {}

  ngOnInit(): void {
    const code = this.route.snapshot.queryParamMap.get('code');
    if (!code) {
      this.error = true;
      this.cdr.markForCheck();
      return;
    }
    this.auth.handleOAuthCallback(code).subscribe({
      next: () => {
        this.auth.refreshMeFromApi().subscribe({
          next: () => {
            const raw = sessionStorage.getItem('post_login_redirect');
            sessionStorage.removeItem('post_login_redirect');
            const target = this.auth.safePostLoginTarget(raw);
            this.router.navigateByUrl(target, { replaceUrl: true });
          },
          error: () => {
            this.error = true;
            this.cdr.markForCheck();
          },
        });
      },
      error: () => {
        this.error = true;
        this.cdr.markForCheck();
      },
    });
  }
}
