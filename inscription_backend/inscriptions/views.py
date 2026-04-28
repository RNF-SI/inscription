from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from inscriptions.authentication import KeycloakUser, require_profile
from inscriptions.keycloak_client import KeycloakAdminClient, KeycloakAdminError
from inscriptions.models import (
    AccessRequestItem,
    Application,
    ApplicationAdmin,
    Notification,
    Organisme,
    ReserveMemberRemovalRequest,
    ReserveReferentRequest,
    RegistrationRequest,
    Reserve,
    UserProfile,
)
from inscriptions.permissions import IsKeycloakAuthenticated, IsSuperAdmin, is_app_admin
from inscriptions.serializers import (
    AdditionalAccessSerializer,
    ApplicationSerializer,
    MeUpdateSerializer,
    NotificationSerializer,
    OrganismeDetailSerializer,
    OrganismeSerializer,
    ReserveSerializer,
    SignupSerializer,
)
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


def _is_admin_user(profile: UserProfile) -> bool:
    return bool(profile.is_super_admin or ApplicationAdmin.objects.filter(user=profile).exists())


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
    def patch(self, request):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)

        ser = MeUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        if not data:
            return Response({"detail": "Aucune modification fournie."}, status=400)

        try:
            kc = KeycloakAdminClient()
            kc.update_user_profile(
                prof.keycloak_sub,
                username=data.get("username"),
                email=data.get("email"),
                first_name=data.get("first_name"),
                last_name=data.get("last_name"),
                function_value=data.get("fonction"),
            )
        except KeycloakAdminError as exc:
            logger.warning("Me patch keycloak failed: %s", exc)
            return Response({"detail": "Mise à jour Keycloak impossible."}, status=502)

        # Sync local technique/fallback
        if "username" in data:
            prof.username = data["username"]
        if "email" in data:
            prof.email = data["email"]
        if "first_name" in data:
            prof.first_name = data["first_name"]
        if "last_name" in data:
            prof.last_name = data["last_name"]
        if "fonction" in data:
            prof.fonction = data["fonction"]
        prof.save(update_fields=["username", "email", "first_name", "last_name", "fonction", "updated_at"])

        # Retourne la vue /me à jour.
        return self.get(request)

    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
        org_group_path = _first_organisme_group_path(claims)
        profile_data = {
            "keycloak_sub": claims.get("sub") or prof.keycloak_sub,
            "email": claims.get("email") or prof.email,
            "username": claims.get("preferred_username") or claims.get("username") or prof.username,
            "first_name": claims.get("given_name") or claims.get("first_name") or prof.first_name,
            "last_name": claims.get("family_name") or claims.get("last_name") or prof.last_name,
            # Les droits applicatifs restent gérés côté backend local.
            "is_super_admin": prof.is_super_admin,
            "legacy_id_role": prof.legacy_id_role,
            # Priorité au claim Keycloak "function", fallback legacy "fonction".
            "fonction": (claims.get("function") or claims.get("fonction") or "").strip(),
            # Nom d'organisme resolu depuis le groupe Keycloak (attribut nom_organisme).
            "organisme": (
                _organisme_name_from_group_path(org_group_path)
                or (claims.get("organisme_name") or claims.get("organisme") or "").strip()
            ),
        }
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
        reserve_codes = _reserve_codes_from_token(claims)
        referent_codes = set(_referent_reserve_codes_from_token(claims))
        pending_referent_codes = set(
            ReserveReferentRequest.objects.filter(
                user=prof,
                status=ReserveReferentRequest.STATUS_PENDING,
            ).values_list("reserve_id", flat=True)
        )
        reserve_by_code = {r.area_code: r for r in Reserve.objects.filter(area_code__in=reserve_codes)}
        reserves = []
        for code in reserve_codes:
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
        is_app_admin = ApplicationAdmin.objects.filter(user=prof).exists()
        return Response(
            {
                "profile": profile_data,
                "applications": out,
                "reserves": reserves,
                "is_app_admin": is_app_admin,
                "unread_notifications": Notification.objects.filter(user=prof, read=False).count(),
            }
        )


