from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inscriptions", "0004_userprofile_fonction"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReserveMemberRemovalRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_sub", models.CharField(db_index=True, max_length=200)),
                ("target_email", models.EmailField(blank=True, max_length=254)),
                ("target_first_name", models.CharField(blank=True, max_length=200)),
                ("target_last_name", models.CharField(blank=True, max_length=200)),
                ("reason", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "En attente"), ("approved", "Approuvé"), ("rejected", "Refusé")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="member_removal_decisions",
                        to="inscriptions.userprofile",
                    ),
                ),
                (
                    "requester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="member_removal_requests",
                        to="inscriptions.userprofile",
                    ),
                ),
                (
                    "reserve",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="member_removal_requests",
                        to="inscriptions.reserve",
                    ),
                ),
            ],
            options={
                "db_table": "inscription_reserve_member_removal_request",
                "ordering": ["-created_at"],
            },
        ),
    ]
