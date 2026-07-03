from __future__ import annotations

import logging
import mimetypes
import time
from typing import Any

import requests
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from inscriptions.authentication import KeycloakUser, get_current_sub, require_keycloak_user
from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import (
    AccessRequestItem,
    Application,
    Notification,
    Organisme,
    ReserveMemberRemovalRequest,
    ReserveReferentRequest,
    RegistrationRequest,
    Reserve,
)
from inscriptions.permissions import IsKeycloakAuthenticated, IsSuperAdmin
from inscriptions.roles import (
    admin_application_slugs,
    effective_groups_from_claims,
    groups_for_request,
    is_app_admin,
    is_super_admin,
    normalize_group_paths,
)
from inscriptions.user_identity import UserInfo, fetch_user_info
from inscriptions.serializers import (
    AdditionalAccessSerializer,
    AdminApplicationWriteSerializer,
    ApplicationCatalogSerializer,
    ApplicationSerializer,
    MeUpdateSerializer,
    NotificationSerializer,
    OrganismeDetailSerializer,
    OrganismeSerializer,
    ReserveSerializer,
    SignupSerializer,
)
from inscriptions.services import application_access as app_access_svc
from inscriptions.services import application_admins as app_admins_svc
from inscriptions.services.application_images import ApplicationImageError, remove_application_image, save_application_image
from inscriptions.services import reserve_notifications as reserve_notify
from inscriptions.services import notifications as notify_svc
from inscriptions.services import workflows

logger = logging.getLogger(__name__)
_ORG_NAME_CACHE: dict[str, tuple[float, str]] = {}
_ORG_NAME_CACHE_TTL_SEC = 300


def _token_groups(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups") or []
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for g in raw:
        if isinstance(g, str) and g.strip():
            out.add(g.strip())
    return out


def _fetch_user_group_paths(keycloak_sub: str) -> list[str]:
    kc = KeycloakAdminClient()
    out: list[str] = []
    for group in kc.get_user_groups(keycloak_sub):
        path = (group.get("path") or "").strip()
        if path:
            out.append(path.lstrip("/"))
    return out


def _claims_with_groups(claims: dict[str, Any], keycloak_sub: str) -> dict[str, Any]:
    if _token_groups(claims):
        return claims
    if not settings.KEYCLOAK_SYNC_ENABLED or not (keycloak_sub or "").strip():
        return claims
    try:
        kc_paths = _fetch_user_group_paths(keycloak_sub)
    except KeycloakAdminError as exc:
        logger.warning("Impossible de charger les groupes Keycloak pour %s: %s", keycloak_sub, exc)
        return claims
    if not kc_paths:
        return claims
    return {**claims, "groups": kc_paths}


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


def _first_organisme_group_path(claims: dict[str, Any]) -> str:
    root = (getattr(settings, "KEYCLOAK_GROUP_ORGANISMES", "organismes") or "organismes").strip("/")
    groups = sorted(_token_groups(claims))
    for g in groups:
        path = f"/{g.strip('/')}"
        if path == f"/{root}" or path.startswith(f"/{root}/"):
            return path
    return ""


def _organisme_name_from_group_path(group_path: str) -> str:
    now = time.time()
    cached = _ORG_NAME_CACHE.get(group_path)
    if cached and (now - cached[0]) < _ORG_NAME_CACHE_TTL_SEC:
        return cached[1]

    if not group_path:
        return ""

    try:
        kc = KeycloakAdminClient()
        group = kc.find_group_by_path(group_path)
        if not group:
            _ORG_NAME_CACHE[group_path] = (now, "")
            return ""
        attrs = group.get("attributes") or {}
        names = attrs.get("nom_organisme") or []
        if isinstance(names, list) and names:
            name = str(names[0]).strip()
        else:
            name = str(group.get("name") or "").strip()
        _ORG_NAME_CACHE[group_path] = (now, name)
        return name
    except KeycloakAdminError:
        logger.warning("Impossible de resoudre l'organisme Keycloak pour %s", group_path)
    except Exception:
        logger.exception("Erreur de resolution organisme Keycloak")
    _ORG_NAME_CACHE[group_path] = (now, "")
    return ""


def _organisme_id_from_group_path(group_path: str) -> int | None:
    if not group_path:
        return None
    try:
        kc = KeycloakAdminClient()
        group = kc.find_group_by_path(group_path)
        if not group:
            return None
        attrs = group.get("attributes") or {}
        ids = attrs.get("id_organisme") or []
        if isinstance(ids, list) and ids:
            try:
                return int(str(ids[0]).strip())
            except (TypeError, ValueError):
                return None
    except Exception:
        logger.exception("Erreur de resolution id_organisme Keycloak")
    return None


def _reserve_codes_from_token(claims: dict[str, Any]) -> list[str]:
    root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
    groups = sorted(_token_groups(claims))
    codes: list[str] = []
    for g in groups:
        path = f"/{g.strip('/')}"
        prefix = f"/{root}/"
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :].strip("/")
        if not remainder:
            continue
        code = remainder.split("/", 1)[0].strip()
        if code:
            codes.append(code)
    # déduplication en conservant l'ordre
    seen: set[str] = set()
    out: list[str] = []
    for c in codes:
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _referent_reserve_codes_from_token(claims: dict[str, Any]) -> list[str]:
    root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
    groups = sorted(_token_groups(claims))
    out: list[str] = []
    seen: set[str] = set()
    for g in groups:
        path = f"/{g.strip('/')}"
        prefix = f"/{root}/"
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :].strip("/")
        if not remainder:
            continue
        parts = [p for p in remainder.split("/") if p]
        if len(parts) != 2 or parts[1] != "referent":
            continue
        code = parts[0].strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _request_groups(request) -> set[str]:
    return normalize_group_paths(groups_for_request(request))


