import { Component, OnDestroy, OnInit } from '@angular/core';
import { forkJoin, Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { NotificationBadgeService } from 'src/app/home-rnf/services/notification-badge.service';
import { AdminGuardService } from 'src/app/home-rnf/services/admin-guard.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { ApiService, NotificationAdminTab, NotificationDto } from 'src/app/services/api.service';

@Component({
  selector: 'app-notifications',
  templateUrl: './notifications.component.html',
  styleUrls: ['./notifications.component.scss']
})
export class NotificationsComponent implements OnInit, OnDestroy {
  notifications: NotificationDto[] = [];
  loading = false;
  markingAll = false;
  deletingRead = false;

  private readonly destroy$ = new Subject<void>();
  private previousUnreadCount = 0;

  constructor(
    private api: ApiService,
    private notificationBadge: NotificationBadgeService,
    private auth: AuthService,
    private adminGuard: AdminGuardService
  ) {}

  ngOnInit(): void {
    this.loadNotifications();
    this.notificationBadge.getUnreadCount$()
      .pipe(takeUntil(this.destroy$))
      .subscribe((count) => {
        if (count > this.previousUnreadCount) {
          this.loadNotifications();
        }
        this.previousUnreadCount = count;
      });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  markRead(id: number): void {
    this.api.markNotificationRead(id).subscribe(() => {
      this.loadNotifications();
      this.notificationBadge.refreshUnreadCount();
    });
  }

  markAllRead(): void {
    const unreadIds = this.notifications.filter((n) => !n.read).map((n) => n.id);
    if (!unreadIds.length || this.markingAll) {
      return;
    }
    this.markingAll = true;
    forkJoin(unreadIds.map((id) => this.api.markNotificationRead(id))).subscribe({
      next: () => {
        this.loadNotifications();
        this.notificationBadge.refreshUnreadCount();
      },
      error: () => {
        this.markingAll = false;
      },
      complete: () => {
        this.markingAll = false;
      },
    });
  }

  deleteReadNotifications(): void {
    if (this.deletingRead || this.readCount === 0) {
      return;
    }
    this.deletingRead = true;
    this.api.deleteReadNotifications().subscribe({
      next: () => {
        this.loadNotifications();
        this.notificationBadge.refreshUnreadCount();
      },
      error: () => {
        this.deletingRead = false;
      },
      complete: () => {
        this.deletingRead = false;
      },
    });
  }

  get unreadCount(): number {
    return this.notifications.filter((n) => !n.read).length;
  }

  get readCount(): number {
    return this.notifications.filter((n) => n.read).length;
  }

  canOpenAdminLink(notification: NotificationDto): boolean {
    if (!notification.admin_tab) {
      return false;
    }
    return this.adminGuard.canAccessAdmin(this.auth.getMeSnapshot());
  }

  adminTabLabel(tab: NotificationAdminTab | '' | undefined): string {
    const labels: Record<NotificationAdminTab, string> = {
      requests: 'Toutes les demandes',
      reserves: 'Membres des réserves',
      'user-access': 'Accès utilisateurs',
      applications: 'Applications',
    };
    if (!tab || !labels[tab]) {
      return 'Administration';
    }
    return labels[tab];
  }

  private loadNotifications(): void {
    this.loading = true;
    this.api.getNotifications().subscribe({
      next: (n) => {
        this.notifications = n;
        this.previousUnreadCount = this.unreadCount;
        this.notificationBadge.setUnreadCount(this.unreadCount);
      },
      error: () => {
        this.notifications = [];
        this.notificationBadge.setUnreadCount(0);
      },
      complete: () => {
        this.loading = false;
      },
    });
  }
}
