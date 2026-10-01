from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.db import repositories as repo

logger = logging.getLogger(__name__)

_MAX_NAME_LEN = 64
_MAX_DESCRIPTION_LEN = 500


def _normalize_name(name: str) -> str:
    name = (name or "").strip().strip(" .\"'“”")
    name = " ".join(name.split())
    return name[:_MAX_NAME_LEN]


def list_albums(db: Session) -> list[dict]:
    return [
        {"id": album.id, "name": album.name, "description": album.description, "count": count}
        for album, count in repo.list_albums(db)
    ]


def create_album(db: Session, name: str, description: str | None = None, created_by: str = "user") -> dict:
    """Legt ein neues Album an (Name muss eindeutig sein)."""
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Album-Name darf nicht leer sein.")
    if repo.get_album_by_name(db, normalized):
        raise ValueError(f"Ein Album mit dem Namen '{normalized}' existiert bereits.")
    description = (description or "").strip()[:_MAX_DESCRIPTION_LEN] or None
    album = repo.create_album(db, normalized, description=description, created_by=created_by)
    return {"id": album.id, "name": album.name, "description": album.description}


def delete_album(db: Session, album_id: str) -> None:
    """Loescht ein Album global; es wird dabei von allen Dateien entfernt."""
    repo.delete_album(db, album_id)


def update_album(db: Session, album_id: str, name: str, description: str | None = None) -> dict:
    """Aktualisiert Name und Beschreibung eines bestehenden Albums."""
    normalized = _normalize_name(name)
    if not normalized:
        raise ValueError("Album-Name darf nicht leer sein.")
    existing = repo.get_album_by_name(db, normalized)
    if existing and existing.id != album_id:
        raise ValueError(f"Ein Album mit dem Namen '{normalized}' existiert bereits.")
    description = (description or "").strip()[:_MAX_DESCRIPTION_LEN] or None
    album = repo.update_album(db, album_id, normalized, description)
    if not album:
        raise ValueError("Album nicht gefunden.")
    return {"id": album.id, "name": album.name, "description": album.description}


def get_file_albums(db: Session, file_id: str) -> list[dict]:
    return [{"id": a.id, "name": a.name} for a in repo.get_albums_for_file(db, file_id)]


def assign_album(db: Session, file_id: str, album_id: str, added_by: str = "user") -> dict:
    """Weist einer Datei ein bestehendes Album zu."""
    album = repo.get_album_by_id(db, album_id)
    if not album:
        raise ValueError("Album nicht gefunden.")
    repo.add_file_album(db, file_id, album_id, added_by=added_by)
    _reembed_file_albums(db, file_id)
    return {"id": album.id, "name": album.name}


def unassign_album(db: Session, file_id: str, album_id: str) -> None:
    """Entfernt ein Album von einer Datei; das Album selbst bleibt in der globalen Liste bestehen."""
    repo.remove_file_album(db, file_id, album_id)
    _reembed_file_albums(db, file_id)


def bulk_add_files_to_album(db: Session, album_id: str, file_ids: list[str]) -> int:
    """Fuegt alle uebergebenen Dateien einem Album hinzu (z.B. anhand aktueller Filterkriterien)."""
    album = repo.get_album_by_id(db, album_id)
    if not album:
        raise ValueError("Album nicht gefunden.")
    for file_id in file_ids:
        repo.add_file_album(db, file_id, album_id)
        _reembed_file_albums(db, file_id)
    return len(file_ids)


def bulk_remove_files_from_album(db: Session, album_id: str, file_ids: list[str]) -> int:
    """Entfernt alle uebergebenen Dateien aus einem Album, sofern sie darin waren."""
    album = repo.get_album_by_id(db, album_id)
    if not album:
        raise ValueError("Album nicht gefunden.")
    for file_id in file_ids:
        repo.remove_file_album(db, file_id, album_id)
        _reembed_file_albums(db, file_id)
    return len(file_ids)


def _reembed_file_albums(db: Session, file_id: str) -> None:
    """Aktualisiert den durchsuchbaren Album-Text-Chunk in ChromaDB nach Aenderung der Alben einer Datei."""
    try:
        from app.services import chroma_service, embedding_service

        f = repo.get_file_by_id(db, file_id)
        if not f:
            return
        chroma_id = f"albums-{file_id}"
        album_names = [a["name"] for a in get_file_albums(db, file_id)]
        if not album_names:
            try:
                chroma_service.delete_ids("file_summaries", [chroma_id])
            except Exception:
                pass
            return
        text = "Alben: " + ", ".join(album_names)
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
                "chunk_type": "albums",
                "page": 0,
            }],
        )
    except Exception as exc:
        logger.warning("Album-Embedding fuer Datei %s fehlgeschlagen: %s", file_id, exc)