def _is_admin_user(request) -> bool:
    groups = _request_groups(request)
    if is_super_admin(groups):
        return True
    return bool(admin_application_slugs(groups))


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


class ApplicationImageServeView(APIView):
    """Sert les vignettes du catalogue (hors dépôt git, dossier media/)."""

    authentication_classes = []
    permission_classes = []

    def get(self, request, filename):
        from inscriptions.services.application_images import ApplicationImageError, application_image_path

        try:
            path = application_image_path(filename)
        except ApplicationImageError as exc:
            raise Http404 from exc
        if not path.is_file():
            raise Http404
        content_type, _ = mimetypes.guess_type(path.name)
        return FileResponse(path.open("rb"), content_type=content_type or "application/octet-stream")


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
    def patch(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)

        ser = MeUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if not data:
            return Response({"detail": "Aucune modification fournie."}, status=400)

        try:
            kc = KeycloakAdminClient()
            kc.update_user_profile(
                user.sub,
                username=data.get("username"),
                email=data.get("email"),
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                function_value=data.get("fonction"),
            )
        except KeycloakAdminError as exc:
            logger.warning("Me patch keycloak failed: %s", exc)
            return Response({"detail": "Mise à jour Keycloak impossible."}, status=502)

        return self.get(request)

    def get(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        groups_list = groups_for_request(request)
        groups = normalize_group_paths(groups_list)
        claims = {**user.claims, "groups": groups_list} if groups_list else user.claims
        org_group_path = _first_organisme_group_path(claims)
        profile_data = {
            "keycloak_sub": claims.get("sub") or user.sub,
            "email": claims.get("email") or "",
            "username": claims.get("preferred_username") or claims.get("username") or "",
            "first_name": claims.get("given_name") or claims.get("first_name") or "",
            "last_name": claims.get("family_name") or claims.get("last_name") or "",
            "is_super_admin": is_super_admin(groups),
            "legacy_id_role": None,
            "fonction": (claims.get("function") or claims.get("fonction") or "").strip(),
            "organisme": (
                _organisme_name_from_group_path(org_group_path)
                or (claims.get("organisme_name") or claims.get("organisme") or "").strip()
            ),
        }
        apps = Application.objects.all()
        user_sub = user.sub
        pending_reg_items = AccessRequestItem.objects.filter(
            registration__keycloak_user_id=user_sub,
            registration__status=RegistrationRequest.STATUS_PENDING_APPS,
            origin=AccessRequestItem.ORIGIN_REGISTRATION,
            status=AccessRequestItem.STATUS_PENDING,
        ).select_related("application")
        pending_additional = AccessRequestItem.objects.filter(
            user_sub=user_sub,
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
        reserve_codes = _reserve_codes_from_token(claims)
        referent_codes_list = _referent_reserve_codes_from_token(claims)
        referent_codes = set(referent_codes_list)
        pending_referent_codes = set(
            ReserveReferentRequest.objects.filter(
                user_sub=user_sub,
                status=ReserveReferentRequest.STATUS_PENDING,
            ).values_list("reserve_id", flat=True)
        )
        all_reserve_codes: list[str] = []
        seen_codes: set[str] = set()
        for code in reserve_codes + referent_codes_list:
            if code and code not in seen_codes:
                seen_codes.add(code)
                all_reserve_codes.append(code)
        reserve_by_code = {r.area_code: r for r in Reserve.objects.filter(area_code__in=all_reserve_codes)}
        reserves = []
        for code in all_reserve_codes:
            r = reserve_by_code.get(code)
            if not r:
                continue
            is_referent = code in referent_codes
            reserves.append(
                {
                    "area_code": r.area_code,
                    "area_name": r.area_name,
                    "referent": is_referent,
                    "referent_valid": is_referent,
                    "referent_pending": (code in pending_referent_codes) and (not is_referent),
                }
            )
        is_app_admin_flag = bool(admin_application_slugs(groups))
        is_reserve_referent = bool(referent_codes)
        return Response(
            {
                "profile": profile_data,
                "applications": out,
                "reserves": reserves,
                "is_app_admin": is_app_admin_flag,
                "is_reserve_referent": is_reserve_referent,
                "unread_notifications": Notification.objects.filter(user_sub=user_sub, read=False).count(),
            }
        )


class MeReserveOptionsView(APIView):
    def get(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = user.claims
        org_group_path = _first_organisme_group_path(claims)
        org_id = _organisme_id_from_group_path(org_group_path)
        if not org_id:
            return Response([])
        org = Organisme.objects.filter(pk=org_id).first()
        if not org:
            return Response([])
        links = org.reserve_links.select_related("reserve").all()
        out = [
            {"area_code": l.reserve.area_code, "area_name": l.reserve.area_name, "principal": l.principal}
            for l in links
        ]
        return Response(out)


class MeReserveLinkDetailView(APIView):
    def post(self, request, area_code):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)
        claims = user.claims
        org_group_path = _first_organisme_group_path(claims)
        org_id = _organisme_id_from_group_path(org_group_path)
        if not org_id:
            return Response({"detail": "Organisme introuvable dans le token"}, status=400)
        allowed = Organisme.objects.filter(pk=org_id, reserve_links__reserve=reserve).exists()
        if not allowed:
            return Response({"detail": "Réserve non liée à votre organisme"}, status=403)
        try:
            kc = KeycloakAdminClient()
            gid = kc.ensure_reserve_group(reserve.area_code)
            kc.user_join_group(user.sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Ajout groupe reserve keycloak impossible: %s", exc)
            return Response({"detail": "Ajout de la réserve impossible côté Keycloak"}, status=502)
        member_info = UserInfo.from_claims(_claims_with_groups(user.claims, user.sub))
        reserve_notify.notify_referents_new_member(member_info, reserve)
        return Response({"ok": True}, status=201)

    def delete(self, request, area_code):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)
        try:
            kc = KeycloakAdminClient()
            gid = kc.ensure_reserve_group(reserve.area_code)
            kc.user_leave_group(user.sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Suppression groupe reserve keycloak impossible: %s", exc)
            return Response({"detail": "Suppression de la réserve impossible côté Keycloak"}, status=502)
        return Response(status=204)


class MeReserveReferentRequestView(APIView):
    def post(self, request, area_code):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)

        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        claims = _claims_with_groups(user.claims, user.sub)
        reserve_codes = set(_reserve_codes_from_token(claims))
        if area_code not in reserve_codes:
            return Response({"detail": "Vous devez être membre de la réserve"}, status=403)

        referent_codes = set(_referent_reserve_codes_from_token(claims))
        if area_code in referent_codes:
            return Response({"detail": "Vous êtes déjà référent de cette réserve"}, status=400)

        already_pending = ReserveReferentRequest.objects.filter(
            user_sub=user.sub,
            reserve=reserve,
            status=ReserveReferentRequest.STATUS_PENDING,
        ).exists()
        if already_pending:
            return Response({"detail": "Une demande est déjà en attente pour cette réserve"}, status=400)

        req = ReserveReferentRequest.objects.create(user_sub=user.sub, reserve=reserve)
        reserve_notify.notify_referent_request_created(UserInfo.from_claims(claims), reserve)
        return Response({"id": req.id, "status": req.status}, status=201)


class MeReferentReservesMembersView(APIView):
    def get(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = _claims_with_groups(user.claims, user.sub)
        groups = _token_groups(claims)
        referent_codes = _referent_reserve_codes_from_token(claims)
        if is_super_admin(groups):
            codes = list(Reserve.objects.order_by("area_name").values_list("area_code", flat=True))
        else:
            codes = referent_codes
        if not codes:
            return Response([])

        reserves = {r.area_code: r for r in Reserve.objects.filter(area_code__in=codes)}
        root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
        out = []
        kc = KeycloakAdminClient()
        for code in codes:
            group = kc.find_group_by_path(f"/{root}/{code}")
            if not group or not group.get("id"):
                continue
            pending_targets: set[str] = set(
                ReserveMemberRemovalRequest.objects.filter(
                    reserve_id=code,
                    requester_sub=user.sub,
                    status=ReserveMemberRemovalRequest.STATUS_PENDING,
                ).values_list("target_sub", flat=True)
            )
            members = kc.list_group_members(group["id"])
            out.append(
                {
                    "reserve": {
                        "area_code": code,
                        "area_name": reserves[code].area_name if code in reserves else code,
                    },
                    "can_request_removal": (not is_super_admin(groups)) and (code in set(referent_codes)),
                    "can_direct_remove": is_super_admin(groups),
                    "can_direct_add": is_super_admin(groups),
                    "members": [
                        {
                            "sub": m.get("id"),
                            "email": m.get("email") or "",
                            "first_name": m.get("firstName") or "",
                            "last_name": m.get("lastName") or "",
                            "username": m.get("username") or "",
                            "pending_removal_request": (m.get("id") or "") in pending_targets,
                        }
                        for m in members
                        if m.get("id")
                    ],
                }
            )
        return Response(out)


class MeReferentReserveRemovalRequestView(APIView):
    def post(self, request, area_code):
        user = require_keycloak_user(request)
        if not user:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = _claims_with_groups(user.claims, user.sub)
        referent_codes = set(_referent_reserve_codes_from_token(claims))
        if area_code not in referent_codes:
            return Response({"detail": "Vous n'êtes pas référent de cette réserve"}, status=403)

        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        target_sub = (request.data.get("target_sub") or "").strip()
        reason = (request.data.get("reason") or "").strip()
        if not target_sub or not reason:
            return Response({"detail": "target_sub et reason sont requis"}, status=400)
        if target_sub == user.sub:
            return Response({"detail": "Vous ne pouvez pas demander votre propre retrait."}, status=400)

        existing = ReserveMemberRemovalRequest.objects.filter(
            reserve=reserve,
            requester_sub=user.sub,
            target_sub=target_sub,
            status=ReserveMemberRemovalRequest.STATUS_PENDING,
        ).exists()
        if existing:
            return Response({"detail": "Une demande est déjà en attente pour ce membre"}, status=400)

        req = ReserveMemberRemovalRequest.objects.create(
            reserve=reserve,
            requester_sub=user.sub,
            target_sub=target_sub,
            target_email=(request.data.get("target_email") or "").strip(),
            target_first_name=(request.data.get("target_first_name") or "").strip(),
            target_last_name=(request.data.get("target_last_name") or "").strip(),
            reason=reason,
        )

        requester_info = UserInfo.from_claims(_claims_with_groups(user.claims, user.sub))
        reserve_notify.notify_reserve_member_removal_request(
            requester=requester_info,
            reserve=reserve,
            target_first_name=req.target_first_name,
            target_last_name=req.target_last_name,
            target_email=req.target_email,
            target_sub=req.target_sub,
            reason=reason,
        )
        return Response({"id": req.id, "status": req.status}, status=201)


class AdminReserveMemberRemovalRequestsView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        if not require_keycloak_user(request):
            return Response(status=401)
        qs = ReserveMemberRemovalRequest.objects.filter(
            status=ReserveMemberRemovalRequest.STATUS_PENDING
        ).select_related("reserve")
        out = []
        for r in qs:
            requester = fetch_user_info(r.requester_sub)
            requester_email = requester.email if requester else ""
            requester_name = (
                f"{requester.first_name} {requester.last_name}".strip() if requester else r.requester_sub
            )
            out.append(
                {
                    "id": r.id,
                    "reserve": {"area_code": r.reserve.area_code, "area_name": r.reserve.area_name},
                    "requester_email": requester_email,
                    "requester_name": requester_name,
                    "target_sub": r.target_sub,
                    "target_email": r.target_email,
                    "target_first_name": r.target_first_name,
                    "target_last_name": r.target_last_name,
                    "reason": r.reason,
                    "created_at": r.created_at.isoformat(),
                }
            )
        return Response(out)


class AdminDecideReserveMemberRemovalRequestView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, req_id, decision):
        actor = require_keycloak_user(request)
        if not actor:
            return Response(status=401)

        req = get_object_or_404(ReserveMemberRemovalRequest, pk=req_id)
        if req.status != ReserveMemberRemovalRequest.STATUS_PENDING:
            return Response({"detail": "Demande déjà traitée"}, status=400)

        approve = decision == "approve"
        note = (request.data.get("note") or "").strip()
        if not approve and not note:
            return Response({"detail": "Motif requis pour refuser"}, status=400)

        if approve:
            try:
                kc = KeycloakAdminClient()
                root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
                reserve_group = kc.find_group_by_path(f"/{root}/{req.reserve.area_code}")
                if reserve_group and reserve_group.get("id"):
                    kc.user_leave_group(req.target_sub, reserve_group["id"])
                referent_group = kc.find_group_by_path(f"/{root}/{req.reserve.area_code}/referent")
                if referent_group and referent_group.get("id"):
                    kc.user_leave_group(req.target_sub, referent_group["id"])
            except KeycloakAdminError as exc:
                logger.warning("Retrait membre reserve impossible: %s", exc)
                return Response({"detail": "Échec du retrait côté Keycloak"}, status=502)

        req.status = (
            ReserveMemberRemovalRequest.STATUS_APPROVED
            if approve
            else ReserveMemberRemovalRequest.STATUS_REJECTED
        )
        req.decided_by_sub = actor.sub
        req.decided_at = timezone.now()
        req.decision_note = note
        req.save(update_fields=["status", "decided_by_sub", "decided_at", "decision_note"])

        requester = fetch_user_info(req.requester_sub)
        if not requester:
            requester = UserInfo(sub=req.requester_sub, email="", username="", first_name="", last_name="")
        reserve_notify.notify_reserve_member_removal_decided(
            requester=requester,
            reserve=req.reserve,
            target_first_name=req.target_first_name,
            target_last_name=req.target_last_name,
            target_email=req.target_email,
            approve=approve,
            note=note,
        )
        return Response({"ok": True})


class AdminReserveMemberDirectRemoveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, area_code, user_sub):
        if not require_keycloak_user(request):
            return Response(status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        try:
            kc = KeycloakAdminClient()
            root = (getattr(settings, "KEYCLOAK_GROUP_RESERVES", "reserves") or "reserves").strip("/")
            reserve_group = kc.find_group_by_path(f"/{root}/{reserve.area_code}")
            if reserve_group and reserve_group.get("id"):
                kc.user_leave_group(user_sub, reserve_group["id"])
            referent_group = kc.find_group_by_path(f"/{root}/{reserve.area_code}/referent")
            if referent_group and referent_group.get("id"):
                kc.user_leave_group(user_sub, referent_group["id"])
        except KeycloakAdminError as exc:
            logger.warning("Retrait direct membre reserve impossible: %s", exc)
            return Response({"detail": "Échec du retrait côté Keycloak"}, status=502)

        return Response({"ok": True})


class AdminReserveMemberDirectAddView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, area_code):
        if not require_keycloak_user(request):
            return Response(status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "email requis"}, status=400)
        try:
            kc = KeycloakAdminClient()
            users = kc.search_users(email, max_count=20)
        except KeycloakAdminError as exc:
            logger.warning("Recherche utilisateur Keycloak impossible: %s", exc)
            return Response({"detail": "Recherche utilisateur indisponible"}, status=502)
        user_sub = ""
        for u in users:
            if (u.get("email") or "").strip().lower() == email:
                user_sub = (u.get("id") or "").strip()
                break
        if not user_sub:
            return Response({"detail": "Utilisateur introuvable pour cet email"}, status=404)

        try:
            kc = KeycloakAdminClient()
            gid = kc.ensure_reserve_group(reserve.area_code)
            kc.user_join_group(user_sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Ajout direct membre reserve impossible: %s", exc)
            return Response({"detail": "Échec de l'ajout côté Keycloak"}, status=502)

        member_info = fetch_user_info(user_sub) or UserInfo(
            sub=user_sub, email=email, username=email, first_name="", last_name=""
        )
        reserve_notify.notify_referents_new_member(member_info, reserve)
        return Response({"ok": True})


class AdminKeycloakUsersSearchView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        if not require_keycloak_user(request):
            return Response(status=401)
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response([])
        try:
            kc = KeycloakAdminClient()
            users = kc.search_users(q, max_count=20)
        except KeycloakAdminError as exc:
            logger.warning("Recherche utilisateurs Keycloak impossible: %s", exc)
            return Response({"detail": "Recherche utilisateurs indisponible"}, status=502)
        out = []
        for u in users:
            sub = (u.get("id") or "").strip()
            if not sub:
                continue
            email = (u.get("email") or "").strip()
            first_name = (u.get("firstName") or "").strip()
            last_name = (u.get("lastName") or "").strip()
            username = (u.get("username") or "").strip()
            label_name = f"{first_name} {last_name}".strip()
            label = f"{label_name} ({email or username})" if label_name else (email or username)
            out.append(
                {
                    "keycloak_sub": sub,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "username": username,
                    "label": label,
                }
            )
        return Response(out)


class AdminReserveReferentRequestsView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        if not require_keycloak_user(request):
            return Response(status=401)
        qs = ReserveReferentRequest.objects.filter(status=ReserveReferentRequest.STATUS_PENDING).select_related(
            "reserve"
        )
        out = []
        for r in qs:
            user_info = fetch_user_info(r.user_sub)
            out.append(
                {
                    "id": r.id,
                    "reserve": {"area_code": r.reserve.area_code, "area_name": r.reserve.area_name},
                    "user_sub": r.user_sub,
                    "user_email": user_info.email if user_info else "",
                    "user_first_name": user_info.first_name if user_info else "",
                    "user_last_name": user_info.last_name if user_info else "",
                    "user_fonction": user_info.fonction if user_info else "",
                }
            )
        return Response(out)


class AdminDecideReserveReferentRequestView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, req_id, decision):
        if not require_keycloak_user(request):
            return Response(status=401)
        req = get_object_or_404(ReserveReferentRequest, pk=req_id)
        if req.status != ReserveReferentRequest.STATUS_PENDING:
            return Response({"detail": "Demande déjà traitée"}, status=400)

        approve = decision == "approve"
        note = (request.data.get("note") or "").strip()
        if not approve and not note:
            return Response({"detail": "Motif requis pour refuser"}, status=400)

        if approve:
            try:
                kc = KeycloakAdminClient()
                gid = kc.ensure_reserve_referent_group(req.reserve.area_code)
                kc.user_join_group(req.user_sub, gid)
            except KeycloakAdminError as exc:
                logger.warning("Validation referent impossible côté Keycloak: %s", exc)
                return Response({"detail": "Échec côté Keycloak"}, status=502)

        user_info = fetch_user_info(req.user_sub) or UserInfo(
            sub=req.user_sub, email="", username=req.user_sub, first_name="", last_name=""
        )
        reserve_notify.notify_referent_request_decided(
            user_info,
            req.reserve,
            approve=approve,
            note=note,
        )
        req.delete()
        return Response({"ok": True})


