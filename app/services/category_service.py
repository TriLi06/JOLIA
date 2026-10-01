from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import Category, File

logger = logging.getLogger(__name__)

_MAX_NAME_LEN = 128
_MAX_DEPTH = 6  # verhindert ausufernde Breadcrumbs bei fehlerhaften KI-Antworten
_ROOTS_BY_CONTENT_TYPE = {
    "images": "Bilder",
    "documents": "Dokumente",
    "audio": "Audio",
    "video": "Video",
}


def _get_categorization_ollama_service(config):
    """Erzeugt den separaten, langsameren Ollama-Service für Hintergrundaufgaben."""
    from app.services.ollama_service import OllamaService

    return OllamaService(
        base_url=config.models.ollama_base_url,
        model=getattr(config.models, "categorization_ollama_model", "qwen2.5:7b"),
        timeout=config.models.ollama_timeout,
        keep_alive=config.models.ollama_keep_alive,
    )


def _normalize_name(name: str) -> str:
    name = (name or "").strip().strip(" .\"'“”")
    name = " ".join(name.split())
    return name[:_MAX_NAME_LEN]


def _category_to_dict(category: Category, file_counts: dict[str, int] | None = None) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "parent_id": category.parent_id,
        "path": category.path(),
        "created_by": category.created_by,
        "count": (file_counts or {}).get(category.id, 0),
    }


def list_category_tree(db: Session) -> list[dict]:
    """Liefert alle Kategorien als flache Liste mit parent_id (Client baut daraus den Baum)."""
    categories = repo.list_categories(db)
    file_counts = repo.count_files_by_category(db)
    return [_category_to_dict(c, file_counts) for c in categories]


def get_category(db: Session, category_id: str) -> Category | None:
    return repo.get_category_by_id(db, category_id)


def format_breadcrumb(category: Category | None) -> str | None:
    if not category:
        return None
    return category.path()


def create_category(db: Session, name: str, parent_id: str | None = None, created_by: str = "user") -> dict:
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Kategorie-Name darf nicht leer sein.")
    if parent_id and not repo.get_category_by_id(db, parent_id):
        raise ValueError("Ziel-Kategorie (Eltern) nicht gefunden.")
    if repo.get_child_category_by_name(db, parent_id, normalized):
        raise ValueError(f"Eine Kategorie mit dem Namen '{normalized}' existiert an dieser Stelle bereits.")
    category = repo.create_category(db, normalized, parent_id=parent_id, created_by=created_by)
    return _category_to_dict(category)


def rename_category(db: Session, category_id: str, name: str) -> dict:
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Kategorie-Name darf nicht leer sein.")
    category = repo.get_category_by_id(db, category_id)
    if not category:
        raise ValueError("Kategorie nicht gefunden.")
    if repo.get_child_category_by_name(db, category.parent_id, normalized) not in (None, category):
        raise ValueError(f"Eine Kategorie mit dem Namen '{normalized}' existiert an dieser Stelle bereits.")
    updated = repo.rename_category(db, category_id, normalized)
    return _category_to_dict(updated)


def move_category(db: Session, category_id: str, new_parent_id: str | None) -> dict:
    category = repo.move_category(db, category_id, new_parent_id)
    return _category_to_dict(category)


