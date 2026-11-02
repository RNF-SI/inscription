from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inscriptions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="requires_access_request",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="accessrequestitem",
            name="request_justification",
            field=models.TextField(blank=True),
        ),
    ]

