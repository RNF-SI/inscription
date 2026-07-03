from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inscriptions", "0008_application_keycloak_counts"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="admin_tab",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
    ]
