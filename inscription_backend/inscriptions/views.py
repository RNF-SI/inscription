from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from inscriptions.authentication import KeycloakUser, require_profile
from inscriptions.models import (
    AccessRequestItem,
    Application,
    ApplicationAdmin,
    Notification,
    Organisme,
    RegistrationRequest,
    Reserve,
    UserProfile,
)
from inscriptions.permissions import IsKeycloakAuthenticated, IsSuperAdmin, is_app_admin
from inscriptions.serializers import (
    AdditionalAccessSerializer,
    ApplicationSerializer,
    MeSerializer,
    NotificationSerializer,
    OrganismeDetailSerializer,
    OrganismeSerializer,
    ReserveSerializer,
    SignupSerializer,
)
from inscriptions.services import workflows

logger = logging.getLogger(__name__)


def _token_groups(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups") or []
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for g in raw:
        if isinstance(g, str) and g.strip():
            out.add(g.strip())
    return out


def _token_has_app_access(claims: dict[str, Any], app: Application) -> bool:
    # Convention groupes Keycloak attendue
    groups = _token_groups(claims)
    app_group_candidates = {
        f"/applications/{app.slug}",
        f"applications/{app.slug}",
        app.slug,
    }
    if groups.intersection(app_group_candidates):
        return True

    # Fallback possible via rôles client si le mapper est en place
    client_id = app.keycloak_client_id or ""
    if client_id:
        res_access = claims.get("resource_access") or {}
        if isinstance(res_access, dict):
            client_access = res_access.get(client_id) or {}
            roles = client_access.get("roles") or []
            if isinstance(roles, list) and "access" in roles:
                return True
    return False


class OrganismeListView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        # V2: afficher tous les organismes disponibles en base.
        qs = Organisme.objects.all().order_by("nom_organisme")
        return Response(OrganismeSerializer(qs, many=True).data)


class OrganismeDetailView(APIView):
    def get(self, request, pk):
        org = get_object_or_404(Organisme, pk=pk)
        return Response(OrganismeDetailSerializer(org).data)


class ReserveListView(APIView):
    def get(self, request):
        qs = Reserve.objects.filter(id_type__in=["5", "6", "18"]).order_by("area_name")
        return Response(ReserveSerializer(qs, many=True).data)


class ApplicationListView(APIView):
    def get(self, request):
        qs = Application.objects.all()
        return Response(ApplicationSerializer(qs, many=True).data)


class RegisterView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        ser = SignupSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {"msg": "Données d’inscription invalides.", "errors": ser.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rr = ser.save()
        workflows.on_registration_created(rr)
        return Response({"public_id": str(rr.public_id), "status": rr.status}, status=status.HTTP_201_CREATED)


class KeycloakPublicConfigView(APIView):
    """URL realm et client SPA : alignés sur le .env Django (lus par le front pour la redirection OIDC)."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "keycloakUrl": settings.KEYCLOAK_BASE_URL.rstrip("/"),
                "realm": settings.KEYCLOAK_REALM,
                "clientId": settings.KEYCLOAK_APP_CLIENT_ID,
            }
        )


class TokenExchangeView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        code = request.data.get("code")
        redirect_uri = request.data.get("redirect_uri")
        if not code or not redirect_uri:
            return Response({"detail": "code et redirect_uri requis"}, status=400)
        data = {
            "grant_type": "authorization_code",
            "client_id": settings.KEYCLOAK_APP_CLIENT_ID,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if settings.KEYCLOAK_APP_CLIENT_SECRET:
            data["client_secret"] = settings.KEYCLOAK_APP_CLIENT_SECRET
        url = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            logger.warning("token exchange failed: %s", r.text[:500])
            return Response({"detail": "Échec de l’échange de jeton."}, status=400)
        return Response(r.json())


class RefreshTokenView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        refresh_token = request.data.get("refresh_token")
        if not refresh_token:
            return Response({"detail": "refresh_token requis"}, status=400)
        data = {
            "grant_type": "refresh_token",
            "client_id": settings.KEYCLOAK_APP_CLIENT_ID,
            "refresh_token": refresh_token,
        }
        if settings.KEYCLOAK_APP_CLIENT_SECRET:
            data["client_secret"] = settings.KEYCLOAK_APP_CLIENT_SECRET
        url = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
        r = requests.post(url, data=data, timeout=30)
        if r.status_code != 200:
            logger.info("refresh token failed: %s", r.text[:500])
            return Response({"detail": "refresh_token invalide ou expiré"}, status=401)
        return Response(r.json())


class MeView(APIView):
    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
        apps = Application.objects.all()
        pending_reg_items = AccessRequestItem.objects.filter(
            registration__created_profile=prof,
            registration__status=RegistrationRequest.STATUS_PENDING_APPS,
            origin=AccessRequestItem.ORIGIN_REGISTRATION,
            status=AccessRequestItem.STATUS_PENDING,
        ).select_related("application")
        pending_additional = AccessRequestItem.objects.filter(
            user=prof,
            registration__isnull=True,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            status=AccessRequestItem.STATUS_PENDING,
        ).select_related("application")
        out = []
        for app in apps:
            st = "none"
            if app.managed_by_si and not app.requires_access_request:
                st = "active"
            elif _token_has_app_access(claims, app):
                st = "active"
            if app.requires_access_request and (
                any(i.application_id == app.id for i in pending_reg_items)
                or any(i.application_id == app.id for i in pending_additional)
            ):
                st = "pending"
            out.append(
                {
                    "application": ApplicationSerializer(app).data,
                    "access_status": st,
                }
            )
        reserves = [
            {
                "area_code": x.reserve.area_code,
                "area_name": x.reserve.area_name,
                "referent": x.referent,
                "referent_valid": x.referent_valid,
            }
            for x in prof.reserve_links.select_related("reserve").all()
        ]
        is_app_admin = ApplicationAdmin.objects.filter(user=prof).exists()
        return Response(
            {
                "profile": MeSerializer(prof).data,
                "applications": out,
                "reserves": reserves,
                "is_app_admin": is_app_admin,
                "unread_notifications": Notification.objects.filter(user=prof, read=False).count(),
            }
        )


class NotificationListView(APIView):
    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        qs = Notification.objects.filter(user=prof)[:100]
        return Response(NotificationSerializer(qs, many=True).data)


class NotificationMarkReadView(APIView):
    def patch(self, request, pk):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        n = get_object_or_404(Notification, pk=pk, user=prof)
        n.read = True
        n.save(update_fields=["read"])
        return Response(NotificationSerializer(n).data)


class AdditionalAccessCreateView(APIView):
    def post(self, request):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        ser = AdditionalAccessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
        requested_slugs = ser.validated_data["application_slugs"]
        filtered_slugs = []
        for slug in requested_slugs:
            app = Application.objects.filter(slug=slug).first()
            if not app:
                continue
            if _token_has_app_access(claims, app):
                continue
            filtered_slugs.append(slug)
        if not filtered_slugs:
            return Response({"detail": "Accès déjà actif pour les applications demandées."}, status=400)
        try:
            req = workflows.create_additional_access_request(
                prof,
                filtered_slugs,
                ser.validated_data.get("remarks", ""),
            )
        except ValueError:
            return Response(
                {"detail": "Demande déjà en attente ou accès déjà actif pour cette application."},
                status=400,
            )
        return Response({"public_id": str(req)}, status=201)


class AdminRegistrationListView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        qs = RegistrationRequest.objects.all().order_by("-created_at")[:200]
        data = []
        for r in qs:
            data.append(
                {
                    "public_id": str(r.public_id),
                    "status": r.status,
                    "email": r.email,
                    "username": r.username,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return Response(data)


class AdminRegistrationDetailView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, public_id):
        r = get_object_or_404(RegistrationRequest, public_id=public_id)
        items = [
            {
                "id": i.pk,
                "application": ApplicationSerializer(i.application).data,
                "status": i.status,
                "request_justification": i.request_justification,
            }
            for i in r.items.all()
        ]
        return Response(
            {
                "public_id": str(r.public_id),
                "status": r.status,
                "email": r.email,
                "username": r.username,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "remarks": r.remarks,
                "reserve_codes": r.reserve_codes,
                "items": items,
            }
        )


class AdminSuperApproveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, public_id):
        r = get_object_or_404(RegistrationRequest, public_id=public_id)
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        try:
            workflows.super_admin_approve(r, prof, getattr(request.user, "claims", {}).get("sub", ""))
        except ValueError:
            return Response({"detail": "Statut invalide"}, status=400)
        except Exception:
            logger.exception("super_admin_approve")
            return Response({"detail": "Erreur serveur"}, status=500)
        return Response({"status": r.status})


class AdminSuperRejectView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, public_id):
        r = get_object_or_404(RegistrationRequest, public_id=public_id)
        sub = getattr(request.user, "claims", {}).get("sub", "")
        try:
            workflows.super_admin_reject(r, sub, request.data.get("note", ""))
        except Exception:
            logger.exception("super_admin_reject")
            return Response({"detail": "Erreur serveur"}, status=500)
        return Response({"status": r.status})


class AdminPendingItemsView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        admin_app_ids = list(ApplicationAdmin.objects.filter(user=prof).values_list("application_id", flat=True))
        if prof.is_super_admin:
            reg_items = AccessRequestItem.objects.filter(
                status=AccessRequestItem.STATUS_PENDING,
                registration__status=RegistrationRequest.STATUS_PENDING_APPS,
                origin=AccessRequestItem.ORIGIN_REGISTRATION,
            ).select_related("application", "registration")
        else:
            if not admin_app_ids:
                return Response([])
            reg_items = AccessRequestItem.objects.filter(
                status=AccessRequestItem.STATUS_PENDING,
                registration__status=RegistrationRequest.STATUS_PENDING_APPS,
                application_id__in=admin_app_ids,
                origin=AccessRequestItem.ORIGIN_REGISTRATION,
            ).select_related("application", "registration")
        out = []
        for i in reg_items:
            if not prof.is_super_admin and not is_app_admin(prof, i.application):
                continue
            out.append(
                {
                    "kind": "registration",
                    "item_id": i.pk,
                    "application": ApplicationSerializer(i.application).data,
                    "registration_public_id": str(i.registration.public_id),
                    "applicant_email": i.registration.email,
                    "request_justification": i.request_justification,
                }
            )
        add_qs = AccessRequestItem.objects.filter(
            status=AccessRequestItem.STATUS_PENDING,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            registration__isnull=True,
        ).select_related("application", "user")
        for i in add_qs:
            if not is_app_admin(prof, i.application):
                continue
            out.append(
                {
                    "kind": "additional",
                    "item_id": i.pk,
                    "application": ApplicationSerializer(i.application).data,
                    "request_public_id": str(i.request_public_id),
                    "applicant_email": i.user.email if i.user else "",
                    "request_justification": i.request_justification,
                }
            )
        return Response(out)


class AdminDecideRegistrationItemView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, item_id, decision):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        item = get_object_or_404(AccessRequestItem, pk=item_id)
        if not is_app_admin(prof, item.application):
            return Response(status=403)
        approve = decision == "approve"
        sub = getattr(request.user, "claims", {}).get("sub", "")
        try:
            workflows.app_admin_decide_item(item, approve, prof, sub, request.data.get("note", ""))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"ok": True})


class AdminDecideAdditionalItemView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, item_id, decision):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        item = get_object_or_404(
            AccessRequestItem, pk=item_id, origin=AccessRequestItem.ORIGIN_ADDITIONAL, registration__isnull=True
        )
        if not is_app_admin(prof, item.application):
            return Response(status=403)
        approve = decision == "approve"
        sub = getattr(request.user, "claims", {}).get("sub", "")
        try:
            workflows.app_admin_decide_additional_item(item, approve, prof, sub, request.data.get("note", ""))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"ok": True})


class AdminRevokeAccessView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, application_slug, user_sub):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        app = get_object_or_404(Application, slug=application_slug)
        if not is_app_admin(prof, app):
            return Response(status=403)
        target = get_object_or_404(UserProfile, keycloak_sub=user_sub)
        from inscriptions.keycloak_client import KeycloakAdminClient
        from inscriptions.services import provisioning as prov

        kc = KeycloakAdminClient()
        try:
            prov.revoke_application_access(kc, target.keycloak_sub, app)
        except Exception:
            logger.exception("revoke keycloak")
        return Response({"ok": True})
