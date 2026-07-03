from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

from django.conf import settings
from django.utils import timezone

from inscriptions.models import AccessRequestItem, Application, RegistrationRequest, Reserve
from inscriptions.user_identity import UserInfo, user_label

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "inscriptions" / "email" / "logo_rnf_blanc_email.png"
LOGO_CID = "rnf_logo@reserves-naturelles.org"
LOGO_HEIGHT_PX = 64

BRAND_PRIMARY = "#0B885D"
BRAND_ACCENT = "#c8d469"
BRAND_BG = "#f4f7f5"
BRAND_TEXT = "#1f2933"
BRAND_MUTED = "#5f6c7b"
BRAND_BORDER = "#d8e3dc"


def frontend_url(path: str = "") -> str:
    base = settings.FRONTEND_PUBLIC_URL.rstrip("/")
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _format_dt(dt) -> str:
    if not dt:
        return "—"
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.strftime("%d/%m/%Y à %H:%M")


def _reserve_labels(codes: Iterable[str]) -> list[str]:
    labels: list[str] = []
    for code in codes:
        code = str(code or "").strip()
        if not code:
            continue
        reserve = Reserve.objects.filter(area_code=code).first()
        labels.append(f"{reserve.area_name} ({code})" if reserve else code)
    return labels


def registration_info_rows(registration: RegistrationRequest) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [
        ("Prénom", registration.first_name),
        ("Nom", registration.last_name),
        ("E-mail", registration.email),
        ("Identifiant", registration.username),
        ("Fonction", (registration.remarks or "").strip() or "—"),
        ("Organisme", registration.organisme.nom_organisme if registration.organisme else "—"),
        ("Date de la demande", _format_dt(registration.created_at)),
        ("Référence", str(registration.public_id)),
    ]

    reserve_labels = _reserve_labels(registration.reserve_codes or [])
    if reserve_labels:
        rows.append(("Réserves naturelles", ", ".join(reserve_labels)))

    champs = registration.champs_addi or {}
    referent_codes: list[str] = []
    raw_referent = champs.get("reserves_referent")
    if isinstance(raw_referent, list):
        for item in raw_referent:
            if isinstance(item, dict):
                code = str(item.get("id") or "").strip()
            else:
                code = str(item or "").strip()
            if code:
                referent_codes.append(code)
    referent_labels = _reserve_labels(referent_codes)
    if referent_labels:
        rows.append(("Demandes référent", ", ".join(referent_labels)))

    for key, value in sorted(champs.items()):
        if key in {"reserves", "reserves_referent"}:
            continue
        if isinstance(value, bool):
            display = "Oui" if value else "Non"
        elif isinstance(value, (list, dict)):
            display = str(value)
        else:
            display = str(value or "").strip()
        if display:
            label = key.replace("_", " ").strip().capitalize()
            rows.append((label, display))

    return rows