def delete_category(db: Session, category_id: str, reassign_to_parent: bool = False) -> None:
    """Loescht eine Kategorie. Standardmaessig nur, wenn sie leer ist (keine Kinder/Dateien).

    Mit `reassign_to_parent=True` werden Kinder und zugeordnete Dateien zuvor auf den
    Elternknoten (bzw. auf "keine Kategorie" wenn es ein Wurzelknoten ist) umgehaengt.
    """
    category = repo.get_category_by_id(db, category_id)
    if not category:
        raise ValueError("Kategorie nicht gefunden.")
    children = [c for c in repo.list_categories(db) if c.parent_id == category_id]
    file_count = repo.count_files_in_category(db, category_id)

    if not reassign_to_parent:
        if children:
            raise ValueError("Kategorie hat noch Unterkategorien - erst verschieben/löschen oder Umhängen aktivieren.")
        if file_count:
            raise ValueError("Kategorie ist noch Dateien zugeordnet - erst umordnen oder Umhängen aktivieren.")
        repo.delete_category(db, category_id)
        return

    for child in children:
        repo.move_category(db, child.id, category.parent_id)
    if file_count:
        files, _ = repo.list_files_for_category(db, [category_id], limit=100000)
        for f in files:
            repo.assign_file_category(db, f.id, category.parent_id, assigned_by=f.category_assigned_by or "user")
    repo.delete_category(db, category_id)


def delete_category_subtree(db: Session, category_id: str) -> None:
    """Loest einen Knoten und alle Unterknoten auf und uebernimmt ihre Dateien in die Elternkategorie."""
    category = repo.get_category_by_id(db, category_id)
    if not category:
        raise ValueError("Kategorie nicht gefunden.")
    category_ids = repo.get_category_descendant_ids(db, category_id)
    db.query(File).filter(File.category_id.in_(category_ids)).update(
        {
            File.category_id: category.parent_id,
            File.category_assigned_by: "user" if category.parent_id else None,
            File.category_needs_review: False,
            File.category_review_reason: None,
        },
        synchronize_session=False,
    )
    db.delete(category)
    db.commit()


def get_or_create_category_path(db: Session, segments: list[str], created_by: str = "user") -> Category | None:
    """Findet/erzeugt eine Knotenkette anhand einer Breadcrumb-Segmentliste, gibt den Blattknoten zurueck."""
    normalized_segments = [_normalize_name(s) for s in segments if _normalize_name(s)]
    if not normalized_segments:
        return None
    normalized_segments = normalized_segments[:_MAX_DEPTH]
    parent_id: str | None = None
    node: Category | None = None
    for segment in normalized_segments:
        node = repo.get_child_category_by_name(db, parent_id, segment)
        if not node:
            node = repo.create_category(db, segment, parent_id=parent_id, created_by=created_by)
        parent_id = node.id
    return node


def assign_category_manually(db: Session, file_id: str, category_id: str | None) -> None:
    """Manuelle Zuordnung durch den Nutzer; wird von der KI danach nie mehr ueberschrieben."""
    if category_id and not repo.get_category_by_id(db, category_id):
        raise ValueError("Kategorie nicht gefunden.")
    repo.assign_file_category(db, file_id, category_id, assigned_by="user", needs_review=False)


def assign_categories_manually(db: Session, file_ids: list[str], category_id: str | None) -> None:
    """Weist mehrere Dateien atomar einer Kategorie zu oder entfernt ihre Zuordnung."""
    unique_file_ids = list(dict.fromkeys(file_ids))
    if not unique_file_ids:
        raise ValueError("Mindestens eine Datei muss ausgewählt sein.")
    if category_id and not repo.get_category_by_id(db, category_id):
        raise ValueError("Kategorie nicht gefunden.")

    files = []
    for file_id in unique_file_ids:
        file_record = repo.get_file_by_id(db, file_id)
        if not file_record:
            raise ValueError("Mindestens eine Datei wurde nicht gefunden.")
        files.append(file_record)

    for file_record in files:
        file_record.category_id = category_id
        file_record.category_assigned_by = "user" if category_id else None
        file_record.category_needs_review = False
        file_record.category_review_reason = None
    db.commit()


def list_files_for_category(
    db: Session, category_id: str, include_subtree: bool = True, status: str | None = None,
    limit: int = 500, offset: int = 0,
) -> tuple[list[dict], int]:
    category_ids = list(repo.get_category_descendant_ids(db, category_id)) if include_subtree else [category_id]
    files, total = repo.list_files_for_category(db, category_ids, status=status, limit=limit, offset=offset)
    return files, total


