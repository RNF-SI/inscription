from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inscriptions", "0007_keycloak_identity_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="keycloak_admin_count",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="keycloak_counts_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="application",
            name="keycloak_member_count",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