def access_items_rows(items: Iterable[AccessRequestItem]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for item in items:
        justification = (item.request_justification or "").strip() or "Aucune justification fournie."
        rows.append((item.application.nom, justification))
    return rows


def access_items_section(items: Iterable[AccessRequestItem]) -> str:
    rows = access_items_rows(items)
    if not rows:
        return paragraph("Aucune demande d'accès à une application n'a été formulée.")
    return section_title("Demandes d'accès aux applications") + info_table(rows)


def info_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    body = []
    for label, value in rows:
        body.append(
            f"""
            <tr>
              <td style="padding:10px 14px;border-bottom:1px solid {BRAND_BORDER};color:{BRAND_MUTED};width:38%;vertical-align:top;font-size:14px;">
                <strong>{_esc(label)}</strong>
              </td>
              <td style="padding:10px 14px;border-bottom:1px solid {BRAND_BORDER};color:{BRAND_TEXT};font-size:14px;vertical-align:top;">
                {_esc(value)}
              </td>
            </tr>
            """
        )
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="border:1px solid {BRAND_BORDER};border-radius:8px;overflow:hidden;background:#ffffff;">
      {''.join(body)}
    </table>
    """


def paragraph(text: str) -> str:
    return f'<p style="margin:0 0 16px;color:{BRAND_TEXT};font-size:15px;line-height:1.6;">{_esc(text)}</p>'


def section_title(text: str) -> str:
    return (
        f'<h2 style="margin:24px 0 12px;color:{BRAND_PRIMARY};font-size:18px;font-weight:700;">'
        f"{_esc(text)}</h2>"
    )


def bullet_list(items: list[str]) -> str:
    if not items:
        return ""
    lis = "".join(
        f'<li style="margin-bottom:8px;color:{BRAND_TEXT};font-size:15px;line-height:1.5;">{_esc(item)}</li>'
        for item in items
    )
    return f'<ul style="margin:0 0 16px 20px;padding:0;">{lis}</ul>'


def button(label: str, url: str) -> str:
    safe_url = _esc(url)
    safe_label = _esc(label)
    return f"""
    <table role="presentation" cellspacing="0" cellpadding="0" style="margin:24px auto 8px;">
      <tr>
        <td align="center" style="border-radius:6px;background:{BRAND_PRIMARY};">
          <a href="{safe_url}" target="_blank"
             style="display:inline-block;padding:14px 28px;color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;border-radius:6px;">
            {safe_label}
          </a>
        </td>
      </tr>
    </table>
    """


def render_email(
    *,
    title: str,
    preheader: str = "",
    blocks: list[str],
    secondary_note: str = "",
) -> tuple[str, str]:
    content = "".join(blocks)
    note_html = ""
    if secondary_note:
        note_html = (
            f'<p style="margin:24px 0 0;color:{BRAND_MUTED};font-size:13px;line-height:1.5;">'
            f"{_esc(secondary_note)}</p>"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_esc(title)}</title>
</head>
<body style="margin:0;padding:0;background:{BRAND_BG};font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{_esc(preheader)}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:{BRAND_BG};">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="max-width:620px;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 8px 24px rgba(11,136,93,0.12);">
          <tr>
            <td style="background:{BRAND_PRIMARY};padding:28px 32px;text-align:center;">
              <img src="cid:{LOGO_CID}" alt="Réserves Naturelles de France" height="{LOGO_HEIGHT_PX}"
                   style="display:block;margin:0 auto 12px;border:0;height:{LOGO_HEIGHT_PX}px;width:auto;max-width:100%;" />
              <div style="color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.3px;">Système d'informations de RNF</div>
            </td>
          </tr>
          <tr>
            <td style="height:5px;background:{BRAND_ACCENT};font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h1 style="margin:0 0 20px;color:{BRAND_PRIMARY};font-size:24px;line-height:1.3;">{_esc(title)}</h1>
              {content}
              {note_html}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background:#f8fbf9;border-top:1px solid {BRAND_BORDER};text-align:center;">
              <p style="margin:0;color:{BRAND_MUTED};font-size:12px;line-height:1.5;">
                Réserves Naturelles de France — 2 allée Pierre Lacroute, 21075 Dijon cedex
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    plain_parts = [title, preheader]
    for block in blocks:
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            plain_parts.append(text)
    if secondary_note:
        plain_parts.append(secondary_note)
    plain_parts.append("Réserves Naturelles de France")
    return html_doc, "\n\n".join(part for part in plain_parts if part)


def registration_submitted_user_email(registration: RegistrationRequest) -> tuple[str, str, str]:
    subject = "Votre demande d'inscription a bien été reçue"
    preheader = "Votre demande est en attente de validation par un administrateur."
    html_doc, plain = render_email(
        title="Demande d'inscription enregistrée",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {registration.first_name}, nous avons bien reçu votre demande d'inscription "
                "sur les plateformes de Réserves Naturelles de France."
            ),
            paragraph(
                "Elle est actuellement en attente de validation par un administrateur. "
                "Vous recevrez un e-mail dès qu'une décision aura été prise."
            ),
            section_title("Récapitulatif de votre demande"),
            info_table(registration_info_rows(registration)),
            access_items_section(registration.items.select_related("application")),
        ],
        secondary_note="Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer ce message.",
    )
    return subject, html_doc, plain


def _registration_user_label(registration: RegistrationRequest) -> str:
    org = registration.organisme.nom_organisme if registration.organisme else ""
    return user_label(
        UserInfo(
            sub=str(registration.public_id),
            email=registration.email,
            username=registration.username,
            first_name=registration.first_name,
            last_name=registration.last_name,
            fonction=(registration.remarks or "").strip(),
            organisme=org,
        )
    )


def registration_submitted_admin_email(registration: RegistrationRequest) -> tuple[str, str, str]:
    subject = f"Nouvelle demande d'inscription — {registration.first_name} {registration.last_name}"
    preheader = "Une nouvelle demande d'inscription nécessite votre validation."
    admin_url = frontend_url("admin")
    html_doc, plain = render_email(
        title="Nouvelle demande d'inscription",
        preheader=preheader,
        blocks=[
            paragraph(f"{_registration_user_label(registration)} vient de soumettre une demande d'inscription."),
            section_title("Informations du demandeur"),
            info_table(registration_info_rows(registration)),
            access_items_section(registration.items.select_related("application")),
            button("Valider l'inscription", admin_url),
        ],
        secondary_note="Connectez-vous à l'espace d'administration pour approuver ou refuser cette demande.",
    )
    return subject, html_doc, plain


def registration_approved_user_email(registration: RegistrationRequest) -> tuple[str, str, str]:
    items = list(registration.items.select_related("application"))
    app_lines = [
        f"{item.application.nom} — en attente de validation par le gestionnaire de l'application"
        for item in items
    ]
    if not app_lines:
        app_lines = ["Aucune demande d'accès applicatif complémentaire."]

    subject = "Votre inscription a été validée"
    preheader = "Votre compte est créé. Les accès aux applications seront traités prochainement."
    platform_url = frontend_url()
    profile_url = frontend_url("mon-compte")
    html_doc, plain = render_email(
        title="Inscription validée",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {registration.first_name}, un administrateur a validé votre inscription. "
                "Votre compte est désormais actif sur la plateforme."
            ),
            section_title("Demandes d'accès aux applications"),
            bullet_list(app_lines),
            paragraph(
                "Ces demandes vont être examinées par les administrateurs de chaque application. "
                "Vous serez notifié dès qu'une décision sera prise."
            ),
            paragraph(
                f"Retrouvez vos autorisations d'accès sur {platform_url} une fois connecté. "
                "Vous pouvez modifier à tout moment les informations de votre profil depuis la page Mon compte."
            ),
            button("Accéder à la plateforme", platform_url),
            button("Modifier mon profil", profile_url),
        ],
    )
    return subject, html_doc, plain


def registration_rejected_user_email(registration: RegistrationRequest, note: str = "") -> tuple[str, str, str]:
    subject = "Votre demande d'inscription n'a pas été retenue"
    preheader = "Votre demande d'inscription a été refusée."
    blocks = [
        paragraph(
            f"Bonjour {registration.first_name}, nous sommes au regret de vous informer que votre demande "
            "d'inscription n'a pas été retenue à ce stade. Vous pouvez contacter l'administrateur de la plateforme pour plus d'informations."
        ),
    ]
    if note.strip():
        blocks.extend([section_title("Motif"), paragraph(note.strip())])
    html_doc, plain = render_email(title="Demande d'inscription refusée", preheader=preheader, blocks=blocks)
    return subject, html_doc, plain


def app_access_request_admin_email(
    *,
    applicant: UserInfo,
    application: Application,
    justification: str,
) -> tuple[str, str, str]:
    applicant_label = user_label(applicant)
    subject = f"Demande d'accès — {application.nom}"
    preheader = f"{applicant_label} demande l'accès à {application.nom}."
    admin_url = frontend_url("admin")
    html_doc, plain = render_email(
        title=f"Demande d'accès à {application.nom}",
        preheader=preheader,
        blocks=[
            paragraph(f"{applicant_label} demande l'accès à l'application {application.nom}."),
            section_title("Justification"),
            paragraph(justification or "Aucune justification fournie."),
            button("Traiter la demande", admin_url),
        ],
    )
    return subject, html_doc, plain


def app_access_granted_user_email(
    *,
    first_name: str,
    application: Application,
) -> tuple[str, str, str]:
    subject = f"Accès accordé — {application.nom}"
    preheader = f"Votre accès à {application.nom} a été validé."
    app_url = (application.url or "").strip() or frontend_url()
    html_doc, plain = render_email(
        title=f"Accès à {application.nom} validé",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {first_name}, votre demande d'accès à {application.nom} a été acceptée. "
                "Vous pouvez dès maintenant utiliser l'application."
            ),
            button(f"Ouvrir {application.nom}", app_url),
        ],
    )
    return subject, html_doc, plain


def app_access_rejected_user_email(
    *,
    first_name: str,
    application: Application,
    note: str,
) -> tuple[str, str, str]:
    subject = f"Accès refusé — {application.nom}"
    preheader = f"Votre demande d'accès à {application.nom} n'a pas été acceptée."
    html_doc, plain = render_email(
        title=f"Demande d'accès à {application.nom} refusée",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {first_name}, votre demande d'accès à {application.nom} n'a pas été acceptée."
            ),
            section_title("Motif"),
            paragraph(note or "Aucun motif précisé."),
        ],
    )
    return subject, html_doc, plain


def _user_first_name(user: UserInfo) -> str:
    return user.first_name or user.username or "utilisateur"


def _user_display_label(user: UserInfo) -> str:
    return user_label(user)


def reserve_referent_request_superadmin_email(*, applicant: UserInfo, reserve: Reserve) -> tuple[str, str, str]:
    subject = f"Demande référent — {reserve.area_name}"
    preheader = f"{_user_display_label(applicant)} demande le statut référent."
    admin_url = frontend_url("admin")
    html_doc, plain = render_email(
        title="Demande de statut référent",
        preheader=preheader,
        blocks=[
            paragraph(
                f"{_user_display_label(applicant)} demande le statut référent pour la réserve "
                f"{reserve.area_name} ({reserve.area_code})."
            ),
            info_table(
                [
                    ("Prénom", applicant.first_name),
                    ("Nom", applicant.last_name),
                    ("E-mail", applicant.email),
                    ("Identifiant", applicant.username),
                    ("Organisme", (applicant.organisme or "").strip() or "—"),
                    ("Fonction", (applicant.fonction or "").strip() or "—"),
                    ("Réserve", f"{reserve.area_name} ({reserve.area_code})"),
                ]
            ),
            button("Traiter la demande", admin_url),
        ],
        secondary_note="Connectez-vous à l'espace d'administration, onglet « Toutes les demandes ».",
    )
    return subject, html_doc, plain


def reserve_referent_approved_user_email(*, user: UserInfo, reserve: Reserve) -> tuple[str, str, str]:
    subject = f"Statut référent accordé — {reserve.area_name}"
    preheader = f"Votre demande de statut référent pour {reserve.area_name} a été acceptée."
    platform_url = frontend_url("admin")
    html_doc, plain = render_email(
        title="Demande de référent acceptée",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {_user_first_name(user)}, votre demande de statut référent pour la réserve "
                f"{reserve.area_name} ({reserve.area_code}) a été acceptée."
            ),
            paragraph(
                "Vous pouvez désormais gérer les membres de cette réserve depuis l'administration "
                "(onglet « Membres des réserves »)."
            ),
            button("Accéder à l'administration", platform_url),
        ],
    )
    return subject, html_doc, plain


def reserve_referent_rejected_user_email(*, user: UserInfo, reserve: Reserve, note: str) -> tuple[str, str, str]:
    subject = f"Statut référent refusé — {reserve.area_name}"
    preheader = f"Votre demande de statut référent pour {reserve.area_name} n'a pas été acceptée."
    blocks = [
        paragraph(
            f"Bonjour {_user_first_name(user)}, votre demande de statut référent pour la réserve "
            f"{reserve.area_name} ({reserve.area_code}) n'a pas été acceptée."
        ),
    ]
    if note.strip():
        blocks.extend([section_title("Motif"), paragraph(note.strip())])
    html_doc, plain = render_email(
        title="Demande de référent refusée",
        preheader=preheader,
        blocks=blocks,
    )
    return subject, html_doc, plain


def reserve_member_removal_superadmin_email(
    *,
    requester: UserInfo,
    reserve: Reserve,
    target: UserInfo,
    reason: str,
) -> tuple[str, str, str]:
    target_label = user_label(target)
    requester_label = user_label(requester)
    subject = f"Demande de retrait membre — {reserve.area_name}"
    preheader = f"{requester_label} demande le retrait de {target_label}."
    admin_url = frontend_url("admin?tab=requests")
    html_doc, plain = render_email(
        title="Demande de retrait d'un membre",
        preheader=preheader,
        blocks=[
            paragraph(
                f"{requester_label} demande le retrait de {target_label} "
                f"de la réserve {reserve.area_name} ({reserve.area_code})."
            ),
            info_table(
                [
                    ("Réserve", f"{reserve.area_name} ({reserve.area_code})"),
                    ("Demandeur", requester_label),
                    ("Membre ciblé", target_label),
                    ("Motif", reason.strip() or "—"),
                ]
            ),
            button("Traiter la demande", admin_url),
        ],
        secondary_note="Connectez-vous à l'espace d'administration, onglet « Toutes les demandes ».",
    )
    return subject, html_doc, plain


def reserve_member_removal_rejected_requester_email(
    *,
    requester: UserInfo,
    reserve: Reserve,
    target_first_name: str,
    target_last_name: str,
    target_email: str,
    note: str,
) -> tuple[str, str, str]:
    target_label = f"{target_first_name} {target_last_name}".strip() or target_email or "ce membre"
    subject = f"Demande de retrait refusée — {reserve.area_name}"
    preheader = f"Votre demande de retrait pour {target_label} n'a pas été acceptée."
    blocks = [
        paragraph(
            f"Bonjour {_user_first_name(requester)}, votre demande de retrait de {target_label} "
            f"de la réserve {reserve.area_name} ({reserve.area_code}) n'a pas été acceptée."
        ),
    ]
    if note.strip():
        blocks.extend([section_title("Motif"), paragraph(note.strip())])
    html_doc, plain = render_email(
        title="Demande de retrait refusée",
        preheader=preheader,
        blocks=blocks,
    )
    return subject, html_doc, plain


def reserve_new_member_referent_email(
    *,
    reserve: Reserve,
    member: UserInfo,
    referent_first_name: str = "référent",
) -> tuple[str, str, str]:
    subject = f"Nouveau membre — {reserve.area_name}"
    preheader = f"{_user_display_label(member)} a rejoint la réserve {reserve.area_name}."
    admin_url = frontend_url("admin")
    html_doc, plain = render_email(
        title=f"Nouveau membre sur {reserve.area_name}",
        preheader=preheader,
        blocks=[
            paragraph(
                f"Bonjour {referent_first_name}, {_user_display_label(member)} vient de rejoindre la réserve "
                f"{reserve.area_name} ({reserve.area_code})."
            ),
            paragraph(
                "Si cette personne ne devrait pas en faire partie, vous pouvez le signaler depuis "
                "l'administration de la plateforme (onglet « Membres des réserves »)."
            ),
            button("Gérer les membres de la réserve", admin_url),
        ],
    )
    return subject, html_doc, plain