# ---------------------------------------------------------------------------
# KI-Kategorisierung
# ---------------------------------------------------------------------------

_CONFIDENCE_HIGH = {"hoch", "high", "sicher"}


def _parse_category_response(response: str) -> tuple[list[str] | None, bool]:
    """Parst die haeufigsten LLM-Antwortformen, ohne unsichere Pfade zu uebernehmen."""
    segments, needs_review, _ = _parse_category_response_details(response)
    return segments, needs_review


def _parse_category_response_details(response: str) -> tuple[list[str] | None, bool, str]:
    """Parst einen Kategoriepfad und liefert zusaetzlich die Modellaktion."""
    text = (response or "").strip()
    if not text:
        return None, True, "review"

    candidate = text.strip()
    candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE).strip()
    try:
        payload = json.loads(candidate)
        if isinstance(payload, dict):
            path_value = payload.get("path") or payload.get("category") or payload.get("kategorie")
            confidence_value = payload.get("confidence") or payload.get("sicherheit")
            action = str(payload.get("action") or "").strip().lower()
            if isinstance(path_value, list):
                segments = [_normalize_name(str(item)) for item in path_value]
            else:
                segments = [_normalize_name(part) for part in str(path_value or "").split(">")]
            confidence = str(confidence_value or "").strip().lower()
            segments = [segment for segment in segments if segment]
            if action not in {"existing", "create", "review"}:
                action = "review" if confidence not in _CONFIDENCE_HIGH else "create"
            if action == "review" or confidence not in _CONFIDENCE_HIGH or not segments:
                return None, True, "review"
            return (None, True, "review") if segments[0].lower() == "unklar" else (segments, False, action)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    first_line = next((line.strip().strip("` ") for line in text.splitlines() if line.strip()), "")
    if "|" not in first_line:
        return None, True
    path_part, confidence_part = first_line.rsplit("|", 1)
    confidence = confidence_part.lower()
    confidence_word = next(
        (word for word in _CONFIDENCE_HIGH if re.search(rf"\b{re.escape(word)}\b", confidence)),
        None,
    )
    if not confidence_word:
        return None, True, "review"
    segments = [_normalize_name(segment) for segment in path_part.split(">")]
    segments = [segment for segment in segments if segment]
    if not segments or segments[0].lower() == "unklar":
        return None, True, "review"
    return segments, False, "create"


def _build_tree_paths(db: Session) -> list[str]:
    categories = repo.list_categories(db)
    return sorted({c.path() for c in categories})


def _validate_category_segments(file_record, segments: list[str]) -> str | None:
    """Verhindert unpassende oder ausufernde KI-Pfade vor dem automatischen Anlegen."""
    if not segments or len(segments) > _MAX_DEPTH:
        return "Der KI-Kategoriepfad ist leer oder zu tief verschachtelt."
    expected_root = _ROOTS_BY_CONTENT_TYPE.get(file_record.content_type or "", "Sonstiges")
    if segments[0].casefold() != expected_root.casefold():
        return f"Die Stammkategorie '{segments[0]}' passt nicht zum Dateityp."
    if any(not segment or segment.casefold() in {"unklar", "unbekannt", "undefined", "null"} for segment in segments):
        return "Der KI-Kategoriepfad enthält ein ungültiges Segment."
    return None


def _fallback_category_segments(file_record, created_at: str | None = None) -> list[str] | None:
    """Erzeugt bei einer unbrauchbaren KI-Antwort eine sichere Basiskategorie."""
    roots = {
        "images": "Bilder",
        "documents": "Dokumente",
        "audio": "Audio",
        "video": "Video",
    }
    root = roots.get(file_record.content_type or "", "Sonstiges")
    date_value = created_at or file_record.created_at or file_record.imported_at or ""
    year_match = re.search(r"\b(19|20)\d{2}\b", date_value)
    year = year_match.group(0) if year_match else "Unbekanntes Jahr"
    return [root, year, "Sonstiges"]


