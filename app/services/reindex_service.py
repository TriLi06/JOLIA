from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import repositories as repo

logger = logging.getLogger(__name__)


def reindex_vectors_only(db: Session) -> dict:
    """
    Modus A: Nur ChromaDB-Index neu aufbauen.
    Chunks aus SQLite bleiben erhalten; Embeddings werden neu generiert.
    """
    from app.services import chroma_service, embedding_service

    logger.info("Reindex Modus A: Nur Vektorindex neu aufbauen…")
    job = repo.create_job(db, file_id=None, job_type="reindex_vectors")
    repo.start_job(db, job.id)

    try:
        for col in chroma_service.COLLECTIONS.values():
            chroma_service.delete_all(col)

        all_chunks = repo.get_all_chunks(db)
        logger.info("Re-embedding %d Chunks…", len(all_chunks))

        batch_size = 64
        for i in range(0, len(all_chunks), batch_size):
            batch = all_chunks[i : i + batch_size]
            texts = [c.text for c in batch]
            embeddings = embedding_service.embed_texts(texts)
            collection_names = [c.chroma_collection or "text_chunks" for c in batch]
            for col_name in set(collection_names):
                idxs = [j for j, c in enumerate(batch) if (c.chroma_collection or "text_chunks") == col_name]
                chroma_service.upsert_chunks(
                    col_name,
                    ids=[batch[j].chroma_id or str(uuid.uuid4()) for j in idxs],
                    texts=[texts[j] for j in idxs],
                    embeddings=[embeddings[j] for j in idxs],
                    metadatas=[
                        {
                            "file_id": batch[j].file_id,
                            "chunk_id": batch[j].id,
                            "source_path": batch[j].file.archive_path if batch[j].file else "",
                            "file_name": batch[j].file.original_filename if batch[j].file else "",
                            "content_type": batch[j].file.content_type if batch[j].file else "other",
                            "chunk_type": batch[j].chunk_type or "text",
                            "page": batch[j].page or 0,
                        }
                        for j in idxs
                    ],
                )

        _update_index_meta(db)
        repo.finish_job(db, job.id, success=True, log=f"{len(all_chunks)} Chunks re-embedded")
        logger.info("Reindex Modus A abgeschlossen.")
        return {"success": True, "chunks_reindexed": len(all_chunks)}

    except Exception as exc:
        logger.error("Reindex Modus A fehlgeschlagen: %s", exc)
        repo.finish_job(db, job.id, success=False, error_message=str(exc))
        return {"success": False, "error": str(exc)}


def full_rebuild(db: Session, archive_root: Path) -> dict:
    """
    Modus B: Vollständiger Rebuild aus dem Filesystem.
    SQLite-Datensätze und Chroma werden komplett neu aufgebaut.
    """
    from app.services import chroma_service
    from app.services.ingestion_service import import_file, process_file

    logger.info("Reindex Modus B: Vollständiger Rebuild aus %s…", archive_root)
    job = repo.create_job(db, file_id=None, job_type="reindex_full")
    repo.start_job(db, job.id)

    try:
        # Nutzer-Beschreibungen vor dem Löschen sichern (sha256 → description)
        from app.db.models import Chunk, File, ProcessingJob
        saved_descriptions: dict[str, str] = {
            f.sha256: f.user_description
            for f in db.query(File).all()
            if f.user_description
        }
        if saved_descriptions:
            logger.info("Rebuild: %d Nutzer-Beschreibungen gesichert.", len(saved_descriptions))

        # Abgeleitete Daten leeren
        db.query(Chunk).delete()
        db.query(ProcessingJob).filter(ProcessingJob.job_type != "reindex_full").delete()
        db.query(File).delete()
        db.commit()

        for col in chroma_service.COLLECTIONS.values():
            chroma_service.delete_all(col)

        # Alle Original-Dateien scannen (keine Sidecars)
        original_files = [
            f for f in archive_root.rglob("*")
            if f.is_file()
            and not f.name.endswith(".json")
            and not f.name.endswith(".md")
        ]
        logger.info("Rebuild: %d Originaldateien gefunden.", len(original_files))

        imported = 0
        errors = 0
        for original in original_files:
            try:
                result = import_file(original, db, archive_root)
                if result["status"] == "imported":
                    process_file(result["file_id"], db)
                    imported += 1
            except Exception as exc:
                logger.error("Fehler beim Rebuild von %s: %s", original.name, exc)
                errors += 1

        # Nutzer-Beschreibungen wiederherstellen
        if saved_descriptions:
            from app.services import chroma_service as _cs, embedding_service as _es
            from datetime import datetime, timezone as _tz
            restored = 0
            for file_record in db.query(File).all():
                desc = saved_descriptions.get(file_record.sha256)
                if not desc:
                    continue
                repo.update_user_description(db, file_record.id, desc)
                content_label = {
                    "audio": "Audio-Datei",
                    "video": "Video-Datei",
                    "images": "Bild-Datei",
                    "documents": "Dokument",
                }.get(file_record.content_type or "", "Datei")
                chunk_text = (
                    f"Datei: {file_record.original_filename}\n"
                    f"Typ: {content_label}\n"
                    f"Nutzer-Beschreibung: {desc}"
                )
                chunk_id = str(uuid.uuid4())
                collection_map = {
                    "audio": "audio_transcripts",
                    "video": "audio_transcripts",
                    "images": "image_descriptions",
                }
                col_name = collection_map.get(file_record.content_type or "", "text_chunks")
                try:
                    embedding = _es.embed_text(chunk_text)
                    _cs.upsert_chunks(
                        col_name,
                        ids=[chunk_id],
                        texts=[chunk_text],
                        embeddings=[embedding],
                        metadatas=[{
                            "file_id": file_record.id,
                            "chunk_id": chunk_id,
                            "source_path": file_record.archive_path,
                            "file_name": file_record.original_filename,
                            "content_type": file_record.content_type or "",
                            "chunk_type": "user_description",
                            "page": 0,
                            "created_year": datetime.now(_tz.utc).year,
                        }],
                    )
                    repo.create_chunk(db, **{
                        "id": chunk_id,
                        "file_id": file_record.id,
                        "chunk_index": 9000,
                        "chunk_type": "user_description",
                        "text": chunk_text,
                        "chroma_collection": col_name,
                        "chroma_id": chunk_id,
                    })
                    restored += 1
                except Exception as desc_exc:
                    logger.warning("Beschreibung für %s konnte nicht wiederhergestellt werden: %s",
                                   file_record.original_filename, desc_exc)
            if restored:
                logger.info("Rebuild: %d Nutzer-Beschreibungen wiederhergestellt.", restored)

        _update_index_meta(db)
        summary = f"Imported: {imported}, Fehler: {errors}"
        repo.finish_job(db, job.id, success=True, log=summary)
        logger.info("Reindex Modus B abgeschlossen. %s", summary)
        return {"success": True, "imported": imported, "errors": errors}

    except Exception as exc:
        logger.error("Reindex Modus B fehlgeschlagen: %s", exc)
        repo.finish_job(db, job.id, success=False, error_message=str(exc))
        return {"success": False, "error": str(exc)}


def _update_index_meta(db: Session) -> None:
    from app.config import get_config
    cfg = get_config()
    import json
    meta = {
        "embedding_model": cfg.models.embedding_model,
        "chunking_version": "1.0",
        "ocr_engine": "tesseract",
        "pipeline_version": "1.0",
        "last_reindex_at": datetime.now(timezone.utc).isoformat(),
    }
    repo.set_setting(db, "index_meta", json.dumps(meta))