class NotificationListView(APIView):
    def get(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        qs = Notification.objects.filter(user_sub=user.sub)[:100]
        return Response(NotificationSerializer(qs, many=True).data)


class NotificationMarkReadView(APIView):
    def patch(self, request, pk):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        n = get_object_or_404(Notification, pk=pk, user_sub=user.sub)
        n.read = True
        n.save(update_fields=["read"])
        return Response(NotificationSerializer(n).data)


class AdditionalAccessCreateView(APIView):
    def post(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        ser = AdditionalAccessSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        claims = _claims_with_groups(user.claims, user.sub)
        user_info = UserInfo.from_claims(claims)
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
                user.sub,
                user_info,
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
        qs = RegistrationRequest.objects.select_related("organisme").all().order_by("-created_at")[:200]
        data = []
        for r in qs:
            data.append(
                {
                    "public_id": str(r.public_id),
                    "status": r.status,
                    "email": r.email,
                    "first_name": r.first_name,
                    "last_name": r.last_name,
                    "fonction": r.remarks,
                    "organisme": r.organisme.nom_organisme if r.organisme else "",
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
        actor = require_keycloak_user(request)
        if not actor:
            return Response(status=401)
        try:
            workflows.super_admin_approve(r, actor.sub)
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
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        groups = _request_groups(request)
        admin_slugs = admin_application_slugs(groups)
        if is_super_admin(groups):
            reg_items = AccessRequestItem.objects.filter(
                status=AccessRequestItem.STATUS_PENDING,
                registration__status=RegistrationRequest.STATUS_PENDING_APPS,
                origin=AccessRequestItem.ORIGIN_REGISTRATION,
            ).select_related("application", "registration")
        else:
            if not admin_slugs:
                return Response([])
            reg_items = AccessRequestItem.objects.filter(
                status=AccessRequestItem.STATUS_PENDING,
                registration__status=RegistrationRequest.STATUS_PENDING_APPS,
                application__slug__in=admin_slugs,
                origin=AccessRequestItem.ORIGIN_REGISTRATION,
            ).select_related("application", "registration")
        out = []
        for i in reg_items:
            if not is_super_admin(groups) and not is_app_admin(groups, i.application):
                continue
            out.append(
                {
                    "kind": "registration",
                    "item_id": i.pk,
                    "application": ApplicationSerializer(i.application).data,
                    "registration_public_id": str(i.registration.public_id),
                    "applicant_email": i.registration.email,
                    "applicant_first_name": i.registration.first_name,
                    "applicant_last_name": i.registration.last_name,
                    "request_justification": i.request_justification,
                }
            )
        add_qs = AccessRequestItem.objects.filter(
            status=AccessRequestItem.STATUS_PENDING,
            origin=AccessRequestItem.ORIGIN_ADDITIONAL,
            registration__isnull=True,
        ).select_related("application")
        for i in add_qs:
            if not is_app_admin(groups, i.application):
                continue
            applicant = fetch_user_info(i.user_sub) if i.user_sub else None
            out.append(
                {
                    "kind": "additional",
                    "item_id": i.pk,
                    "application": ApplicationSerializer(i.application).data,
                    "request_public_id": str(i.request_public_id),
                    "applicant_email": applicant.email if applicant else "",
                    "applicant_first_name": applicant.first_name if applicant else "",
                    "applicant_last_name": applicant.last_name if applicant else "",
                    "request_justification": i.request_justification,
                }
            )
        return Response(out)


class AdminMyValidationApplicationsView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def get(self, request):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        groups = _request_groups(request)
        if is_super_admin(groups):
            apps = Application.objects.filter(requires_access_request=True).order_by("nom")
            return Response(ApplicationSerializer(apps, many=True).data)
        slugs = admin_application_slugs(groups)
        apps = Application.objects.filter(slug__in=slugs, requires_access_request=True).order_by("nom")
        return Response(ApplicationSerializer(apps, many=True).data)


class AdminDecideRegistrationItemView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, item_id, decision):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        item = get_object_or_404(AccessRequestItem, pk=item_id)
        groups = _request_groups(request)
        if not is_app_admin(groups, item.application):
            return Response(status=403)
        approve = decision == "approve"
        try:
            workflows.app_admin_decide_item(item, approve, user.sub, request.data.get("note", ""))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"ok": True})


class AdminDecideAdditionalItemView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, item_id, decision):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        item = get_object_or_404(
            AccessRequestItem, pk=item_id, origin=AccessRequestItem.ORIGIN_ADDITIONAL, registration__isnull=True
        )
        groups = _request_groups(request)
        if not is_app_admin(groups, item.application):
            return Response(status=403)
        approve = decision == "approve"
        try:
            workflows.app_admin_decide_additional_item(item, approve, user.sub, request.data.get("note", ""))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"ok": True})


