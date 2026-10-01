from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db import repositories as repo

logger = logging.getLogger(__name__)

_MAX_NAME_LEN = 64

# Feld-/Kategoriebezeichnungen statt konkreter Werte, die die KI trotz Prompt gelegentlich
# vorschlaegt (z.B. "Anlass" statt "Geburtstag"); werden aus KI-Vorschlaegen herausgefiltert.
_GENERIC_LABEL_BLOCKLIST = {
    "kategorie", "anlass", "marke", "person", "titel", "typ", "art", "thema",
    "kontakt", "material", "ort", "name", "gegenstand", "ereignis", "produkt",
}


def list_tags(db: Session) -> list[dict]:
    return [{"name": tag.name, "count": count} for tag, count in repo.list_tags(db)]


def _normalize_name(name: str) -> str:
    name = (name or "").strip().strip(" .\"'“”")
    name = name.lstrip("#*")  # Nutzer geben Tags oft mit #/* Praefix ein (siehe Beispiele)
    name = " ".join(name.split())
    return name[:_MAX_NAME_LEN]


def add_tag(db: Session, name: str, created_by: str = "user") -> str:
    """Legt einen Tag global an (idempotent) und gibt den normierten Namen zurueck."""
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Tag-Name darf nicht leer sein.")
    existing = repo.get_tag_by_name(db, normalized)
    if existing:
        return existing.name
    tag = repo.create_tag(db, normalized, created_by=created_by)
    return tag.name


def delete_tag(db: Session, name: str) -> None:
    """Loescht einen Tag global; er wird dabei von allen Dateien entfernt."""
    repo.delete_tag(db, name)


def get_file_tags(db: Session, file_id: str) -> list[str]:
    return [t.name for t in repo.get_tags_for_file(db, file_id)]


def assign_tag(db: Session, file_id: str, name: str, added_by: str = "user") -> str:
    """Weist einer Datei einen Tag zu (legt ihn bei Bedarf global an)."""
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Tag-Name darf nicht leer sein.")
    tag = repo.add_file_tag(db, file_id, normalized, added_by=added_by)
    _reembed_file_tags(db, file_id)
    return tag.name


def unassign_tag(db: Session, file_id: str, name: str) -> None:
    """Entfernt einen Tag von einer Datei; der Tag selbst bleibt in der globalen Liste bestehen."""
    repo.remove_file_tag(db, file_id, name)
    _reembed_file_tags(db, file_id)


def _reembed_file_tags(db: Session, file_id: str) -> None:
    """Aktualisiert den durchsuchbaren Tag-Text-Chunk in ChromaDB nach Aenderung der Tags einer Datei."""
    try:
        from app.services import chroma_service, embedding_service

        f = repo.get_file_by_id(db, file_id)
        if not f:
            return
        chroma_id = f"tags-{file_id}"
        tag_names = get_file_tags(db, file_id)
        if not tag_names:
            try:
                chroma_service.delete_ids("file_summaries", [chroma_id])
            except Exception:
                pass
            return
        text = "Tags: " + ", ".join(tag_names)
        embedding = embedding_service.embed_text(text)
        chroma_service.upsert_chunks(
            collection_name="file_summaries",
            ids=[chroma_id],
            texts=[text],
            embeddings=[embedding],
            metadatas=[{
                "file_id": file_id,
                "chunk_id": chroma_id,
                "source_path": f.archive_path,
                "file_name": f.original_filename,
                "content_type": f.content_type or "other",
                "chunk_type": "tags",
                "page": 0,
            }],
        )
    except Exception as exc:
        logger.warning("Tag-Embedding fuer Datei %s fehlgeschlagen: %s", file_id, exc)


