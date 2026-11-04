import uuid

from django.db import models
from django.utils import timezone


class Organisme(models.Model):
    id_organisme = models.IntegerField(primary_key=True)
    uuid_organisme = models.CharField(max_length=64, blank=True)
    nom_organisme = models.CharField(max_length=500)
    keycloak_slug = models.SlugField(max_length=500, blank=True)
    # Identifiant de l'organisme dans RADIS, posé par « synchro_radis » le jour où
    # l'uuid_organisme a permis de les rapprocher. Nul pour les organismes que RADIS
    # ne connaît pas : ceux-là ne gèrent pas de réserve, et la synchronisation ne doit
    # jamais les toucher. C'est donc ce champ, et non l'absence d'un organisme de la
    # réponse de RADIS, qui dit si la comparaison a un sens.
    radis_id = models.IntegerField(null=True, blank=True, unique=True)

    class Meta:
        db_table = "inscription_organisme"
        ordering = ["nom_organisme"]

    def __str__(self):
        return self.nom_organisme


class Reserve(models.Model):
    area_code = models.CharField(max_length=64, primary_key=True)
    area_name = models.CharField(max_length=500)
    # ref_geo.l_areas.id_type, hérité de l'import de la base historique. RADIS ne le
    # connaît pas : il expose un type littéral, repris dans type_rn ci-dessous.
    id_type = models.CharField(max_length=32, blank=True)
    type_rn = models.CharField(max_length=3, blank=True)

    # RADIS ne supprime pas une réserve sortie du réseau, il la déclasse — et la
    # plateforme fait de même : les groupes Keycloak /reserves/<code> et les lignes
    # complement_rnf.cor_role_rn de ses membres existent toujours. Supprimer la ligne
    # rendrait ces rattachements illisibles ; la réserve est seulement retirée des
    # listes où l'on se rattache.
    ancienne_reserve = models.BooleanField(default=False)
    date_declassement = models.DateField(null=True, blank=True)

    # Réserve que RADIS connaît mais qui manque à ref_geo.l_areas de la base
    # historique. Elle ne doit pas être proposée : cor_role_rn.rn_id est une clé
    # étrangère vers l_areas.area_code, et c'est un trigger qui l'alimente à l'INSERT
    # de t_roles. Un inscrit qui cocherait cette réserve ferait échouer la création de
    # son compte tout entière. Posé par « synchro_radis » quand la base historique est
    # joignable, laissé tel quel sinon.
    absente_ref_geo = models.BooleanField(default=False)

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
    # N'a de sens que si requires_access_request est faux : l'accès n'est alors
    # pas demandé mais déduit de l'appartenance à une réserve. Côté Keycloak c'est
    # le rôle « access » du client mappé sur le groupe parent /reserves, hérité par
    # tous les sous-groupes (voir docs/runbook-cutover.txt § 1.1).
    reserve_members_only = models.BooleanField(default=False)
    keycloak_client_id = models.CharField(max_length=200, blank=True)
    keycloak_member_count = models.IntegerField(null=True, blank=True)
    keycloak_admin_count = models.IntegerField(null=True, blank=True)
    keycloak_counts_updated_at = models.DateTimeField(null=True, blank=True)

    # Correspondance vers la base historique, pour l'écriture miroir.
    # Une application dont legacy_id_application est vide n'écrit rien côté legacy :
    # le déploiement peut précéder le renseignement de ces valeurs.
    legacy_id_application = models.IntegerField(
        null=True,
        blank=True,
        help_text="utilisateurs.t_applications.id_application",
    )
    legacy_id_profil = models.IntegerField(
        default=1,
        help_text="utilisateurs.t_profils.id_profil ; 1 = Lecteur, ce qu'accordait UsersHub",
    )
    legacy_group_id_role = models.IntegerField(
        null=True,
        blank=True,
        help_text="utilisateurs.t_roles.id_role du groupe (groupe=true) à alimenter dans cor_roles",
    )

    class Meta:
        db_table = "inscription_application"
        ordering = ["nom"]

    def __str__(self):
        return self.nom


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
    keycloak_user_id = models.CharField(max_length=64, blank=True, db_index=True)
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
    user_sub = models.CharField(max_length=200, blank=True, db_index=True)
    application = models.ForeignKey(Application, on_delete=models.CASCADE)
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES, default=ORIGIN_REGISTRATION)
    request_public_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_sub = models.CharField(max_length=200, blank=True)
    request_justification = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "inscription_access_request_item"


class ReserveReferentRequest(models.Model):
    """Demande en attente de statut référent. Supprimée dès validation (vérité = Keycloak)."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "En attente"),
        (STATUS_APPROVED, "Approuvé"),
        (STATUS_REJECTED, "Refusé"),
    ]

    user_sub = models.CharField(max_length=200, db_index=True)
    reserve = models.ForeignKey(Reserve, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_sub = models.CharField(max_length=200, blank=True)

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
    requester_sub = models.CharField(max_length=200, db_index=True)
    target_sub = models.CharField(max_length=200, db_index=True)
    target_email = models.EmailField(blank=True)
    target_first_name = models.CharField(max_length=200, blank=True)
    target_last_name = models.CharField(max_length=200, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_sub = models.CharField(max_length=200, blank=True)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_reserve_member_removal_request"
        ordering = ["-created_at"]


class Notification(models.Model):
    user_sub = models.CharField(max_length=200, db_index=True)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)
    read = models.BooleanField(default=False)
    admin_tab = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_notification"
        ordering = ["-created_at"]


class PasswordResetToken(models.Model):
    """Jeton de réinitialisation de mot de passe, à usage unique et daté.

    Seule l'empreinte SHA-256 du jeton est conservée : une fuite de cette table ne
    doit pas suffire à réinitialiser des comptes. Le jeton en clair n'existe que dans
    le lien envoyé par e-mail.
    """

    token_hash = models.CharField(max_length=64, unique=True)
    user_sub = models.CharField(max_length=200, db_index=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "inscription_password_reset_token"
        ordering = ["-created_at"]

    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class AuditLog(models.Model):
    actor_sub = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscription_audit_log"
        ordering = ["-created_at"]
