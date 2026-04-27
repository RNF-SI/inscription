from __future__ import annotations

from rest_framework.permissions import BasePermission

from inscriptions.authentication import KeycloakUser
from inscriptions.models import Application, ApplicationAdmin


class IsKeycloakAuthenticated(BasePermission):
    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), KeycloakUser)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        return (
            isinstance(user, KeycloakUser)
            and user.profile is not None
            and user.profile.is_super_admin
        )


def is_app_admin(profile, application: Application) -> bool:
    if profile.is_super_admin:
        return True
    return ApplicationAdmin.objects.filter(user=profile, application=application).exists()


class IsAppAdminForApplication(BasePermission):
    """Permission sur une vue qui reçoit application_slug en kwargs."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not isinstance(user, KeycloakUser) or not user.profile:
            return False
        slug = view.kwargs.get("application_slug")
        if not slug:
            return False
        app = Application.objects.filter(slug=slug).first()
        if not app:
            return False
        return is_app_admin(user.profile, app)