class AdminRevokeAccessView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def post(self, request, application_slug, user_sub):
        user = require_keycloak_user(request)
        if not user:
            return Response(status=401)
        app = get_object_or_404(Application, slug=application_slug)
        groups = _request_groups(request)
        if not is_app_admin(groups, app):
            return Response(status=403)
        target_sub = (user_sub or "").strip()
        if not target_sub:
            return Response({"detail": "Utilisateur invalide"}, status=400)
        from inscriptions.services import provisioning as prov

        kc = KeycloakAdminClient()
        try:
            prov.revoke_application_access(kc, target_sub, app)
        except Exception:
            logger.exception("revoke keycloak")
        return Response({"ok": True})


class AdminApplicationCatalogListCreateView(APIView):
    """Super-admin : consulter et créer des applications du catalogue."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        apps = Application.objects.all().order_by("nom")
        return Response(ApplicationCatalogSerializer(apps, many=True).data)

    def post(self, request):
        ser = AdminApplicationWriteSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        app = ser.save()
        return Response(ApplicationCatalogSerializer(app).data, status=status.HTTP_201_CREATED)


class AdminApplicationCatalogRefreshCountsView(APIView):
    """Super-admin : actualiser les effectifs Keycloak (utilisateurs + admins) et les persister."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, application_slug=None):
        if not settings.KEYCLOAK_SYNC_ENABLED:
            return Response(
                {"detail": "Synchronisation Keycloak désactivée."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            kc = KeycloakAdminClient()
        except Exception:
            logger.exception("keycloak client init for refresh counts")
            return Response({"detail": "Keycloak indisponible."}, status=status.HTTP_502_BAD_GATEWAY)

        if application_slug:
            apps = [get_object_or_404(Application, slug=application_slug)]
        else:
            apps = list(Application.objects.all().order_by("nom"))

        refreshed: list[Application] = []
        for app in apps:
            try:
                refreshed.append(app_access_svc.refresh_application_access_counts(app, kc))
            except KeycloakAdminError as exc:
                logger.warning("Refresh effectifs %s impossible: %s", app.slug, exc)
                return Response(
                    {"detail": f"Échec du comptage pour {app.slug}."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        data = ApplicationCatalogSerializer(refreshed, many=True).data
        if application_slug:
            return Response(data[0] if data else {})
        return Response({"applications": data})


class AdminApplicationCatalogDetailView(APIView):
    """Super-admin : consulter et modifier une application du catalogue."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        return Response(ApplicationSerializer(app).data)

    def put(self, request, application_slug):
        return self._update(request, application_slug, partial=False)

    def patch(self, request, application_slug):
        return self._update(request, application_slug, partial=True)

    def _update(self, request, application_slug, *, partial: bool):
        app = get_object_or_404(Application, slug=application_slug)
        ser = AdminApplicationWriteSerializer(app, data=request.data, partial=partial)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        app = ser.save()
        return Response(ApplicationSerializer(app).data)


class AdminApplicationCatalogAdminsView(APIView):
    """Super-admin : gérer les administrateurs d'une application depuis le catalogue."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        return Response(app_admins_svc.list_application_admins(app))

    def put(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        subs = request.data.get("keycloak_subs")
        if not isinstance(subs, list):
            return Response({"detail": "keycloak_subs (liste) requis"}, status=400)
        try:
            admins = app_admins_svc.replace_application_admins(app, subs)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=404)
        return Response({"admins": admins})

    def post(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        keycloak_sub = (request.data.get("keycloak_sub") or "").strip()
        email = (request.data.get("email") or "").strip().lower()
        if not keycloak_sub and not email:
            return Response({"detail": "keycloak_sub ou email requis"}, status=400)
        try:
            admin = app_admins_svc.add_application_admin(app, keycloak_sub=keycloak_sub, email=email)
        except ValueError:
            return Response({"detail": "Utilisateur introuvable"}, status=404)
        return Response(admin, status=201)


class AdminApplicationCatalogAdminRemoveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def delete(self, request, application_slug, user_sub):
        app = get_object_or_404(Application, slug=application_slug)
        app_admins_svc.remove_application_admin(app, user_sub)
        return Response(status=204)


class AdminApplicationCatalogImageView(APIView):
    """Super-admin : importer ou supprimer l'image d'une application."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        uploaded = request.FILES.get("image")
        if not uploaded:
            return Response({"detail": "Fichier image requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            save_application_image(app, uploaded)
        except ApplicationImageError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except OSError:
            logger.exception("Écriture image application %s", application_slug)
            return Response({"detail": "Impossible d'enregistrer l'image."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        app.refresh_from_db()
        return Response(ApplicationSerializer(app).data)

    def delete(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        try:
            remove_application_image(app)
        except ApplicationImageError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except OSError:
            logger.exception("Suppression image application %s", application_slug)
            return Response({"detail": "Impossible de supprimer l'image."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        app.refresh_from_db()
        return Response(ApplicationSerializer(app).data)


def _parse_positive_int(value, default: int, *, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _parse_keycloak_subs(data) -> list[str]:
    raw_list = data.get("keycloak_subs")
    if isinstance(raw_list, list):
        return [(str(s) or "").strip() for s in raw_list if (str(s) or "").strip()]
    single = (data.get("keycloak_sub") or "").strip()
    return [single] if single else []


class AdminApplicationCatalogDualMembersView(APIView):
    """Super-admin : lister en une fois tous les utilisateurs des deux côtés du dual-listbox."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        if not app_access_svc.is_application_access_editable(app):
            return Response(
                {"detail": "Cette application n'a pas de groupe d'accès géré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            kc = KeycloakAdminClient()
            payload = app_access_svc.list_application_dual_members(kc, app)
        except KeycloakAdminError as exc:
            logger.warning("Liste dual membres application impossible: %s", exc)
            return Response({"detail": "Liste des utilisateurs indisponible"}, status=502)
        return Response(
            {
                "application": ApplicationSerializer(app).data,
                "members": payload["members"],
                "available": payload["available"],
            }
        )


class AdminApplicationCatalogMembersView(APIView):
    """Super-admin : lister et ajouter les membres d'une application."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        if not app_access_svc.is_application_access_editable(app):
            return Response(
                {"detail": "Cette application n'a pas de groupe d'accès géré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        q = (request.query_params.get("q") or "").strip()
        page = _parse_positive_int(request.query_params.get("page"), 1, minimum=1, maximum=10_000)
        page_size = _parse_positive_int(request.query_params.get("page_size"), 10, minimum=1, maximum=100)
        side = (request.query_params.get("side") or "members").strip().lower()
        try:
            kc = KeycloakAdminClient()
            if side == "available":
                payload = app_access_svc.list_application_non_members_page(
                    kc,
                    app,
                    query=q,
                    page=page,
                    page_size=page_size,
                )
            else:
                payload = app_access_svc.list_application_group_members_page(
                    kc,
                    app,
                    query=q,
                    page=page,
                    page_size=page_size,
                )
        except KeycloakAdminError as exc:
            logger.warning("Liste membres application impossible: %s", exc)
            return Response({"detail": "Liste des utilisateurs indisponible"}, status=502)
        payload["application"] = ApplicationSerializer(app).data
        return Response(payload)

    def post(self, request, application_slug):
        from inscriptions.services import provisioning as prov

        app = get_object_or_404(Application, slug=application_slug)
        if not app_access_svc.is_application_access_editable(app):
            return Response(
                {"detail": "Cette application n'a pas de groupe d'accès géré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_subs = _parse_keycloak_subs(request.data)
        if not user_subs:
            return Response({"detail": "keycloak_sub ou keycloak_subs requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            kc = KeycloakAdminClient()
            added = 0
            for user_sub in user_subs:
                kc.get_user(user_sub)
                groups = kc.get_user_groups(user_sub)
                paths = app_access_svc._group_paths(groups)
                if app_access_svc.user_has_application_access(paths, app):
                    continue
                prov.provision_application_access(kc, user_sub, app)
                added += 1
        except KeycloakAdminError as exc:
            logger.warning("Ajout membre application impossible: %s", exc)
            return Response({"detail": "Ajout utilisateur indisponible"}, status=502)
        return Response({"ok": True, "count": added}, status=status.HTTP_201_CREATED)


class AdminApplicationCatalogMembersBulkRemoveView(APIView):
    """Super-admin : retirer plusieurs membres d'une application."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, application_slug):
        from inscriptions.services import provisioning as prov

        app = get_object_or_404(Application, slug=application_slug)
        if not app_access_svc.is_application_access_editable(app):
            return Response(
                {"detail": "Cette application n'a pas de groupe d'accès géré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_subs = _parse_keycloak_subs(request.data)
        if not user_subs:
            return Response({"detail": "keycloak_subs requis."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            kc = KeycloakAdminClient()
            removed = 0
            for user_sub in user_subs:
                kc.get_user(user_sub)
                prov.revoke_application_access(kc, user_sub, app)
                removed += 1
        except KeycloakAdminError as exc:
            logger.warning("Retrait membre application impossible: %s", exc)
            return Response({"detail": "Retrait utilisateur indisponible"}, status=502)
        return Response({"ok": True, "count": removed})


class AdminApplicationCatalogMemberRemoveView(APIView):
    """Super-admin : retirer un membre d'une application."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def delete(self, request, application_slug, user_sub):
        from inscriptions.services import provisioning as prov

        app = get_object_or_404(Application, slug=application_slug)
        if not app_access_svc.is_application_access_editable(app):
            return Response(
                {"detail": "Cette application n'a pas de groupe d'accès géré."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user_sub = (user_sub or "").strip()
        if not user_sub:
            return Response({"detail": "Utilisateur invalide."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            kc = KeycloakAdminClient()
            kc.get_user(user_sub)
            prov.revoke_application_access(kc, user_sub, app)
        except KeycloakAdminError as exc:
            logger.warning("Retrait membre application impossible: %s", exc)
            return Response({"detail": "Retrait utilisateur indisponible"}, status=502)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminApplicationAdminsView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        apps = Application.objects.filter(managed_by_si=True, requires_access_request=True).order_by("nom")
        out = []
        for app in apps:
            out.append(
                {
                    "application": ApplicationSerializer(app).data,
                    "admins": app_admins_svc.list_application_admins(app),
                }
            )
        return Response(out)


class AdminApplicationAdminAssignView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, application_slug):
        app = get_object_or_404(Application, slug=application_slug)
        keycloak_sub = (request.data.get("keycloak_sub") or "").strip()
        email = (request.data.get("email") or "").strip().lower()
        if not keycloak_sub and not email:
            return Response({"detail": "keycloak_sub ou email requis"}, status=400)
        try:
            admin = app_admins_svc.add_application_admin(app, keycloak_sub=keycloak_sub, email=email)
        except ValueError:
            return Response({"detail": "Utilisateur introuvable"}, status=404)
        return Response({"ok": True, "admin": admin}, status=201)


class AdminApplicationAdminRemoveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def delete(self, request, application_slug, user_sub):
        app = get_object_or_404(Application, slug=application_slug)
        app_admins_svc.remove_application_admin(app, user_sub)
        return Response(status=204)


class AdminUserApplicationAccessView(APIView):
    """Super-admin : consulter et modifier les accès applicatifs d'un utilisateur Keycloak."""

    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request, user_sub):
        user_sub = (user_sub or "").strip()
        if not user_sub:
            return Response({"detail": "Utilisateur invalide"}, status=400)
        try:
            kc = KeycloakAdminClient()
            kc_user = kc.get_user(user_sub)
            groups = kc.get_user_groups(user_sub)
        except KeycloakAdminError as exc:
            logger.warning("Lecture accès utilisateur Keycloak impossible: %s", exc)
            return Response({"detail": "Utilisateur Keycloak introuvable ou API indisponible"}, status=502)

        group_paths = app_access_svc._group_paths(groups)
        apps = list(app_access_svc.si_managed_applications())
        pending_ids = app_access_svc.pending_application_ids_for_user(user_sub)
        rows = app_access_svc.build_user_application_access_rows(apps, group_paths, pending_ids)

        email = (kc_user.get("email") or "").strip()
        first_name = (kc_user.get("firstName") or "").strip()
        last_name = (kc_user.get("lastName") or "").strip()
        username = (kc_user.get("username") or "").strip()
        label_name = f"{first_name} {last_name}".strip()
        label = f"{label_name} ({email or username})" if label_name else (email or username)

        return Response(
            {
                "user": {
                    "keycloak_sub": user_sub,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "username": username,
                    "label": label,
                },
                "applications": [
                    {
                        "application": ApplicationSerializer(row["application"]).data,
                        "has_access": row["has_access"],
                        "auto_granted": row["auto_granted"],
                        "editable": row["editable"],
                        "pending_request": row["pending_request"],
                    }
                    for row in rows
                ],
            }
        )

    def put(self, request, user_sub):
        user_sub = (user_sub or "").strip()
        if not user_sub:
            return Response({"detail": "Utilisateur invalide"}, status=400)
        access = request.data.get("access")
        if not isinstance(access, dict):
            return Response({"detail": "Champ access requis (objet slug -> booléen)"}, status=400)

        desired: dict[str, bool] = {}
        for slug, value in access.items():
            if not isinstance(slug, str) or not slug.strip():
                continue
            desired[slug.strip()] = bool(value)

        if not desired:
            return Response({"detail": "Aucune application à modifier"}, status=400)

        try:
            kc = KeycloakAdminClient()
            kc.get_user(user_sub)
            groups = kc.get_user_groups(user_sub)
            current_paths = app_access_svc._group_paths(groups)
            app_access_svc.apply_application_access_changes(kc, user_sub, current_paths, desired)
        except KeycloakAdminError as exc:
            logger.exception("Modification accès Keycloak")
            return Response({"detail": str(exc) or "Échec de la modification Keycloak"}, status=502)

        return self.get(request, user_sub)
