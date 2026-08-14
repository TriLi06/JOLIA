from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.services.archive_service import calculate_archive_path, move_to_archive, resolve_archive_path
from app.services.file_type_service import detect_file_type, is_ignored
from app.services.hashing_service import compute_sha256

logger = logging.getLogger(__name__)

_PROCESSOR_REGISTRY: dict | None = None

# Begrenzt gleichzeitig laufende process_file()-Aufrufe (Watcher + manuelle Uploads
# teilen sich dieses Limit), da jeder Aufruf eine DB-Session ueber die gesamte
# Verarbeitungsdauer offen haelt (OCR/Embeddings/LLM koennen bei grossen Dateien lange
# dauern) - ohne Begrenzung koennen bei vielen parallelen Jobs mehr Sessions offen sein
# als der SQLAlchemy-Connection-Pool erlaubt, was zu QueuePool-Timeouts fuehrt.
_processing_semaphore: threading.Semaphore | None = None
_processing_semaphore_size: int | None = None


def _get_processing_semaphore() -> threading.Semaphore:
    global _processing_semaphore, _processing_semaphore_size
    from app.config import get_config
    size = max(1, get_config().processing.max_concurrent_processing)
    if _processing_semaphore is None or _processing_semaphore_size != size:
        _processing_semaphore = threading.Semaphore(size)
        _processing_semaphore_size = size
    return _processing_semaphore


