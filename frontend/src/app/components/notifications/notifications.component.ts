import { Component, OnInit } from '@angular/core';
import { forkJoin } from 'rxjs';
import { NotificationBadgeService } from 'src/app/home-rnf/services/notification-badge.service';
import { ApiService } from 'src/app/services/api.service';

@Component({
  selector: 'app-notifications',
  templateUrl: './notifications.component.html',
  styleUrls: ['./notifications.component.scss']
})
export class NotificationsComponent implements OnInit {
  notifications: { id: number; title: string; body: string; read: boolean; created_at: string }[] = [];
  loading = false;
  markingAll = false;

  constructor(private api: ApiService, private notificationBadge: NotificationBadgeService) {}

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