def _build_file_context(
    file_record, text_context: str, tags: list[str] | None = None, sidecar_path: Path | None = None,
    created_at: str | None = None,
) -> str:
    """Baut einen begrenzten, strukturierten Kontext fuer die Kategorie-KI."""
    all_tags = sorted(set(getattr(file_record, "tags", []) or []) | set(tags or []))
    sections = [
        "DATEI",
        f"Dateiname: {file_record.original_filename}",
        f"Dateityp: {file_record.content_type or 'unbekannt'}",
        f"MIME-Typ: {file_record.mime_type or 'unbekannt'}",
        f"Dateigroesse: {file_record.file_size or 0} Bytes",
        f"Erstellungsdatum: {created_at or file_record.created_at or 'unbekannt'}",
        f"Importdatum: {file_record.imported_at or 'unbekannt'}",
        f"SHA256: {file_record.sha256 or 'unbekannt'}",
        f"Tags: {', '.join(all_tags) or '(keine)'}",
        f"Nutzerbeschreibung: {file_record.user_description or '(keine)'}",
        f"KI-Zusammenfassung: {file_record.ai_summary or '(keine)'}",
    ]
    chunks = getattr(file_record, "chunks", []) or []
    chunk_lines = []
    for chunk in chunks:
        marker = f"Typ={chunk.chunk_type or 'text'}, Seite={chunk.page or '-'}, Abschnitt={chunk.section or '-'}"
        chunk_lines.append(f"[{marker}]\n{chunk.text}")
    if text_context and not chunk_lines:
        chunk_lines.append(text_context)
    # Bei sehr vielen Chunks über das gesamte Dokument sampeln statt nur den Anfang
    # abzuschneiden, damit auch lange Dokumente vollständig repräsentiert sind.
    from app.services import chunking_service
    content_text = chunking_service.sample_chunk_texts(chunk_lines, max_chars=14000, max_samples=20)
    sections.extend(["INHALT / OCR / TRANSKRIPT", content_text or "(kein Inhalt)"])

    if sidecar_path:
        try:
            from app.services import sidecar_service
            sidecar_json = sidecar_service.read_json_sidecar(sidecar_path)
            sidecar_md = sidecar_service.read_md_sidecar(sidecar_path)
            if sidecar_json:
                sections.extend(["JSON-SIDECAR", json.dumps(sidecar_json, ensure_ascii=False, indent=2)[:6000]])
            if sidecar_md:
                sections.extend(["MARKDOWN-SIDECAR", sidecar_md[:6000]])
        except (OSError, ValueError, TypeError) as exc:
            logger.debug("Sidecar fuer Kategorisierung nicht lesbar: %s", exc)
    return "\n\n".join(sections)[:32000]


def suggest_category(
    db: Session, text_context: str, content_type: str | None, tags: list[str] | None = None,
    file_context: str | None = None,
) -> tuple[list[str] | None, bool]:
    """Ermittelt per KI einen Breadcrumb-Pfad fuer die Kategorisierung.

    Gibt (segments, needs_review) zurueck. `segments` ist None, wenn die KI sich nicht sicher
    genug war - in diesem Fall ist `needs_review` True und es wird KEINE Kategorie erfunden.
    """
    segments, needs_review, _, _ = _suggest_category_result(
        db, file_context or text_context, content_type, tags=tags
    )
    return segments, needs_review


