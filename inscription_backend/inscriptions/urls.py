from django.urls import path

from inscriptions import views

urlpatterns = [
    path("organismes/", views.OrganismeListView.as_view()),
    path("organismes/<int:pk>/", views.OrganismeDetailView.as_view()),
    path("organisme/<int:pk>/", views.OrganismeDetailView.as_view()),
    path("reserves/", views.ReserveListView.as_view()),
    path("applications/", views.ApplicationListView.as_view()),
    path("register/", views.RegisterView.as_view()),
    path("auth/keycloak-config/", views.KeycloakPublicConfigView.as_view()),
    path("auth/token/", views.TokenExchangeView.as_view()),
    path("auth/refresh/", views.RefreshTokenView.as_view()),
    path("me/", views.MeView.as_view()),
    path("me/reserve-options/", views.MeReserveOptionsView.as_view()),
    path("me/reserves/<str:area_code>/", views.MeReserveLinkDetailView.as_view()),
    path("me/reserves/<str:area_code>/referent-request/", views.MeReserveReferentRequestView.as_view()),
    path("me/referent/reserves-members/", views.MeReferentReservesMembersView.as_view()),
    path(
        "me/referent/reserves/<str:area_code>/removal-requests/",
        views.MeReferentReserveRemovalRequestView.as_view(),
    ),
    path("me/additional-access/", views.AdditionalAccessCreateView.as_view()),
    path("notifications/", views.NotificationListView.as_view()),
    path("notifications/<int:pk>/mark-read/", views.NotificationMarkReadView.as_view()),
    path("admin/registration-requests/", views.AdminRegistrationListView.as_view()),
    path("admin/registration-requests/<uuid:public_id>/", views.AdminRegistrationDetailView.as_view()),
    path("admin/registration-requests/<uuid:public_id>/super-approve/", views.AdminSuperApproveView.as_view()),
    path("admin/registration-requests/<uuid:public_id>/super-reject/", views.AdminSuperRejectView.as_view()),
    path("admin/pending-items/", views.AdminPendingItemsView.as_view()),
    path("admin/my-validation-applications/", views.AdminMyValidationApplicationsView.as_view()),
    path("admin/keycloak-users-search/", views.AdminKeycloakUsersSearchView.as_view()),
    path("admin/catalog/applications/", views.AdminApplicationCatalogListCreateView.as_view()),
    path(
        "admin/catalog/applications/refresh-counts/",
        views.AdminApplicationCatalogRefreshCountsView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/refresh-counts/",
        views.AdminApplicationCatalogRefreshCountsView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/",
        views.AdminApplicationCatalogDetailView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/admins/",
        views.AdminApplicationCatalogAdminsView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/admins/<str:user_sub>/",
        views.AdminApplicationCatalogAdminRemoveView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/image/",
        views.AdminApplicationCatalogImageView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/members/dual/",
        views.AdminApplicationCatalogDualMembersView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/members/",
        views.AdminApplicationCatalogMembersView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/members/remove/",
        views.AdminApplicationCatalogMembersBulkRemoveView.as_view(),
    ),
    path(
        "admin/catalog/applications/<slug:application_slug>/members/<str:user_sub>/",
        views.AdminApplicationCatalogMemberRemoveView.as_view(),
    ),
    path(
        "admin/users/<str:user_sub>/application-access/",
        views.AdminUserApplicationAccessView.as_view(),
    ),
    path("admin/application-admins/", views.AdminApplicationAdminsView.as_view()),
    path(
        "admin/applications/<slug:application_slug>/admins/",
        views.AdminApplicationAdminAssignView.as_view(),
    ),
    path(
        "admin/applications/<slug:application_slug>/admins/<str:user_sub>/",
        views.AdminApplicationAdminRemoveView.as_view(),
    ),
    path(
        "admin/registration-items/<int:item_id>/<str:decision>/",
        views.AdminDecideRegistrationItemView.as_view(),
    ),
    path(
        "admin/additional-items/<int:item_id>/<str:decision>/",
        views.AdminDecideAdditionalItemView.as_view(),
    ),
    path(
        "admin/applications/<slug:application_slug>/revoke/<str:user_sub>/",
        views.AdminRevokeAccessView.as_view(),
    ),
    path("admin/reserve-member-removal-requests/", views.AdminReserveMemberRemovalRequestsView.as_view()),
    path(
        "admin/reserves/<str:area_code>/members/add/",
        views.AdminReserveMemberDirectAddView.as_view(),
    ),
    path(
        "admin/reserves/<str:area_code>/members/<str:user_sub>/remove/",
        views.AdminReserveMemberDirectRemoveView.as_view(),
    ),
    path(
        "admin/reserve-member-removal-requests/<int:req_id>/<str:decision>/",
        views.AdminDecideReserveMemberRemovalRequestView.as_view(),
    ),
    path("admin/reserve-referent-requests/", views.AdminReserveReferentRequestsView.as_view()),
    path(
        "admin/reserve-referent-requests/<int:req_id>/<str:decision>/",
        views.AdminDecideReserveReferentRequestView.as_view(),
    ),
]
