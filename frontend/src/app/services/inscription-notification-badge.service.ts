import { Injectable, NgZone, OnDestroy } from '@angular/core';
import { of } from 'rxjs';
import { catchError, map, switchMap, tap } from 'rxjs/operators';
import { NotificationBadgeService } from 'src/app/home-rnf/services/notification-badge.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { AppConfig } from 'src/conf/app.config';
import { ApiService } from './api.service';

@Injectable()
export class InscriptionNotificationBadgeService extends NotificationBadgeService implements OnDestroy {
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollingActive = false;
  private refreshInFlight = false;
  private readonly onVisibilityChange = (): void => {
    if (document.visibilityState === 'visible' && this.auth.authenticated) {
      this.refreshUnreadCount();
    }
  };

  constructor(private api: ApiService, private auth: AuthService, private ngZone: NgZone) {
    super();
    const snapshotCount = this.auth.getMeSnapshot()?.unread_notifications;
    if (typeof snapshotCount === 'number') {
      this.setUnreadCount(snapshotCount);
    }
  }

  ngOnDestroy(): void {
    this.stopPolling();
  }

  override startPolling(): void {
    if (this.pollingActive || AppConfig.features?.notifications === false) {
      return;
    }
    if (!this.auth.authenticated) {
      return;
    }
    this.pollingActive = true;
    this.refreshUnreadCount();
    const intervalMs = AppConfig.features?.notificationPollIntervalMs ?? 30_000;
    this.pollTimer = setInterval(() => {
      this.ngZone.run(() => {
        if (this.auth.authenticated) {
          this.refreshUnreadCount();
        } else {
          this.stopPolling();
          this.setUnreadCount(0);
        }
      });
    }, intervalMs);
    document.addEventListener('visibilitychange', this.onVisibilityChange);
  }

  override stopPolling(): void {
    this.pollingActive = false;
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
  }

  override refreshUnreadCount(): void {
    if (!this.auth.authenticated || this.refreshInFlight) {
      if (!this.auth.authenticated) {
        this.setUnreadCount(0);
      }
      return;
    }
    this.refreshInFlight = true;
    this.auth
      .ensureFreshToken()
      .pipe(
        switchMap((ok) => {
          if (!ok) {
            this.stopPolling();
            this.setUnreadCount(0);
            return of(null);
          }
          return this.api.getUnreadNotificationCount().pipe(
            map((payload) => payload.count || 0),
            tap((count) => {
              this.setUnreadCount(count);
              this.auth.updateMeSnapshotUnreadCount(count);
            }),
            catchError((err: unknown) => {
              const status = (err as { status?: number })?.status;
              if (status === 401) {
                this.stopPolling();
              }
              this.setUnreadCount(0);
              return of(0);
            }),
          );
        }),
      )
      .subscribe({
        complete: () => {
          this.refreshInFlight = false;
        },
        error: () => {
          this.refreshInFlight = false;
          this.stopPolling();
          this.setUnreadCount(0);
        },
      });
  }
}