def _suggest_category_result(
    db: Session, text_context: str, content_type: str | None, tags: list[str] | None = None,
) -> tuple[list[str] | None, bool, str, str]:
    """Liefert zusätzlich zur Kategorie die rohe KI-Antwort und den Review-Grund."""
    text_context = (text_context or "").strip()
    if not text_context:
        return None, True, "", "Kein verwertbarer Inhalt für eine sichere Kategorisierung vorhanden."
    try:
        from app.config import get_config

        ollama = _get_categorization_ollama_service(get_config())
        if not ollama.is_available():
            return None, True, "", "Der KI-Dienst ist nicht erreichbar."

        existing_paths = _build_tree_paths(db)
        existing_str = "\n".join(f"- {p}" for p in existing_paths) if existing_paths else "(noch keine vorhanden)"
        type_label = {
            "documents": "Dokument", "images": "Bild", "audio": "Audio-Datei", "video": "Video-Datei",
        }.get(content_type or "", "Datei")
        tags_str = ", ".join(tags) if tags else "(keine)"

        prompt = (
            "Ordne diese Datei in eine hierarchische Kategorie-Struktur ein. Du MUSST auch bei "
            "unsicherem Inhalt einen einfachen, nuetzlichen Pfad waehlen. Verwende dafuer immer "
            "diese drei Schritte:\n"
            "1. Ebene: sichere Stammkategorie aus dem Dateityp: Bilder, Dokumente, Audio, Video "
            "oder Sonstiges.\n"
            "2. Ebene: das Jahr aus Erstellungsdatum, EXIF, Dokumentdatum oder Importdatum. "
            "Wenn kein Jahr vorhanden ist, verwende 'Unbekanntes Jahr'.\n"
            "3. Ebene: genau EIN abstraktes Stichwort aus Zusammenfassung, Sidecar, OCR, Tags "
            "oder Metadaten. Beispiele: Personen, Tiere, Garten, Reise, Rechnung, Buch, "
            "Anleitung, Vertrag oder Sonstiges. Bei Bildern mit erkannten Personen verwende "
            "'Personen'. Bei Dokumenten ohne klares Thema verwende 'Sonstiges'.\n"
            "Weitere Ebenen darfst du nur anlegen, wenn sie aus den Daten wirklich sicher "
            "hervorgehen. Erfinde keine Namen, Autoren oder Orte. 'Sonstiges' ist besser als "
            "eine unsichere Detailkategorie. Eine leere oder unklare Antwort ist NICHT erlaubt.\n"
            "Nutze nach Moeglichkeit einen der folgenden bereits vorhandenen Pfade. Wenn keine "
            "Kategorie passt, darfst du einen neuen konkreten Pfad vorschlagen; der Code legt "
            "nur die fehlenden Segmente an.\n"
            f"Bereits vorhandene Kategorie-Pfade:\n{existing_str}\n\n"
            f"Dateityp fuer die Einordnung: {type_label}\n"
            f"Vorhandene Tags: {tags_str}\n\n"
            f"Vollstaendiger Dateikontext:\n{text_context}\n\n"
            "Antworte in GENAU EINER Zeile im Format:\n"
            "Segment1 > Segment2 > Segment3|<hoch|niedrig>\n"
            "Alternativ als JSON mit action existing, create oder review:\n"
            '{"action":"create","path":["Dokumente","2026","Neue Fachkategorie"],"confidence":"hoch"}\n'
            "Verwende 'hoch', wenn Stammkategorie und Jahr aus den Dateidaten sicher sind, "
            "auch wenn die dritte Ebene 'Sonstiges' lautet. Verwende 'niedrig' nur, wenn selbst "
            "Dateityp und Jahr fehlen. Antworte niemals 'unklar|niedrig', wenn ein Dateityp oder "
            "ein Datum vorhanden ist.\n"
            "Keine Erklaerung, kein weiterer Text."
        )
        response = ollama.generate(prompt)
        segments, needs_review = _parse_category_response(response)
        reason = "" if not needs_review else "Die KI konnte keine eindeutig sichere Kategorie bestimmen."
        return segments, needs_review, response or "", reason
    except Exception as exc:
        logger.warning("Kategorie-Vorschlag fehlgeschlagen: %s", exc)
        return None, True, "", f"Fehler bei der KI-Kategorisierung: {exc}"


