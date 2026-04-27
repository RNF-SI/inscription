from django.contrib import admin

from inscriptions.models import (
    AccessRequestItem,
    AdditionalAccessItem,
    AdditionalAccessRequest,
    Application,
    ApplicationAdmin,
    AuditLog,
    Notification,
    Organisme,
    OrganismeReserveLink,
    RegistrationRequest,
    Reserve,
    ReserveReferentRequest,
    UserApplicationAccess,
    UserProfile,
    UserReserveLink,
)

admin.site.register(Organisme)
admin.site.register(Reserve)
admin.site.register(OrganismeReserveLink)
admin.site.register(Application)
admin.site.register(UserProfile)
admin.site.register(ApplicationAdmin)
admin.site.register(RegistrationRequest)
admin.site.register(AccessRequestItem)
admin.site.register(AdditionalAccessRequest)
admin.site.register(AdditionalAccessItem)
admin.site.register(UserApplicationAccess)
admin.site.register(UserReserveLink)
admin.site.register(Notification)
admin.site.register(AuditLog)
admin.site.register(ReserveReferentRequest)