def _get_processor_registry() -> dict:
    global _PROCESSOR_REGISTRY
    if _PROCESSOR_REGISTRY is None:
        from app.processors.audio_processor import AudioProcessor
        from app.processors.docx_processor import DocxProcessor
        from app.processors.eml_processor import EmlProcessor
        from app.processors.generic_processor import GenericProcessor
        from app.processors.html_processor import HtmlProcessor
        from app.processors.image_processor import ImageProcessor
        from app.processors.odt_processor import OdtProcessor
        from app.processors.pdf_processor import PdfProcessor
        from app.processors.pptx_processor import PptxProcessor
        from app.processors.text_processor import TextProcessor
        from app.processors.video_processor import VideoProcessor
        from app.processors.xlsx_processor import XlsxProcessor

        _PROCESSOR_REGISTRY = {
            "application/pdf": PdfProcessor(),
            "text/plain": TextProcessor(),
            "text/markdown": TextProcessor(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxProcessor(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": XlsxProcessor(),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": PptxProcessor(),
            "application/vnd.oasis.opendocument.text": OdtProcessor(),
            "message/rfc822": EmlProcessor(),
            "text/html": HtmlProcessor(),
            "image/jpeg": ImageProcessor(),
            "image/png": ImageProcessor(),
            "image/tiff": ImageProcessor(),
            "image/heic": ImageProcessor(),
            "image/webp": ImageProcessor(),
            "image/bmp": ImageProcessor(),
            "audio/mpeg": AudioProcessor(),
            "audio/mp4": AudioProcessor(),
            "audio/wav": AudioProcessor(),
            "audio/flac": AudioProcessor(),
            "audio/ogg": AudioProcessor(),
            "audio/aac": AudioProcessor(),
            "video/mp4": VideoProcessor(),
            "video/x-matroska": VideoProcessor(),
            "video/x-msvideo": VideoProcessor(),
            "video/quicktime": VideoProcessor(),
            "video/webm": VideoProcessor(),
            "__default__": GenericProcessor(),
        }
    return _PROCESSOR_REGISTRY


def scan_inbox(inbox_path: Path) -> list[Path]:
    """Gibt alle importierbaren Dateien im Inbox zurück."""
    if not inbox_path.exists():
        logger.warning("Inbox-Ordner existiert nicht: %s", inbox_path)
        return []
    files = [f for f in inbox_path.iterdir() if f.is_file() and not is_ignored(f)]
    logger.info("Inbox-Scan: %d Dateien gefunden in %s", len(files), inbox_path)
    return files


def import_file(file_path: Path, db: Session, archive_root: Path) -> dict:
    """Importiert eine einzelne Datei: Hash → Duplikat-Check → Archivierung → DB."""
    logger.info("Importiere Datei: %s", file_path.name)

    sha256 = compute_sha256(file_path)
    existing = repo.get_file_by_sha256(db, sha256)
    if existing:
        logger.info("Duplikat erkannt: %s (existiert als %s)", file_path.name, existing.archive_path)
        return {"status": "duplicate", "file_id": existing.id, "filename": file_path.name}

    mime_type, content_type = detect_file_type(file_path)
    file_size = file_path.stat().st_size
    now = datetime.now()

    file_id = str(uuid.uuid4())
    target_path = calculate_archive_path(archive_root, file_path.name, content_type, now, file_id)
    target_path = move_to_archive(file_path, target_path)
    # Relativ zu archive_root speichern, damit ein Umbenennen/Verschieben des
    # Archiv-Root-Ordners bereits importierte Dateien nicht verwaist.
    relative_archive_path = target_path.relative_to(archive_root)
    file_record = repo.create_file(
        db,
        id=file_id,
        sha256=sha256,
        original_filename=file_path.name,
        archive_path=str(relative_archive_path),
        mime_type=mime_type,
        content_type=content_type,
        file_size=file_size,
        imported_at=now.isoformat(),
        status="imported",
    )

    return {
        "status": "imported",
        "file_id": file_record.id,
        "filename": file_path.name,
        "archive_path": str(relative_archive_path),
        "mime_type": mime_type,
        "content_type": content_type,
    }


def process_file(file_id: str, db: Session) -> None:
    """Verarbeitet eine importierte Datei: Processor → Sidecar → Chunks → Embeddings."""
    from app.config import get_config
    from app.services import chroma_service, embedding_service

    cfg = get_config()
    file_record = repo.get_file_by_id(db, file_id)
    if not file_record:
        logger.error("Datei nicht gefunden: %s", file_id)
        return

    job = repo.create_job(db, file_id=file_id, job_type="process")
    repo.start_job(db, job.id)
    repo.update_file_status(db, file_id, "processing")

    try:
        file_path = resolve_archive_path(file_record.archive_path, cfg.paths.archive_root)
        if not file_path.exists():
            raise FileNotFoundError(f"Archivdatei nicht gefunden: {file_path}")

        registry = _get_processor_registry()
        processor = registry.get(file_record.mime_type or "", registry["__default__"])

        result = processor.process(file_path, file_record, cfg)

        if not result.success:
            raise RuntimeError(result.error_message or "Processor-Fehler")

        # Chunks in SQLite speichern
        if result.chunks:
            chunk_records = [
                {
                    "id": str(uuid.uuid4()),
                    "file_id": file_id,
                    "chunk_index": c.chunk_index,
                    "chunk_type": c.chunk_type,
                    "text": c.text,
                    "page": c.page,
                    "section": c.section,
                    "chroma_collection": _collection_for_content_type(file_record.content_type),
                    "chroma_id": str(uuid.uuid4()),
                }
                for c in result.chunks
            ]
            chunk_objs = repo.bulk_create_chunks(db, chunk_records)

            # Embeddings berechnen und in ChromaDB speichern (optional – schlägt fehl wenn kein Backend verfügbar)
            try:
                texts = [c.text for c in result.chunks]
                embeddings = embedding_service.embed_texts(texts)
                collection_name = _collection_for_content_type(file_record.content_type)
                chroma_ids = [cr["chroma_id"] for cr in chunk_records]
                chroma_metadatas = [
                    {
                        "file_id": file_id,
                        "chunk_id": cr["id"],
                        "source_path": file_record.archive_path,
                        "file_name": file_record.original_filename,
                        "content_type": file_record.content_type or "other",
                        "created_year": datetime.now().year,
                        "page": cr.get("page") or 0,
                    }
                    for cr in chunk_records
                ]
                chroma_service.upsert_chunks(
                    collection_name, chroma_ids, texts, embeddings, chroma_metadatas
                )
            except Exception as emb_exc:
                logger.warning(
                    "Embeddings für %s konnten nicht erstellt werden (Backend nicht verfügbar): %s – "
                    "Datei wurde ohne Vektorindex gespeichert. Reindexierung später möglich.",
                    file_record.original_filename,
                    emb_exc,
                )

        # Gesichtserkennung für Bilder (wenn aktiviert)
        face_count = 0
        if file_record.content_type == "images" and cfg.processing.enable_face_detection:
            try:
                from app.services import face_service
                face_count = face_service.detect_and_store_faces(file_path, file_id, db)
                if face_count > 0:
                    logger.info("Gesichtserkennung: %d Gesicht(er) in %s", face_count, file_record.original_filename)
                    # Sidecar-JSON mit Gesichtsanzahl aktualisieren
                    from app.services import sidecar_service as sc
                    sidecar_data = sc.read_json_sidecar(file_path)
                    if sidecar_data:
                        sidecar_data["face_count"] = face_count
                        sc.write_json_sidecar(file_path, sidecar_data)
                    # Sidecar-MD mit Gesichtsanzahl neu generieren
                    if result.sidecar_md_path:
                        from app.services import sidecar_service as sc
                        updated_md = sc.build_image_md(
                            original_filename=file_record.original_filename,
                            ocr_text=sidecar_data.get("ocr_text", "") if sidecar_data else "",
                            metadata=result.metadata or {},
                            vision_description=sidecar_data.get("vision_description", "") if sidecar_data else "",
                            face_count=face_count,
                        )
                        sc.write_md_sidecar(file_path, updated_md)
                    # Gesichts-Info als durchsuchbaren Chunk in ChromaDB speichern
                    try:
                        face_text = (
                            f"Dateiname: {file_record.original_filename}\n"
                            f"Anzahl erkannter Gesichter/Personen: {face_count}"
                        )
                        face_embedding = embedding_service.embed_text(face_text)
                        face_chunk_id = str(uuid.uuid4())
                        chroma_service.upsert_chunks(
                            collection_name="image_descriptions",
                            ids=[face_chunk_id],
                            texts=[face_text],
                            embeddings=[face_embedding],
                            metadatas=[{
                                "file_id": file_id,
                                "chunk_id": face_chunk_id,
                                "source_path": file_record.archive_path,
                                "file_name": file_record.original_filename,
                                "content_type": "images",
                                "chunk_type": "faces",
                                "face_count": face_count,
                                "created_year": datetime.now().year,
                                "page": 0,
                            }],
                        )
                    except Exception as emb_exc:
                        logger.warning("Gesichts-Chunk Embedding fehlgeschlagen: %s", emb_exc)
            except Exception as face_exc:
                logger.warning("Gesichtserkennung fehlgeschlagen für %s: %s", file_record.original_filename, face_exc)

        now_iso = datetime.now().isoformat()

        # Thumbnail für Bilder und PDFs generieren (Vorschau in Timeline-/Listenansicht)
        is_pdf = file_path.suffix.lower() == ".pdf"
        if file_record.content_type == "images" or is_pdf:
            try:
                from app.services import thumbnail_service
                rel_path = thumbnail_service.generate_and_store(file_path, file_id, cfg.paths.data_dir)
                if rel_path:
                    repo.update_file_thumbnail(db, file_id, rel_path)
            except Exception as thumb_exc:
                logger.warning("Thumbnail-Erstellung fehlgeschlagen für %s: %s", file_record.original_filename, thumb_exc)

        # KI-Zusammenfassung generieren und speichern
        ai_summary = None
        try:
            from app.services import summarization_service
            sidecar_data_for_summary = None
            if file_record.content_type == "images":
                from app.services import sidecar_service as sc
                sidecar_data_for_summary = sc.read_json_sidecar(file_path)
                ai_summary = summarization_service.generate_image_summary(
                    vision_description=sidecar_data_for_summary.get("vision_description", "") if sidecar_data_for_summary else "",
                    exif_meta=sidecar_data_for_summary.get("exif", {}) if sidecar_data_for_summary else {},
                    face_count=sidecar_data_for_summary.get("face_count") if sidecar_data_for_summary else face_count or None,
                )
            else:
                # Für Dokumente: ersten Chunk-Text nutzen
                first_chunk_text = result.chunks[0].text if result.chunks else ""
                ai_summary = summarization_service.generate_document_summary(first_chunk_text)
            if ai_summary:
                repo.update_file_summary(db, file_id, ai_summary)
                # In Sidecar-JSON speichern
                from app.services import sidecar_service as sc
                sd = sc.read_json_sidecar(file_path)
                if sd is not None:
                    sd["ai_summary"] = ai_summary
                    sc.write_json_sidecar(file_path, sd)
                # Sidecar-MD bei Bildern mit Summary aktualisieren
                if file_record.content_type == "images" and result.sidecar_md_path:
                    sd2 = sd if sd is not None else (sidecar_data_for_summary or {})
                    updated_md = sc.build_image_md(
                        original_filename=file_record.original_filename,
                        ocr_text=sd2.get("ocr_text", ""),
                        metadata=result.metadata or {},
                        vision_description=sd2.get("vision_description", ""),
                        face_count=sd2.get("face_count"),
                        ai_summary=ai_summary,
                    )
                    sc.write_md_sidecar(file_path, updated_md)
                logger.info("KI-Zusammenfassung gespeichert für %s", file_record.original_filename)
        except Exception as sum_exc:
            logger.warning("KI-Zusammenfassung fehlgeschlagen für %s: %s", file_record.original_filename, sum_exc)

        # Tags (z.B. Rechnung, Arzt, Homöopathie) per KI ermitteln und zuweisen
        if cfg.processing.enable_tag_suggestion:
            try:
                from app.services import tag_service
                context_text = ai_summary or (result.chunks[0].text if result.chunks else "")
                assigned = tag_service.suggest_and_assign_tags(
                    db, file_id, context_text, is_image=file_record.content_type == "images"
                )
                if assigned:
                    logger.info("Tags %s zugewiesen für %s", assigned, file_record.original_filename)
            except Exception as tag_exc:
                logger.warning(
                    "Tag-Vorschlag fehlgeschlagen für %s: %s",
                    file_record.original_filename, tag_exc,
                )

        # Inhaltliches Erstellungsdatum fuer die Timeline bestimmen:
        # Bilder liefern es aus EXIF (result.created_at), fuer Dokumente wird ein
        # beschriftetes Belegdatum (z.B. Rechnungsdatum) aus dem Text extrahiert.
        created_at = result.created_at
        if not created_at and file_record.content_type == "documents":
            try:
                from app.services import document_date_service
                doc_text = "\n".join(c.text for c in result.chunks[:5]) if result.chunks else ""
                created_at = document_date_service.extract_document_date(doc_text)
            except Exception as date_exc:
                logger.warning("Datumserkennung fehlgeschlagen für %s: %s", file_record.original_filename, date_exc)
        if created_at:
            repo.update_file_created_at(db, file_id, created_at)

        repo.update_file_status(
            db,
            file_id,
            status="needs_review" if result.needs_review else "processed",
            processed_at=now_iso,
            sidecar_json_path=result.sidecar_json_path,
            sidecar_md_path=result.sidecar_md_path,
        )
        if result.sharpness_score is not None or result.perceptual_hash is not None:
            repo.update_file_image_metrics(
                db, file_id, result.sharpness_score, result.perceptual_hash
            )
        repo.finish_job(db, job.id, success=True, log=f"{len(result.chunks)} Chunks erstellt")
        # Neue Gesichter/GPS-Daten/Hashes koennen entstanden sein: naechsten Cluster-Job-Tick anstossen.
        from app.services.scheduler_service import mark_dirty
        mark_dirty(db)
        logger.info("Datei verarbeitet: %s (%d Chunks)", file_record.original_filename, len(result.chunks))

    except Exception as exc:
        logger.error("Fehler bei Verarbeitung von %s: %s", file_record.original_filename, exc)
        repo.update_file_status(db, file_id, status="failed", error_message=str(exc))
        repo.finish_job(db, job.id, success=False, error_message=str(exc))


def _reprocess_after_restart(file_id: str) -> None:
    """Verarbeitet eine Datei erneut in einem eigenen DB-Thread (nach App-Neustart)."""
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    # Semaphore VOR dem Öffnen der DB-Session erwerben (siehe _get_processing_semaphore).
    with _get_processing_semaphore():
        db = _SessionLocal()
        try:
            process_file(file_id, db)
        except Exception:
            logger.exception("Erneute Verarbeitung von Datei %s nach Neustart fehlgeschlagen.", file_id)
        finally:
            db.close()


def _recovery_worker(file_ids: list[str]) -> None:
    """Arbeitet unterbrochene Dateien nach einem Neustart NACHEINANDER ab.

    Bewusst sequentiell (nicht ein Thread pro Datei), damit die Wiederaufnahme
    nicht alle Slots des Verarbeitungs-Semaphors belegt und Ollama saettigt -
    interaktive Aktionen (z.B. manuelles "Neu verarbeiten") bleiben so moeglich.
    """
    for file_id in file_ids:
        _reprocess_after_restart(file_id)
    logger.info("Wiederaufnahme nach Neustart abgeschlossen (%d Datei(en)).", len(file_ids))


def _resume_full_rebuild_worker() -> None:
    """Setzt einen beim letzten App-Neustart unterbrochenen vollständigen
    Rebuild (Modus B) fort, statt ihn stillschweigend als fehlgeschlagen
    stehen zu lassen.
    """
    from app.config import get_config
    from app.db.database import _SessionLocal
    from app.services import reindex_service
    if _SessionLocal is None:
        return
    cfg = get_config()
    db = _SessionLocal()
    try:
        reindex_service.full_rebuild(db, cfg.paths.archive_root, resume=True)
    except Exception:
        logger.exception("Fortsetzung des unterbrochenen vollständigen Rebuilds fehlgeschlagen.")
    finally:
        db.close()


def requeue_interrupted_jobs() -> int:
    """Beim App-Start aufrufen: durch einen Absturz unterbrochene Verarbeitung
    erkennen und erneut anstossen.

    - Alle noch offenen Jobs (Status 'running'/'queued') werden als unterbrochen
      markiert, damit die Jobliste nicht dauerhaft auf "Running" haengen bleibt.
    - War darunter ein unterbrochener vollständiger Rebuild (Modus B), wird
      dieser in einem Hintergrund-Worker fortgesetzt (bereits fertig verarbeitete
      Dateien werden uebersprungen, die zuletzt evtl. nur teilweise verarbeitete
      Datei wird zur Sicherheit erneut indexiert).
    - Andernfalls werden einzelne Dateien, die im Status 'processing'/'queued'
      stecken geblieben sind, in EINEM sequentiellen Hintergrund-Worker erneut
      verarbeitet.

    Gibt die Anzahl erneut eingeplanter Dateien zurueck.
    """
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return 0

    db = _SessionLocal()
    file_ids: list[str] = []
    try:
        # 1) Haengengebliebene Jobs abschliessen, damit die UI nicht ewig "Running" zeigt.
        for job in repo.list_unfinished_jobs(db):
            repo.finish_job(
                db,
                job.id,
                success=False,
                error_message="Durch App-Neustart unterbrochen; Verarbeitung wird erneut gestartet.",
            )
        # 2) Dateien einsammeln, die mitten in der Verarbeitung unterbrochen wurden.
        file_ids = repo.list_file_ids_by_status(db, ["processing", "queued"])
        # Marker aus full_rebuild(): bleibt bei hartem Abbruch stehen (wird nur bei
        # normalem Abschluss geloescht), unabhaengig vom Job-Status.
        interrupted_full_rebuild = bool(repo.get_setting(db, "reindex_full_in_progress"))
    finally:
        db.close()

    if interrupted_full_rebuild:
        # Der fortgesetzte Rebuild scannt ohnehin das gesamte Archiv erneut und
        # deckt damit auch die oben eingesammelten file_ids mit ab.
        logger.info("Unterbrochener vollständiger Rebuild (Modus B) erkannt - wird fortgesetzt.")
        threading.Thread(target=_resume_full_rebuild_worker, daemon=True).start()
        return len(file_ids)

    if not file_ids:
        return 0

    logger.info(
        "%d unterbrochene Datei(en) werden nach dem Neustart erneut verarbeitet.",
        len(file_ids),
    )
    threading.Thread(target=_recovery_worker, args=(file_ids,), daemon=True).start()
    return len(file_ids)


def _collection_for_content_type(content_type: str | None) -> str:
    mapping = {
        "images": "image_descriptions",
        "audio": "audio_transcripts",
        "video": "audio_transcripts",
    }
    return mapping.get(content_type or "", "text_chunks")
