"""Compatibilité : gestion des admins applicatifs via groupes Keycloak."""

from inscriptions.roles import (
    add_application_admin,
    count_application_admins,
    list_application_admins,
    remove_application_admin,
    replace_application_admins,
)

__all__ = [
    "add_application_admin",
    "count_application_admins",
    "list_application_admins",
    "remove_application_admin",
    "replace_application_admins",
]
