import { Component, OnInit } from '@angular/core';
import { forkJoin } from 'rxjs';
import { NotificationBadgeService } from 'src/app/home-rnf/services/notification-badge.service';
import { AdminGuardService } from 'src/app/home-rnf/services/admin-guard.service';
import { AuthService } from 'src/app/home-rnf/services/auth-service.service';
import { ApiService, NotificationAdminTab, NotificationDto } from 'src/app/services/api.service';

@Component({
  selector: 'app-notifications',
  templateUrl: './notifications.component.html',
  styleUrls: ['./notifications.component.scss']
})
export class NotificationsComponent implements OnInit {
  notifications: NotificationDto[] = [];
  loading = false;
  markingAll = false;

  constructor(
    private api: ApiService,
    private notificationBadge: NotificationBadgeService,
    private auth: AuthService,
    private adminGuard: AdminGuardService
  ) {}

  ngOnInit(): void {
    this.loadNotifications();
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

  get unreadCount(): number {
    return this.notifications.filter((n) => !n.read).length;
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
