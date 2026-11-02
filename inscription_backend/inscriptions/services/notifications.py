from __future__ import annotations

from inscriptions.models import Notification

ADMIN_TAB_REQUESTS = "requests"
ADMIN_TAB_RESERVES = "reserves"
ADMIN_TAB_USER_ACCESS = "user-access"
ADMIN_TAB_APPLICATIONS = "applications"


def notify_user(user_sub: str, title: str, body: str, *, admin_tab: str = "") -> None:
    sub = (user_sub or "").strip()
    if not sub:
        return
    Notification.objects.create(
        user_sub=sub,
        title=title,
        body=body,
        admin_tab=(admin_tab or "").strip(),
    )
