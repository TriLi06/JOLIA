"""Generiert kurze KI-Zusammenfassungen (~300 Zeichen) für Dateien via Ollama."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_SUMMARY_LEN = 300
_INPUT_LIMIT = 6000  # Maximale Eingabe für den Prompt (Text kommt bereits über das ganze Dokument gesampelt)


def generate_image_summary(
    vision_description: str,
    exif_meta: dict,
    face_count: int | None = None,
) -> str:
    """Generiert eine kurze Zusammenfassung für ein Bild auf Deutsch."""
    try:
        from app.config import get_config
        from app.services.ollama_service import get_background_ollama_service

        cfg = get_config()
        ollama = get_background_ollama_service()
        if not ollama.is_available():
            return _fallback_image_summary(vision_description, face_count)

        context_parts = []
        if vision_description:
            context_parts.append(vision_description[:800])
        if face_count:
            context_parts.append(f"Erkannte Personen: {face_count}")
        capture_date = (
            exif_meta.get("DateTimeOriginal")
            or exif_meta.get("DateTime")
            or exif_meta.get("DateTimeDigitized")
        )
        if capture_date:
            context_parts.append(f"Aufnahmedatum: {capture_date}")
        gps = exif_meta.get("GPS")
        if gps:
            context_parts.append(f"GPS: {gps}")

        if not context_parts:
            return ""

        context = "\n".join(context_parts)
        prompt = (
            f"Erstelle eine sehr kurze Zusammenfassung dieses Bildes auf Deutsch "
            f"(maximal {_MAX_SUMMARY_LEN} Zeichen, ein einziger Satz oder sehr kurzer Absatz). "
            f"Beginne direkt mit der Beschreibung, ohne Einleitung:\n\n{context}"
        )

        summary = ollama.generate(prompt)
        return _trim_summary(summary)

    except Exception as exc:
        logger.warning("Bildzusammenfassung fehlgeschlagen: %s", exc)
        return _fallback_image_summary(vision_description, face_count)


def generate_document_summary(text_content: str) -> str:
    """Generiert eine kurze Zusammenfassung für ein Dokument auf Deutsch."""
    if not text_content or not text_content.strip():
        return ""
    try:
        from app.services.ollama_service import get_background_ollama_service

        ollama = get_background_ollama_service()
        if not ollama.is_available():
            return _fallback_text_summary(text_content)

        excerpt = text_content[:_INPUT_LIMIT].strip()
        prompt = (
            f"Erstelle eine sehr kurze Zusammenfassung dieses Dokuments auf Deutsch "
            f"(maximal {_MAX_SUMMARY_LEN} Zeichen, ein einziger Satz oder sehr kurzer Absatz). "
            f"Beginne direkt mit der Beschreibung, ohne Einleitung:\n\n{excerpt}"
        )

        summary = ollama.generate(prompt)
        return _trim_summary(summary)

    except Exception as exc:
        logger.warning("Dokumentzusammenfassung fehlgeschlagen: %s", exc)
        return _fallback_text_summary(text_content)


def _trim_summary(text: str) -> str:
    """Kürzt die Zusammenfassung auf _MAX_SUMMARY_LEN Zeichen."""
    text = text.strip()
    if len(text) > _MAX_SUMMARY_LEN:
        text = text[:_MAX_SUMMARY_LEN - 1].rsplit(" ", 1)[0] + "…"
    return text


def _fallback_image_summary(vision_description: str, face_count: int | None) -> str:
    """Einfache Fallback-Zusammenfassung ohne LLM."""
    if vision_description:
        first_sentence = vision_description.split(".")[0].strip()
        if len(first_sentence) > 10:
            return _trim_summary(first_sentence)
    if face_count:
        return f"Bild mit {face_count} erkennbaren Person(en)."
    return ""


def _fallback_text_summary(text_content: str) -> str:
    """Einfache Fallback-Zusammenfassung ohne LLM."""
    excerpt = text_content.strip()[:_MAX_SUMMARY_LEN]
    if len(text_content.strip()) > _MAX_SUMMARY_LEN:
        excerpt = excerpt.rsplit(" ", 1)[0] + "…"
    return excerpt
