import uuid

from django.db import migrations, models
import django.db.models.deletion


def forwards_unify_items(apps, schema_editor):
    AccessRequestItem = apps.get_model("inscriptions", "AccessRequestItem")
    AdditionalAccessItem = apps.get_model("inscriptions", "AdditionalAccessItem")

    # Aligne les items d'inscription existants sur la nouvelle convention.
    for item in AccessRequestItem.objects.exclude(registration_id=None).select_related("registration"):
        req = getattr(item, "registration", None)
        if req and req.public_id:
            item.request_public_id = req.public_id
        item.origin = "registration"
        item.user_id = None
        item.save(update_fields=["origin", "request_public_id", "user"])

    # Recopie les demandes additionnelles dans le modèle unifié.
    for add_item in AdditionalAccessItem.objects.select_related("request"):
        req = add_item.request
        if not req:
            continue
        exists = AccessRequestItem.objects.filter(
            origin="additional",
            registration_id=None,
            user_id=req.user_id,
            application_id=add_item.application_id,
            request_public_id=req.public_id,
        ).exists()
        if exists:
            continue
        AccessRequestItem.objects.create(
            registration_id=None,
            user_id=req.user_id,
            application_id=add_item.application_id,
            origin="additional",
            request_public_id=req.public_id,
            status=add_item.status,
            decided_at=add_item.decided_at,
            decided_by_id=add_item.decided_by_id,
            request_justification=req.remarks or "",
            decision_note=add_item.decision_note or "",
        )


def backwards_unify_items(apps, schema_editor):
    # Pas de rollback automatique des données recopiées.
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("inscriptions", "0002_application_requires_access_request_and_request_justification"),
    ]

    operations = [
        migrations.AddField(
            model_name="accessrequestitem",
            name="origin",
            field=models.CharField(
                choices=[("registration", "Inscription"), ("additional", "Demande additionnelle")],
                default="registration",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="accessrequestitem",
            name="request_public_id",
            field=models.UUIDField(db_index=True, default=uuid.uuid4),
        ),
        migrations.AddField(
            model_name="accessrequestitem",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="access_requests",
                to="inscriptions.userprofile",
            ),
        ),
        migrations.RunPython(forwards_unify_items, backwards_unify_items),
    ]
