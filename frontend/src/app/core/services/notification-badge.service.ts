import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

/**
 * Service générique (no-op par défaut) pour alimenter le badge de notifications.
 * Chaque application peut le surcharger via un provider.
 */
@Injectable({ providedIn: 'root' })
export class NotificationBadgeService {
  protected readonly unreadCountSubject = new BehaviorSubject<number>(0);

  getUnreadCount$(): Observable<number> {
    return this.unreadCountSubject.asObservable();
  }

  refreshUnreadCount(): void {
    // no-op par defaut
  }

  setUnreadCount(count: number): void {
    const normalized = Math.max(0, Number(count) || 0);
    if (normalized === this.unreadCountSubject.value) {
      return;
    }
    this.unreadCountSubject.next(normalized);
  }

  /** Démarre le rafraîchissement périodique (no-op par défaut). */
  startPolling(): void {}

  /** Arrête le rafraîchissement périodique (no-op par défaut). */
  stopPolling(): void {}
}
