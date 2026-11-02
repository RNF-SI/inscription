from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inscriptions", "0003_unify_access_request_items"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="fonction",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
