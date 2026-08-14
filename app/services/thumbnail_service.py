"""Generiert und speichert Thumbnails für Bilddateien."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

THUMBNAIL_SIZE = (200, 200)
THUMBNAIL_FORMAT = "JPEG"
THUMBNAIL_QUALITY = 80


def get_thumbnail_dir(data_dir: Path) -> Path:
    thumb_dir = data_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    return thumb_dir


def get_thumbnail_path(data_dir: Path, file_id: str) -> Path:
    return get_thumbnail_dir(data_dir) / f"{file_id}.jpg"


def generate_and_store(file_path: Path, file_id: str, data_dir: Path) -> str | None:
    """
    Erzeugt ein Thumbnail für eine Bild- oder PDF-Datei und speichert es persistent.

    Gibt den relativen Pfad zum Thumbnail zurück (relativ zu data_dir),
    oder None bei Fehler.
    """
    try:
        from PIL import Image

        if file_path.suffix.lower() == ".pdf":
            img = _render_pdf_first_page(file_path)
            if img is None:
                return None
        else:
            # HEIC-Support
            if file_path.suffix.lower() in (".heic", ".heif"):
                try:
                    from pillow_heif import register_heif_opener
                    register_heif_opener()
                except ImportError:
                    pass
            img = Image.open(str(file_path))

        # In RGB konvertieren (JPEG unterstützt kein RGBA/P)
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])
            else:
                background.paste(img)
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)

        thumb_path = get_thumbnail_path(data_dir, file_id)
        img.save(str(thumb_path), format=THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY, optimize=True)

        # Relativer Pfad als String zurückgeben
        rel_path = str(thumb_path.relative_to(data_dir))
        logger.info("Thumbnail erstellt: %s", thumb_path)
        return rel_path

    except Exception as exc:
        logger.warning("Thumbnail-Erstellung fehlgeschlagen für %s: %s", file_path.name, exc)
        return None


def _render_pdf_first_page(file_path: Path):
    """Rendert die erste Seite eines PDFs als PIL-Image (benötigt poppler/pdf2image)."""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(str(file_path), dpi=100, first_page=1, last_page=1)
        return images[0] if images else None
    except Exception as exc:
        logger.warning("PDF-Vorschau fehlgeschlagen für %s: %s", file_path.name, exc)
        return None


def thumbnail_exists(data_dir: Path, file_id: str) -> bool:
    return get_thumbnail_path(data_dir, file_id).exists()
