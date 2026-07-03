from django.contrib import admin

from inscriptions.models import (
    AccessRequestItem,
    Application,
    AuditLog,
    Notification,
    Organisme,
    OrganismeReserveLink,
    RegistrationRequest,
    Reserve,
    ReserveMemberRemovalRequest,
    ReserveReferentRequest,
)

admin.site.register(Organisme)
admin.site.register(Reserve)
admin.site.register(OrganismeReserveLink)
admin.site.register(Application)
admin.site.register(RegistrationRequest)
admin.site.register(AccessRequestItem)
admin.site.register(ReserveReferentRequest)
admin.site.register(ReserveMemberRemovalRequest)
admin.site.register(Notification)
admin.site.register(AuditLog)
