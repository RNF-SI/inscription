from __future__ import annotations

from rest_framework.permissions import BasePermission

from inscriptions.authentication import KeycloakUser
from inscriptions.models import Application
from inscriptions.roles import groups_for_request, is_app_admin, is_super_admin


class IsKeycloakAuthenticated(BasePermission):
    def has_permission(self, request, view):
        return isinstance(getattr(request, "user", None), KeycloakUser)


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not isinstance(user, KeycloakUser):
            return False
        return is_super_admin(groups_for_request(request))


class IsAppAdminForApplication(BasePermission):
    """Permission sur une vue qui reçoit application_slug en kwargs."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not isinstance(user, KeycloakUser):
            return False
        slug = view.kwargs.get("application_slug")
        if not slug:
            return False
        app = Application.objects.filter(slug=slug).first()
        if not app:
            return False
        return is_app_admin(groups_for_request(request), app)
