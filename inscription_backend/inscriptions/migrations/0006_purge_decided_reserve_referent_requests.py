from django.db import migrations


def purge_decided_referent_requests(apps, schema_editor):
    ReserveReferentRequest = apps.get_model("inscriptions", "ReserveReferentRequest")
    ReserveReferentRequest.objects.exclude(status="pending").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inscriptions", "0005_reserve_member_removal_request"),
    ]

    operations = [
        migrations.RunPython(purge_decided_referent_requests, migrations.RunPython.noop),
    ]
