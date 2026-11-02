from __future__ import annotations

import io
import mimetypes
from pathlib import Path

from django.conf import settings
from PIL import Image

from inscriptions.models import Application

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
ALLOWED_IMAGE_MIME_PREFIXES = ("image/",)
MAX_APPLICATION_IMAGE_BYTES = 8 * 1024 * 1024
APPLICATION_IMAGE_WIDTH = 800
APPLICATION_IMAGE_HEIGHT = 400
APPLICATION_IMAGE_EXTENSION = ".png"


class ApplicationImageError(ValueError):
    pass


def application_images_dir() -> Path:
    return Path(getattr(settings, "APPLICATION_IMAGES_DIR", "")).resolve()


def application_image_path(filename: str) -> Path:
    name = Path((filename or "").strip()).name
    if not name or name != filename or ".." in filename:
        raise ApplicationImageError("Nom de fichier image invalide.")
    return application_images_dir() / name


def image_in_use_by_other_apps(filename: str, *, exclude_app_id: int | None = None) -> bool:
    if not filename:
        return False
    qs = Application.objects.filter(image=filename)
    if exclude_app_id is not None:
        qs = qs.exclude(pk=exclude_app_id)
    return qs.exists()


def safe_delete_application_image(filename: str, *, exclude_app_id: int | None = None) -> None:
    if not filename or image_in_use_by_other_apps(filename, exclude_app_id=exclude_app_id):
        return
    path = application_image_path(filename)
    if path.is_file():
        path.unlink()


def _validate_upload(uploaded_file) -> str:
    if not uploaded_file:
        raise ApplicationImageError("Fichier image requis.")
    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_APPLICATION_IMAGE_BYTES:
        raise ApplicationImageError("L'image dépasse la taille maximale autorisée (8 Mo).")
    original_path = Path(getattr(uploaded_file, "name", "") or "")
    ext = original_path.suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ApplicationImageError("Format d'image non supporté (png, jpg, webp, svg, gif).")
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type and not content_type.startswith(ALLOWED_IMAGE_MIME_PREFIXES):
        guessed, _ = mimetypes.guess_type(original_path.name)
        if not guessed or not guessed.startswith("image/"):
            raise ApplicationImageError("Le fichier envoyé n'est pas une image.")
    return ext


def normalize_application_image(uploaded_file) -> bytes:
    """Recadre au ratio cible et redimensionne en PNG 800×400."""
    uploaded_file.seek(0)
    img = Image.open(uploaded_file)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    src_w, src_h = img.size
    target_ratio = APPLICATION_IMAGE_WIDTH / APPLICATION_IMAGE_HEIGHT
    src_ratio = src_w / src_h if src_h else target_ratio

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    img = img.resize((APPLICATION_IMAGE_WIDTH, APPLICATION_IMAGE_HEIGHT), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def save_application_image(app: Application, uploaded_file) -> str:
    _validate_upload(uploaded_file)
    images_dir = application_images_dir()
    images_dir.mkdir(parents=True, exist_ok=True)

    old_filename = (app.image or "").strip()
    new_filename = f"{app.slug}{APPLICATION_IMAGE_EXTENSION}"
    dest = images_dir / new_filename

    normalized = normalize_application_image(uploaded_file)
    dest.write_bytes(normalized)

    if old_filename and old_filename != new_filename:
        safe_delete_application_image(old_filename, exclude_app_id=app.pk)

    app.image = new_filename
    app.save(update_fields=["image"])
    return new_filename


def remove_application_image(app: Application) -> None:
    old_filename = (app.image or "").strip()
    app.image = ""
    app.save(update_fields=["image"])
    safe_delete_application_image(old_filename, exclude_app_id=app.pk)