def suggest_tags(db: Session, text_context: str, is_image: bool = False) -> list[str]:
    """Ermittelt per KI passende Tags (bestehende oder neue) anhand eines Textkontexts."""
    text_context = (text_context or "").strip()
    if not text_context:
        return []
    try:
        from app.services.ollama_service import get_background_ollama_service

        ollama = get_background_ollama_service()
        if not ollama.is_available():
            return []

        existing = [t["name"] for t in list_tags(db)]
        existing_str = ", ".join(existing) if existing else "(noch keine vorhanden)"
        kind = "Bildes" if is_image else "Dokuments"
        prompt = (
            f"Bestimme passende Tags fuer dieses {kind} auf Deutsch.\n"
            "Die Tags muessen sich DIREKT aus dem folgenden Inhalt ableiten lassen (konkrete "
            "Begriffe, Namen, Gegenstaende, Orte, Themen, die tatsaechlich im Inhalt vorkommen "
            "oder eindeutig daraus hervorgehen). Erfinde NICHTS und uebernimm KEINE Tags, die "
            "inhaltlich nicht zu diesem Dokument passen.\n"
            "Ein Tag ist immer ein KONKRETER WERT (ein Eigenname, ein Ort, eine Marke, ein "
            "Ereignis, ein Gegenstand, eine Person, ...), NIEMALS die Bezeichnung einer "
            "Kategorie oder eines Feldes. Nenne also z.B. 'Geburtstag' statt 'Anlass', "
            "'Tissot' statt 'Marke', 'Oliver Brang' statt 'Person', 'Zahnarzt Dr. Meyer' "
            "statt 'Kontakt'. Wörter wie Kategorie, Anlass, Marke, Person, Titel, Typ, Art, "
            "Thema, Kontakt oder Material duerfen NIEMALS selbst als Tag auftauchen.\n"
            "Beispiele fuer gute Tags an einer Datei: 'Rechnung, Arzt, Homöopathie, Louisa' "
            "oder 'Auto, Werkstatt, Astra, TÜV' oder 'Kassenbon, DM_Drogerie' oder "
            "'Baumarkt, Bauhaus, Holz'.\n"
            f"Bereits vorhandene Tags (nur zur Wiederverwendung, falls sie WIRKLICH zum Inhalt "
            f"passen): {existing_str}\n"
            "Nutze einen vorhandenen Tag NUR, wenn er inhaltlich exakt passt. Erzeuge in allen "
            "anderen Faellen lieber einen neuen, treffenden Tag statt einen vorhandenen nur "
            "deshalb zu waehlen, weil er bereits existiert. Vorhandene Tags sind KEIN Hinweis "
            "darauf, worum es in diesem Dokument geht.\n"
            "Nutze mindestens 2 Tags, ausser dem Inhalt laesst sich wirklich keine Information "
            "entnehmen - dann antworte mit einer leeren Zeile. "
            "Antworte NUR mit einer kommagetrennten Liste von Tags, ohne Erklaerung, ohne Satzzeichen.\n\n"
            f"Inhalt:\n{text_context[:800]}"
        )
        response = ollama.generate(prompt)
        raw_tags = [t.strip() for t in response.replace("\n", ",").split(",")]
        seen: set[str] = set()
        result: list[str] = []
        for raw in raw_tags:
            normalized = _normalize_name(raw)
            if not normalized or normalized.lower() in seen:
                continue
            if normalized.lower() in _GENERIC_LABEL_BLOCKLIST:
                continue  # KI schlaegt trotz Prompt manchmal die Feld-/Kategoriebezeichnung statt eines Werts vor
            seen.add(normalized.lower())
            result.append(normalized)
        return result
    except Exception as exc:
        logger.warning("Tag-Vorschlag fehlgeschlagen: %s", exc)
        return []


def suggest_and_assign_tags(db: Session, file_id: str, text_context: str, is_image: bool = False) -> list[str]:
    """Ermittelt per KI Tags und weist sie der Datei zu (legt neue Tags mit created_by='ai' an)."""
    suggested = suggest_tags(db, text_context, is_image=is_image)
    assigned: list[str] = []
    for name in suggested:
        normalized = _normalize_name(name)
        if not normalized:
            continue
        tag = repo.add_file_tag(db, file_id, normalized, added_by="ai")
        assigned.append(tag.name)
    if assigned:
        _reembed_file_tags(db, file_id)
    return assigned
