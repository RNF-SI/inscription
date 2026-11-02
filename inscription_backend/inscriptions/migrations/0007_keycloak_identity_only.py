# Generated migration: identité Keycloak uniquement (suppression UserProfile)

import django.db.models.deletion
from django.db import migrations, models


def forwards_copy_user_fks(apps, schema_editor):
    UserProfile = apps.get_model("inscriptions", "UserProfile")
    Notification = apps.get_model("inscriptions", "Notification")
    AccessRequestItem = apps.get_model("inscriptions", "AccessRequestItem")
    ReserveReferentRequest = apps.get_model("inscriptions", "ReserveReferentRequest")
    ReserveMemberRemovalRequest = apps.get_model("inscriptions", "ReserveMemberRemovalRequest")
    RegistrationRequest = apps.get_model("inscriptions", "RegistrationRequest")

    profile_sub = {p.id: p.keycloak_sub for p in UserProfile.objects.all()}

    for n in Notification.objects.select_related("user").all():
        if n.user_id and n.user_id in profile_sub:
            n.user_sub = profile_sub[n.user_id]
            n.save(update_fields=["user_sub"])

    for item in AccessRequestItem.objects.all():
        changed = False
        if item.user_id and item.user_id in profile_sub:
            item.user_sub = profile_sub[item.user_id]
            changed = True
        if item.decided_by_id and item.decided_by_id in profile_sub:
            item.decided_by_sub = profile_sub[item.decided_by_id]
            changed = True
        if changed:
            item.save(update_fields=["user_sub", "decided_by_sub"])

    for req in ReserveReferentRequest.objects.all():
        changed = False
        if req.user_id and req.user_id in profile_sub:
            req.user_sub = profile_sub[req.user_id]
            changed = True
        if req.decided_by_id and req.decided_by_id in profile_sub:
            req.decided_by_sub = profile_sub[req.decided_by_id]
            changed = True
        if changed:
            req.save(update_fields=["user_sub", "decided_by_sub"])

    for req in ReserveMemberRemovalRequest.objects.all():
        changed = False
        if req.requester_id and req.requester_id in profile_sub:
            req.requester_sub = profile_sub[req.requester_id]
            changed = True
        if req.decided_by_id and req.decided_by_id in profile_sub:
            req.decided_by_sub = profile_sub[req.decided_by_id]
            changed = True
        if changed:
            req.save(update_fields=["requester_sub", "decided_by_sub"])

    for reg in RegistrationRequest.objects.all():
        if reg.created_profile_id and reg.created_profile_id in profile_sub:
            sub = profile_sub[reg.created_profile_id]
            if not reg.keycloak_user_id:
                reg.keycloak_user_id = sub
                reg.save(update_fields=["keycloak_user_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0006_purge_decided_reserve_referent_requests"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="user_sub",
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name="accessrequestitem",
            name="user_sub",
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name="accessrequestitem",
            name="decided_by_sub",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="reservereferentrequest",
            name="user_sub",
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name="reservereferentrequest",
            name="decided_by_sub",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="reservememberremovalrequest",
            name="requester_sub",
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name="reservememberremovalrequest",
            name="decided_by_sub",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="registrationrequest",
            name="keycloak_user_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.RunPython(forwards_copy_user_fks, migrations.RunPython.noop),
        migrations.RemoveField(model_name="notification", name="user"),
        migrations.RemoveField(model_name="accessrequestitem", name="user"),
        migrations.RemoveField(model_name="accessrequestitem", name="decided_by"),
        migrations.RemoveField(model_name="registrationrequest", name="created_profile"),
        migrations.RemoveField(model_name="reservereferentrequest", name="user"),
        migrations.RemoveField(model_name="reservereferentrequest", name="decided_by"),
        migrations.RemoveField(model_name="reservememberremovalrequest", name="requester"),
        migrations.RemoveField(model_name="reservememberremovalrequest", name="decided_by"),
        migrations.AlterField(
            model_name="notification",
            name="user_sub",
            field=models.CharField(db_index=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="reservereferentrequest",
            name="user_sub",
            field=models.CharField(db_index=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="reservememberremovalrequest",
            name="requester_sub",
            field=models.CharField(db_index=True, max_length=200),
        ),
        migrations.DeleteModel(name="ApplicationAdmin"),
        migrations.DeleteModel(name="UserApplicationAccess"),
        migrations.DeleteModel(name="UserReserveLink"),
        migrations.DeleteModel(name="AdditionalAccessItem"),
        migrations.DeleteModel(name="AdditionalAccessRequest"),
        migrations.DeleteModel(name="UserProfile"),
    ]
