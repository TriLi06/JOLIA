"""Generiert kurze KI-Zusammenfassungen (~300 Zeichen) für Dateien via Ollama."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_MAX_SUMMARY_LEN = 300
_MAX_SHORT_SUMMARY_WORDS = 5
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
    document_date: str | None = None,
) -> str:
    """Generiert eine kurze, aber inhaltlich aussagekräftige Dokumentbeschreibung."""
    if not text_content or not text_content.strip():
        return ""
    try:
        from app.services.ollama_service import get_background_ollama_service

        ollama = get_background_ollama_service()

        excerpt = text_content[:_INPUT_LIMIT].strip()
        date_context = (
            f"\nErkanntes Dokumentdatum: {document_date}"
            if document_date else ""
        )
        prompt = (
            "Beschreibe den Inhalt dieses Dokuments auf Deutsch knapp, aber aussagekräftig "
            f"(maximal {_MAX_SUMMARY_LEN} Zeichen, ein kurzer Satz oder Absatz). "
            "Nenne Dokumentart, Thema und relevante Namen oder Details. Nenne ein Datum, "
            "wenn es im Inhalt eindeutig erkennbar ist; erfinde kein Datum. "
            "Beginne direkt mit der Beschreibung, ohne Einleitung:"
            f"{date_context}\n\nDokumentinhalt:\n{excerpt}"
        )

        summary = ollama.generate(prompt)
        if summary.strip() and not _is_unhelpful_summary(summary):
            return _trim_summary(summary)
        return ""

    except Exception as exc:
        logger.warning("Dokumentzusammenfassung fehlgeschlagen: %s", exc)
        return ""


def generate_document_short_summary(
    text_content: str,
    original_filename: str = "",
    document_date: str | None = None,
) -> str:
    """Generiert ein prägnantes Label aus zwei bis fünf Wörtern für Liste und Timeline."""
    if not text_content or not text_content.strip():
        return original_filename
    try:
        from app.services.ollama_service import get_background_ollama_service

        excerpt = text_content[:_INPUT_LIMIT].strip()
        date_context = (
            f"\nErkanntes Dokumentdatum: {document_date}"
            if document_date else ""
        )
        prompt = (
            "Erstelle eine eindeutige Kurzzusammenfassung dieses Dokuments auf Deutsch. "
            "Gib nur 2 bis 5 Wörter aus, keinen ganzen Satz und keine Einleitung. "
            "Nenne Dokumentart und wichtigstes Thema oder den Namen. "
            "Füge ein Datum oder zumindest Jahr hinzu, wenn es im Inhalt sicher erkennbar ist; "
            "erfinde niemals ein Datum. Setze das Datum ans Ende. "
            "Beispiele: 'Stundenplan Lousa 2026', 'Reparatur Astra 10/2026'."
            f"{date_context}\n\nDokumentinhalt:\n{excerpt}"
        )
        summary = get_background_ollama_service().generate(prompt)
        summary = _trim_short_summary(summary)
        if (
            2 <= len(summary.split()) <= _MAX_SHORT_SUMMARY_WORDS
            and not _is_unhelpful_summary(summary)
        ):
            return summary
        return original_filename
    except Exception as exc:
        logger.warning("Dokument-Kurzzusammenfassung fehlgeschlagen: %s", exc)
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


def _trim_short_summary(text: str) -> str:
    text = text.strip().strip("\"'„“")
    words = text.split()
    if len(words) > _MAX_SHORT_SUMMARY_WORDS:
        date_at_end = re.fullmatch(
            r"(?:\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|\d{1,2}[-/.]\d{4}|\d{4})",
            words[-1].rstrip(".,;:"),
        )
        if date_at_end:
            text = " ".join(words[:_MAX_SHORT_SUMMARY_WORDS - 1] + [words[-1]])
        else:
            text = " ".join(words[:_MAX_SHORT_SUMMARY_WORDS])
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
