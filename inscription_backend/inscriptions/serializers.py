from __future__ import annotations

import re

from django.db import transaction
from rest_framework import serializers

from inscriptions.crypto_util import encrypt_text
from inscriptions.models import (
    Application,
    Notification,
    Organisme,
    RegistrationRequest,
    Reserve,
)


class OrganismeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisme
        fields = ("id_organisme", "uuid_organisme", "nom_organisme", "keycloak_slug")


class ReserveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reserve
        fields = ("area_code", "area_name", "id_type")


class OrganismeDetailSerializer(serializers.ModelSerializer):
    rns = serializers.SerializerMethodField()

    class Meta:
        model = Organisme
        fields = ("id_organisme", "uuid_organisme", "nom_organisme", "keycloak_slug", "rns")

    def get_rns(self, obj):
        links = obj.reserve_links.select_related("reserve").all()
        return [{"rn": ReserveSerializer(l.reserve).data, "principal": l.principal} for l in links]


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = (
            "slug",
            "nom",
            "url",
            "image",
            "description",
            "managed_by_si",
            "requires_access_request",
            "keycloak_client_id",
        )


class ApplicationCatalogSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(source="keycloak_member_count", read_only=True, allow_null=True)
    admin_count = serializers.IntegerField(source="keycloak_admin_count", read_only=True, allow_null=True)
    counts_updated_at = serializers.DateTimeField(source="keycloak_counts_updated_at", read_only=True, allow_null=True)

    class Meta:
        model = Application
        fields = (
            "slug",
            "nom",
            "url",
            "image",
            "description",
            "managed_by_si",
            "requires_access_request",
            "keycloak_client_id",
            "member_count",
            "admin_count",
            "counts_updated_at",
        )


class AdminApplicationWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = (
            "slug",
            "nom",
            "url",
            "image",
            "description",
            "managed_by_si",
            "requires_access_request",
            "keycloak_client_id",
        )
        extra_kwargs = {
            "url": {"required": False, "allow_blank": True},
            "image": {"read_only": True},
            "description": {"required": False, "allow_blank": True},
            "keycloak_client_id": {"required": False, "allow_blank": True},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None:
            self.fields["slug"].read_only = True

    def validate_slug(self, value):
        slug = (value or "").strip().lower()
        if not slug:
            raise serializers.ValidationError("Slug requis.")
        qs = Application.objects.filter(slug=slug)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Ce slug existe déjà.")
        return slug

    def validate(self, attrs):
        attrs["nom"] = (attrs.get("nom") or "").strip()
        if not attrs["nom"]:
            raise serializers.ValidationError({"nom": "Nom requis."})
        for field in ("url", "description", "keycloak_client_id"):
            if field in attrs and attrs[field] is not None:
                attrs[field] = str(attrs[field]).strip()
        return attrs


class SignupItemSerializer(serializers.Serializer):
    application_slug = serializers.SlugField()
    justification = serializers.CharField(required=False, allow_blank=True)


class SignupSerializer(serializers.Serializer):
    nom_role = serializers.CharField()
    prenom_role = serializers.CharField()
    identifiant = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirmation = serializers.CharField(write_only=True)
    remarques = serializers.CharField(allow_blank=True)
    id_organisme = serializers.IntegerField(required=False, allow_null=True)
    organisme = serializers.CharField(required=False, allow_blank=True)
    champs_addi = serializers.DictField(required=False, default=dict)
    applications = SignupItemSerializer(many=True, required=False, default=list)

    def run_validation(self, data=serializers.empty):
        if data is serializers.empty or not isinstance(data, dict):
            return super().run_validation(data)
        data = {**data}
        # Le front envoie souvent "" quand l’organisme est saisi en texte libre (sans id liste).
        raw_org = data.get("id_organisme")
        if raw_org in ("", None):
            data["id_organisme"] = None
        elif isinstance(raw_org, str):
            s = raw_org.strip()
            if not s:
                data["id_organisme"] = None
            else:
                try:
                    data["id_organisme"] = int(s)
                except ValueError:
                    data["id_organisme"] = None
        if "champs_addi" in data and not isinstance(data.get("champs_addi"), dict):
            data["champs_addi"] = {}
        if "applications" in data and data["applications"] is None:
            data["applications"] = []
        return super().run_validation(data)

    def validate(self, attrs):
        identifiant = (attrs.get("identifiant") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]+", identifiant):
            raise serializers.ValidationError(
                {"identifiant": "Le login ne doit contenir que des lettres, chiffres, points (.), tirets (-) ou underscores (_)."}
            )
        attrs["identifiant"] = identifiant
        if attrs["password"] != attrs["password_confirmation"]:
            raise serializers.ValidationError({"password_confirmation": "Les mots de passe ne correspondent pas."})
        attrs["remarques"] = (attrs.get("remarques") or "").strip()
        apps = attrs.get("applications") or []
        slugs = [x.get("application_slug") for x in apps if x.get("application_slug")]
        if slugs:
            req_apps = {
                a.slug: a
                for a in Application.objects.filter(slug__in=slugs, requires_access_request=True)
            }
            missing = []
            for item in apps:
                slug = item.get("application_slug")
                if slug in req_apps and not (item.get("justification") or "").strip():
                    missing.append(slug)
            if missing:
                raise serializers.ValidationError(
                    {"applications": f"Justification requise pour: {', '.join(sorted(missing))}"}
                )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from inscriptions.models import AccessRequestItem

        champs = validated_data.get("champs_addi") or {}
        reserve_codes = []
        reserves_val = champs.get("reserves")
        if isinstance(reserves_val, list):
            for r in reserves_val:
                if isinstance(r, dict) and r.get("id"):
                    reserve_codes.append(str(r["id"]))
        org_id = validated_data.get("id_organisme")
        organisme = None
        if org_id:
            organisme = Organisme.objects.filter(pk=org_id).first()

        cipher = encrypt_text(validated_data["password"])
        rr = RegistrationRequest.objects.create(
            email=validated_data["email"].lower(),
            username=validated_data["identifiant"],
            password_cipher=cipher,
            first_name=validated_data["prenom_role"],
            last_name=validated_data["nom_role"],
            organisme=organisme,
            remarks=validated_data["remarques"],
            champs_addi=champs,
            reserve_codes=reserve_codes,
        )
        by_slug = {}
        for item in validated_data.get("applications") or []:
            slug = item.get("application_slug")
            if not slug:
                continue
            by_slug[slug] = (item.get("justification") or "").strip()

        for slug, justification in sorted(by_slug.items(), key=lambda x: x[0]):
            app = Application.objects.filter(slug=slug).first()
            if app and app.requires_access_request:
                AccessRequestItem.objects.create(
                    registration=rr,
                    application=app,
                    origin=AccessRequestItem.ORIGIN_REGISTRATION,
                    request_public_id=rr.public_id,
                    request_justification=justification,
                )
        return rr


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ("id", "title", "body", "read", "admin_tab", "created_at")


class MeUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=False, max_length=200)
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    fonction = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_username(self, value: str) -> str:
        username = (value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._@-]+", username):
            raise serializers.ValidationError(
                "L'identifiant ne doit contenir que des lettres, chiffres ou . _ @ -"
            )
        return username

    def validate_email(self, value: str) -> str:
        return (value or "").strip().lower()


class AdditionalAccessSerializer(serializers.Serializer):
    application_slugs = serializers.ListField(child=serializers.SlugField(), min_length=1)
    remarks = serializers.CharField(required=False, allow_blank=True)
