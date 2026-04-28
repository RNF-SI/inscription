import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';
import { NotificationBadgeService } from 'src/app/home-rnf/services/notification-badge.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { ApiService } from './api.service';

@Injectable()
export class InscriptionNotificationBadgeService extends NotificationBadgeService {
  constructor(private api: ApiService, private auth: AuthService) {
    super();
    const snapshotCount = this.auth.getMeSnapshot()?.unread_notifications;
    if (typeof snapshotCount === 'number') {
      this.setUnreadCount(snapshotCount);
    }
  }

  override getUnreadCount$(): Observable<number> {
    this.refreshUnreadCount();
    return super.getUnreadCount$();
  }

  override refreshUnreadCount(): void {
    this.api.getMe().pipe(
      map((me) => me.unread_notifications || 0),
      tap((count) => this.setUnreadCount(count)),
      catchError(() => {
        this.setUnreadCount(0);
        return of(0);
      })
    ).subscribe();
  }
}
