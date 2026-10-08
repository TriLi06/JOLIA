"""Generiert kurze KI-Zusammenfassungen (~300 Zeichen) für Dateien via Ollama."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_MAX_SUMMARY_LEN = 300
_MAX_DOCUMENT_SUMMARY_LEN = 100
_INPUT_LIMIT = 6000  # Maximale Eingabe für den Prompt (Text kommt bereits über das ganze Dokument gesampelt)


def generate_image_summary(
    vision_description: str,
    exif_meta: dict,
    face_count: int | None = None,
) -> str:
    """Generiert eine kurze Zusammenfassung für ein Bild auf Deutsch."""
    try:
        from app.services.ollama_service import get_background_ollama_service

        ollama = get_background_ollama_service()

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


def generate_document_summary(
    text_content: str,
    original_filename: str = "",
    document_date: str | None = None,
) -> str:
    """Generiert einen kurzen, eindeutigen Titel für ein Dokument."""
    if not text_content or not text_content.strip():
        return original_filename
    try:
        from app.services.ollama_service import get_background_ollama_service

        ollama = get_background_ollama_service()

        excerpt = text_content[:_INPUT_LIMIT].strip()
        date_context = (
            f"\nErkanntes Dokumentdatum: {document_date}"
            if document_date else ""
        )
        prompt = (
            "Erstelle einen eindeutigen, sehr kurzen Titel für dieses Dokument auf Deutsch "
            f"(maximal {_MAX_DOCUMENT_SUMMARY_LEN} Zeichen; wenige Stichwörter, kein ganzer Satz). "
            "Nenne Dokumentart und wichtigstes Thema bzw. den Namen. Nenne ein Datum oder "
            "einen Monat/Jahr, wenn es im Inhalt eindeutig erkennbar ist; erfinde kein Datum. "
            "Gib ausschließlich den Titel aus, ohne Einleitung oder Anführungszeichen."
            f"{date_context}\n\nDokumentinhalt:\n{excerpt}"
        )

        summary = ollama.generate(prompt)
        summary = _trim_summary(summary)
        if summary and not _is_unhelpful_summary(summary):
            return _trim_document_summary(summary)
        return original_filename

    except Exception as exc:
        logger.warning("Dokumentzusammenfassung fehlgeschlagen: %s", exc)
        return original_filename


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


def _trim_document_summary(text: str) -> str:
    if len(text) > _MAX_DOCUMENT_SUMMARY_LEN:
        shortened = text[:_MAX_DOCUMENT_SUMMARY_LEN - 1].rsplit(" ", 1)[0]
        text = (shortened or text[:_MAX_DOCUMENT_SUMMARY_LEN - 1]) + "…"
    return text


def _is_unhelpful_summary(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".!?")
    return normalized in {
        "",
        "dokument",
        "zusammenfassung",
        "keine zusammenfassung möglich",
        "kein dokumentinhalt",
    } or normalized.startswith(("ich kann ", "als ki-", "der text beschreibt "))
