"""
Importe organismes, réserves et liens depuis la base PostgreSQL legacy (Flask/UsersHub).

Configurer LEGACY_DATABASE_URL (ex. postgres://user:pass@host:5432/dbname).
Schémas attendus : utilisateurs.bib_organismes, ref_geo.l_areas, complement_rnf.cor_rn_og.
"""

from django.core.management.base import BaseCommand
from django.db import connections, transaction
from django.utils.text import slugify

from inscriptions.models import Organisme, OrganismeReserveLink, Reserve


class Command(BaseCommand):
    help = "Import organismes / réserves / liens depuis la base legacy."

    def handle(self, *args, **options):
        if "legacy" not in connections.databases:
            self.stderr.write(self.style.ERROR("Définir LEGACY_DATABASE_URL pour utiliser cette commande."))
            return
        legacy = connections["legacy"]
        with legacy.cursor() as c:
            c.execute(
                """
                SELECT id_organisme, uuid_organisme::text, nom_organisme
                FROM utilisateurs.bib_organismes
                """
            )
            org_rows = c.fetchall()
            c.execute(
                """
                SELECT area_code::text, area_name::text, id_type::text
                FROM ref_geo.l_areas
                WHERE id_type::text IN ('5','6','18')
                """
            )
            res_rows = c.fetchall()
            c.execute(
                """
                SELECT rn_id::text, og_uuid::text, COALESCE(principal, false)
                FROM complement_rnf.cor_rn_og
                """
            )
            link_rows = c.fetchall()

        with transaction.atomic():
            for oid, uuid_o, nom in org_rows:
                slug = slugify(nom or "")[:200] or f"org-{oid}"
                Organisme.objects.update_or_create(
                    id_organisme=oid,
                    defaults={
                        "uuid_organisme": uuid_o or "",
                        "nom_organisme": nom or "",
                        "keycloak_slug": slug,
                    },
                )
            for code, name, id_type in res_rows:
                Reserve.objects.update_or_create(
                    area_code=code,
                    defaults={"area_name": name or "", "id_type": id_type or ""},
                )
            for rn_id, og_uuid, principal in link_rows:
                org = Organisme.objects.filter(uuid_organisme=og_uuid).first()
                if not org:
                    continue
                res = Reserve.objects.filter(area_code=rn_id).first()
                if not res:
                    continue
                OrganismeReserveLink.objects.update_or_create(
                    organisme=org,
                    reserve=res,
                    defaults={"principal": bool(principal)},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Import terminé : {len(org_rows)} organismes, {len(res_rows)} réserves, {len(link_rows)} liens lus."
            )
        )
