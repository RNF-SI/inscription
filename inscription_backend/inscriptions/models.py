import uuid

from django.db import models


class Organisme(models.Model):
    id_organisme = models.IntegerField(primary_key=True)
    uuid_organisme = models.CharField(max_length=64, blank=True)
    nom_organisme = models.CharField(max_length=500)
    keycloak_slug = models.SlugField(max_length=500, blank=True)

    class Meta:
        db_table = "inscription_organisme"
        ordering = ["nom_organisme"]

    def __str__(self):
        return self.nom_organisme


class Reserve(models.Model):
    area_code = models.CharField(max_length=64, primary_key=True)
    area_name = models.CharField(max_length=500)
    id_type = models.CharField(max_length=32, blank=True)

    class Meta:
        db_table = "inscription_reserve"
        ordering = ["area_name"]

    def __str__(self):
        return f"{self.area_code} — {self.area_name}"


class OrganismeReserveLink(models.Model):
    organisme = models.ForeignKey(Organisme, on_delete=models.CASCADE, related_name="reserve_links")
    reserve = models.ForeignKey(Reserve, on_delete=models.CASCADE, related_name="organisme_links")
    principal = models.BooleanField(default=False)

    class Meta:
        db_table = "inscription_organisme_reserve"
        unique_together = [["organisme", "reserve"]]


class Application(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    nom = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    image = models.CharField(max_length=240, blank=True)
    description = models.TextField(blank=True)
    managed_by_si = models.BooleanField(default=True)
    requires_access_request = models.BooleanField(default=True)
    keycloak_client_id = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "inscription_application"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


class UserProfile(models.Model):
    keycloak_sub = models.CharField(max_length=200, unique=True, db_index=True)
    email = models.EmailField()
    username = models.CharField(max_length=200, blank=True)
    first_name = models.CharField(max_length=200, blank=True)
    last_name = models.CharField(max_length=200, blank=True)
    fonction = models.CharField(max_length=200, blank=True)
    organisme = models.ForeignKey(Organisme, null=True, blank=True, on_delete=models.SET_NULL)
    is_super_admin = models.BooleanField(default=False)
    legacy_id_role = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inscription_user_profile"

    def __str__(self):
        return self.email


class ApplicationAdmin(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="admin_assignments")
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="admins")

    class Meta:
        db_table = "inscription_application_admin"
        unique_together = [["user", "application"]]


class RegistrationRequest(models.Model):
    STATUS_PENDING_SUPER = "pending_super"
    STATUS_SUPER_REJECTED = "super_rejected"
    STATUS_PENDING_APPS = "pending_apps"
    STATUS_PROVISIONING = "provisioning"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING_SUPER, "En attente super-admin"),
        (STATUS_SUPER_REJECTED, "Refusé super-admin"),
        (STATUS_PENDING_APPS, "En attente validateurs applicatifs"),
        (STATUS_PROVISIONING, "Provisioning Keycloak"),
        (STATUS_COMPLETED, "Terminé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING_SUPER)
    email = models.EmailField()
    username = models.CharField(max_length=200)
    password_cipher = models.TextField(blank=True)
    first_name = models.CharField(max_length=200)
    last_name = models.CharField(max_length=200)
    organisme = models.ForeignKey(Organisme, null=True, blank=True, on_delete=models.SET_NULL)
    remarks = models.TextField(blank=True)
    champs_addi = models.JSONField(default=dict, blank=True)
    reserve_codes = models.JSONField(default=list, blank=True)
    keycloak_user_id = models.CharField(max_length=64, blank=True)
    created_profile = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="registration_origins"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inscription_registration_request"
        ordering = ["-created_at"]


class AccessRequestItem(models.Model):
    ORIGIN_REGISTRATION = "registration"
    ORIGIN_ADDITIONAL = "additional"
    ORIGIN_CHOICES = [
        (ORIGIN_REGISTRATION, "Inscription"),
        (ORIGIN_ADDITIONAL, "Demande additionnelle"),
    ]

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    registration = models.ForeignKey(
        RegistrationRequest, on_delete=models.CASCADE, related_name="items", null=True, blank=True
    )
    user = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.CASCADE, related_name="access_requests")
    application = models.ForeignKey(Application, on_delete=models.CASCADE)
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default=ORIGIN_REGISTRATION)
    request_public_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="item_decisions"
    )
    request_justification = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "inscription_access_request_item"


class AdditionalAccessRequest(models.Model):
    STATUS_PENDING_APPS = "pending_apps"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING_APPS, "En attente validateurs"),
        (STATUS_COMPLETED, "Terminé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="additional_access_requests")
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING_APPS)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inscription_additional_access_request"


class AdditionalAccessItem(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    request = models.ForeignKey(AdditionalAccessRequest, on_delete=models.CASCADE, related_name="items")
    application = models.ForeignKey(Application, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="additional_item_decisions"
    )
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "inscription_additional_access_item"


class UserApplicationAccess(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_PENDING = "pending"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Actif"),
        (STATUS_REVOKED, "Révoqué"),
        (STATUS_PENDING, "En attente"),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="app_access")
    application = models.ForeignKey(Application, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    source_item = models.ForeignKey(
        AccessRequestItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="granted_access"
    )
    source_additional_item = models.ForeignKey(
        AdditionalAccessItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_access",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inscription_user_application_access"
        unique_together = [["user", "application"]]


class UserReserveLink(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="reserve_links")
    reserve = models.ForeignKey(Reserve, on_delete=models.CASCADE)
    referent = models.BooleanField(default=False)
    referent_valid = models.BooleanField(default=False)

    class Meta:
        db_table = "inscription_user_reserve_link"
        unique_together = [["user", "reserve"]]


class ReserveReferentRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="referent_requests")
    reserve = models.ForeignKey(Reserve, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="referent_decisions"
    )

    class Meta:
        db_table = "inscription_reserve_referent_request"


class ReserveMemberRemovalRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    reserve = models.ForeignKey(Reserve, on_delete=models.CASCADE, related_name="member_removal_requests")
    requester = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="member_removal_requests")
    target_sub = models.CharField(max_length=200, db_index=True)
    target_email = models.EmailField(blank=True)
    target_first_name = models.CharField(max_length=200, blank=True)
    target_last_name = models.CharField(max_length=200, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="member_removal_decisions"
    )
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_reserve_member_removal_request"
        ordering = ["-created_at"]


class Notification(models.Model):
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_notification"
        ordering = ["-created_at"]


class AuditLog(models.Model):
    actor_sub = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_audit_log"
        ordering = ["-created_at"]