def suggest_and_assign_category(
    db: Session, file_id: str, text_context: str, content_type: str | None, tags: list[str] | None = None,
    sidecar_path: Path | None = None, created_at: str | None = None,
) -> str | None:
    """Ermittelt per KI eine Kategorie und weist sie zu, ausser der Nutzer hat die Datei bereits manuell eingeordnet."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        return None
    if f.category_assigned_by == "user":
        return None  # manuelle Zuordnung wird von der KI nie ueberschrieben

    file_context = _build_file_context(
        f, text_context, tags=tags, sidecar_path=sidecar_path, created_at=created_at
    )
    segments, needs_review, ai_response, review_reason = _suggest_category_result(
        db, file_context, content_type, tags=tags
    )
    if not segments:
        if needs_review:
            repo.assign_file_category(
                db, file_id, None, assigned_by="ai", needs_review=True,
                ai_response=ai_response, review_reason=review_reason,
            )
            return None
        fallback_segments = _fallback_category_segments(f, created_at=created_at)
        if fallback_segments:
            category = get_or_create_category_path(db, fallback_segments, created_by="ai")
            if category:
                repo.assign_file_category(
                    db, file_id, category.id, assigned_by="ai", needs_review=False,
                    ai_response=ai_response,
                )
                return category.path()
        repo.assign_file_category(
            db, file_id, None, assigned_by="ai", needs_review=needs_review,
            ai_response=ai_response, review_reason=review_reason,
        )
        return None

    validation_error = _validate_category_segments(f, segments)
    if validation_error:
        repo.assign_file_category(
            db, file_id, None, assigned_by="ai", needs_review=True,
            ai_response=ai_response, review_reason=validation_error,
        )
        return None

    category = get_or_create_category_path(db, segments, created_by="ai")
    if not category:
        repo.assign_file_category(
            db, file_id, None, assigned_by="ai", needs_review=True,
            ai_response=ai_response, review_reason="Der KI-Kategoriepfad konnte nicht angelegt werden.",
        )
        return None

    repo.assign_file_category(
        db, file_id, category.id, assigned_by="ai", needs_review=False,
        ai_response=ai_response,
    )
    return category.path()


def categorize_all_uncategorized(db: Session) -> dict:
    """Batch-Nachkategorisierung aller bisher unkategorisierten, verarbeiteten Dateien."""
    files = repo.list_uncategorized_files(db)
    categorized = 0
    flagged_for_review = 0
    for f in files:
        from app.services import chunking_service
        context_text = f.ai_summary or chunking_service.sample_chunk_texts([chunk.text for chunk in f.chunks])
        if not context_text:
            context_text = f.original_filename
        tags = f.tags
        from app.config import get_config
        from app.services.archive_service import resolve_archive_path
        sidecar_path = resolve_archive_path(f.archive_path, get_config().paths.archive_root)
        path = suggest_and_assign_category(
            db, f.id, context_text, f.content_type, tags=tags, sidecar_path=sidecar_path,
            created_at=f.created_at,
        )
        if path:
            categorized += 1
        else:
            db.refresh(f)
            if f.category_needs_review:
                flagged_for_review += 1
    return {
        "processed": len(files),
        "categorized": categorized,
        "flagged_for_review": flagged_for_review,
    }


def run_categorize_all_uncategorized_job(job_id: str, db: Session) -> None:
    """Fuehrt die Batch-Nachkategorisierung aus und protokolliert das Ergebnis im ProcessingJob (siehe /jobs)."""
    repo.start_job(db, job_id)
    try:
        result = categorize_all_uncategorized(db)
        log = (
            f"{result['processed']} Datei(en) geprüft, {result['categorized']} kategorisiert, "
            f"{result['flagged_for_review']} zur Prüfung markiert."
        )
        repo.finish_job(db, job_id, success=True, log=log)
    except Exception as exc:
        logger.warning("Batch-Kategorisierung fehlgeschlagen: %s", exc)
        repo.finish_job(db, job_id, success=False, error_message=str(exc))