class MeReserveOptionsView(APIView):
    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
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
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
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
            kc.user_join_group(prof.keycloak_sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Ajout groupe reserve keycloak impossible: %s", exc)
            return Response({"detail": "Ajout de la réserve impossible côté Keycloak"}, status=502)
        return Response({"ok": True}, status=201)

    def delete(self, request, area_code):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)
        try:
            kc = KeycloakAdminClient()
            gid = kc.ensure_reserve_group(reserve.area_code)
            kc.user_leave_group(prof.keycloak_sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Suppression groupe reserve keycloak impossible: %s", exc)
            return Response({"detail": "Suppression de la réserve impossible côté Keycloak"}, status=502)
        return Response(status=204)


class MeReserveReferentRequestView(APIView):
    def post(self, request, area_code):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)

        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
        reserve_codes = set(_reserve_codes_from_token(claims))
        if area_code not in reserve_codes:
            return Response({"detail": "Vous devez être membre de la réserve"}, status=403)

        referent_codes = set(_referent_reserve_codes_from_token(claims))
        if area_code in referent_codes:
            return Response({"detail": "Vous êtes déjà référent de cette réserve"}, status=400)

        already_pending = ReserveReferentRequest.objects.filter(
            user=prof,
            reserve=reserve,
            status=ReserveReferentRequest.STATUS_PENDING,
        ).exists()
        if already_pending:
            return Response({"detail": "Une demande est déjà en attente pour cette réserve"}, status=400)

        req = ReserveReferentRequest.objects.create(user=prof, reserve=reserve)
        admins = {u.keycloak_sub: u for u in UserProfile.objects.filter(is_super_admin=True)}
        for u in UserProfile.objects.filter(admin_assignments__isnull=False).distinct():
            admins[u.keycloak_sub] = u
        for u in admins.values():
            Notification.objects.create(
                user=u,
                title=f"Demande référent : {reserve.area_code}",
                body=(
                    f"{prof.first_name} {prof.last_name} ({prof.email}) demande le statut référent "
                    f"pour la réserve {reserve.area_name}."
                ),
            )
        return Response({"id": req.id, "status": req.status}, status=201)


class MeReferentReservesMembersView(APIView):
    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
        referent_codes = _referent_reserve_codes_from_token(claims)
        if prof.is_super_admin:
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
                    requester=prof,
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
                    "can_request_removal": (not prof.is_super_admin) and (code in set(referent_codes)),
                    "can_direct_remove": prof.is_super_admin,
                    "can_direct_add": prof.is_super_admin,
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
        prof = require_profile(request)
        if not prof:
            return Response({"detail": "Non authentifié"}, status=401)
        claims = getattr(request.user, "claims", {}) if isinstance(request.user, KeycloakUser) else {}
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
        if target_sub == prof.keycloak_sub:
            return Response({"detail": "Vous ne pouvez pas demander votre propre retrait."}, status=400)

        existing = ReserveMemberRemovalRequest.objects.filter(
            reserve=reserve,
            requester=prof,
            target_sub=target_sub,
            status=ReserveMemberRemovalRequest.STATUS_PENDING,
        ).exists()
        if existing:
            return Response({"detail": "Une demande est déjà en attente pour ce membre"}, status=400)

        req = ReserveMemberRemovalRequest.objects.create(
            reserve=reserve,
            requester=prof,
            target_sub=target_sub,
            target_email=(request.data.get("target_email") or "").strip(),
            target_first_name=(request.data.get("target_first_name") or "").strip(),
            target_last_name=(request.data.get("target_last_name") or "").strip(),
            reason=reason,
        )

        admin_profiles = UserProfile.objects.filter(is_super_admin=True)
        app_admin_profiles = UserProfile.objects.filter(admin_assignments__isnull=False).distinct()
        recipients = {u.keycloak_sub: u for u in list(admin_profiles) + list(app_admin_profiles)}
        for u in recipients.values():
            Notification.objects.create(
                user=u,
                title=f"Demande retrait membre : {reserve.area_code}",
                body=(
                    f"{prof.first_name} {prof.last_name} demande le retrait de "
                    f"{req.target_first_name} {req.target_last_name} ({req.target_email}) "
                    f"de la réserve {reserve.area_name}. Motif: {reason}"
                ),
            )
        return Response({"id": req.id, "status": req.status}, status=201)


class AdminReserveMemberRemovalRequestsView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        qs = ReserveMemberRemovalRequest.objects.filter(
            status=ReserveMemberRemovalRequest.STATUS_PENDING
        ).select_related("reserve", "requester")
        out = []
        for r in qs:
            out.append(
                {
                    "id": r.id,
                    "reserve": {"area_code": r.reserve.area_code, "area_name": r.reserve.area_name},
                    "requester_email": r.requester.email,
                    "requester_name": f"{r.requester.first_name} {r.requester.last_name}".strip(),
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
        prof = require_profile(request)
        if not prof:
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
        req.decided_by = prof
        req.decided_at = timezone.now()
        req.decision_note = note
        req.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])

        Notification.objects.create(
            user=req.requester,
            title=f"Demande retrait membre : {req.reserve.area_code}",
            body=(
                "Votre demande a été acceptée."
                if approve
                else f"Votre demande a été refusée. Motif: {note}"
            ),
        )
        return Response({"ok": True})


class AdminReserveMemberDirectRemoveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, area_code, user_sub):
        prof = require_profile(request)
        if not prof:
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
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        reserve = Reserve.objects.filter(area_code=area_code).first()
        if not reserve:
            return Response({"detail": "Réserve introuvable"}, status=404)

        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "email requis"}, status=400)
        user = UserProfile.objects.filter(email__iexact=email).first()
        if not user:
            return Response({"detail": "Utilisateur introuvable pour cet email"}, status=404)

        try:
            kc = KeycloakAdminClient()
            gid = kc.ensure_reserve_group(reserve.area_code)
            kc.user_join_group(user.keycloak_sub, gid)
        except KeycloakAdminError as exc:
            logger.warning("Ajout direct membre reserve impossible: %s", exc)
            return Response({"detail": "Échec de l'ajout côté Keycloak"}, status=502)

        return Response({"ok": True})


class AdminKeycloakUsersSearchView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        prof = require_profile(request)
        if not prof:
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
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        qs = ReserveReferentRequest.objects.filter(status=ReserveReferentRequest.STATUS_PENDING).select_related(
            "user", "reserve"
        )
        out = []
        for r in qs:
            out.append(
                {
                    "id": r.id,
                    "reserve": {"area_code": r.reserve.area_code, "area_name": r.reserve.area_name},
                    "user_sub": r.user.keycloak_sub,
                    "user_email": r.user.email,
                    "user_first_name": r.user.first_name,
                    "user_last_name": r.user.last_name,
                    "user_fonction": r.user.fonction,
                }
            )
        return Response(out)


class AdminDecideReserveReferentRequestView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, req_id, decision):
        prof = require_profile(request)
        if not prof:
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
                kc.user_join_group(req.user.keycloak_sub, gid)
            except KeycloakAdminError as exc:
                logger.warning("Validation referent impossible côté Keycloak: %s", exc)
                return Response({"detail": "Échec côté Keycloak"}, status=502)

        req.status = ReserveReferentRequest.STATUS_APPROVED if approve else ReserveReferentRequest.STATUS_REJECTED
        req.decided_by = prof
        req.decided_at = timezone.now()
        req.save(update_fields=["status", "decided_by", "decided_at"])

        Notification.objects.create(
            user=req.user,
            title=f"Demande référent : {req.reserve.area_code}",
            body=(
                "Votre demande de statut référent a été acceptée."
                if approve
                else f"Votre demande de statut référent a été refusée. Motif: {note}"
            ),
        )
        return Response({"ok": True})


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
                    "applicant_first_name": i.registration.first_name,
                    "applicant_last_name": i.registration.last_name,
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
                    "applicant_first_name": i.user.first_name if i.user else "",
                    "applicant_last_name": i.user.last_name if i.user else "",
                    "request_justification": i.request_justification,
                }
            )
        return Response(out)


class AdminMyValidationApplicationsView(APIView):
    permission_classes = [IsKeycloakAuthenticated]

    def get(self, request):
        prof = require_profile(request)
        if not prof:
            return Response(status=401)
        if prof.is_super_admin:
            apps = Application.objects.filter(requires_access_request=True).order_by("nom")
            return Response(ApplicationSerializer(apps, many=True).data)
        app_ids = ApplicationAdmin.objects.filter(user=prof).values_list("application_id", flat=True)
        apps = Application.objects.filter(id__in=app_ids, requires_access_request=True).order_by("nom")
        return Response(ApplicationSerializer(apps, many=True).data)


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


class AdminApplicationAdminsView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def get(self, request):
        apps = Application.objects.filter(managed_by_si=True, requires_access_request=True).order_by("nom")
        out = []
        for app in apps:
            admins = ApplicationAdmin.objects.filter(application=app).select_related("user").order_by("user__email")
            out.append(
                {
                    "application": ApplicationSerializer(app).data,
                    "admins": [
                        {
                            "keycloak_sub": adm.user.keycloak_sub,
                            "email": adm.user.email,
                            "first_name": adm.user.first_name,
                            "last_name": adm.user.last_name,
                        }
                        for adm in admins
                    ],
                }
            )
        return Response(out)


class AdminApplicationAdminAssignView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def post(self, request, application_slug):
        app = get_object_or_404(
            Application,
            slug=application_slug,
            managed_by_si=True,
            requires_access_request=True,
        )
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "email requis"}, status=400)
        user = UserProfile.objects.filter(email__iexact=email).first()
        if not user:
            return Response({"detail": "Utilisateur introuvable pour cet email"}, status=404)
        ApplicationAdmin.objects.get_or_create(application=app, user=user)
        return Response({"ok": True}, status=201)


class AdminApplicationAdminRemoveView(APIView):
    permission_classes = [IsKeycloakAuthenticated, IsSuperAdmin]

    def delete(self, request, application_slug, user_sub):
        app = get_object_or_404(
            Application,
            slug=application_slug,
            managed_by_si=True,
            requires_access_request=True,
        )
        user = get_object_or_404(UserProfile, keycloak_sub=user_sub)
        ApplicationAdmin.objects.filter(application=app, user=user).delete()
        return Response(status=204)
