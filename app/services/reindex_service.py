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

        clip_clap_counts = _reindex_clip_clap_embeddings(db)

        _update_index_meta(db)
        repo.finish_job(
            db,
            job.id,
            success=True,
            log=(
                f"{len(all_chunks)} Chunks re-embedded, "
                f"{clip_clap_counts['images']} CLIP-Bild- und "
                f"{clip_clap_counts['audio']} CLAP-Audio-Embeddings neu erstellt"
            ),
        )
        logger.info("Reindex Modus A abgeschlossen.")
        return {
            "success": True,
            "chunks_reindexed": len(all_chunks),
            "clip_embeddings_reindexed": clip_clap_counts["images"],
            "clap_embeddings_reindexed": clip_clap_counts["audio"],
        }

    except Exception as exc:
        logger.error("Reindex Modus A fehlgeschlagen: %s", exc)
        repo.finish_job(db, job.id, success=False, error_message=str(exc))
        return {"success": False, "error": str(exc)}


def _reindex_clip_clap_embeddings(db: Session) -> dict:
    """Baut CLIP-Bild- und CLAP-Audio-Embeddings aus den Sidecar-JSONs neu auf.

    `reindex_vectors_only` löscht ALLE Chroma-Collections (inkl.
    image_embeddings/audio_embeddings), re-embedded aber nur SQLite-Chunks -
    ohne diese Funktion blieben CLIP/CLAP-Suche nach Modus A leer.
    """
    from app.config import get_config
    from app.db.models import File
    from app.processors.audio_processor import AudioProcessor
    from app.processors.image_processor import ImageProcessor
    from app.services import archive_service, sidecar_service

    cfg = get_config()
    counts = {"images": 0, "audio": 0}

    if getattr(cfg.processing, "enable_clip_embeddings", False):
        image_processor = ImageProcessor()
        images = (
            db.query(File)
            .filter(File.content_type == "images", File.status != "deleted")
            .all()
        )
        for f in images:
            if not f.archive_path:
                continue
            path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
            if not path.exists():
                continue
            sd = sidecar_service.read_json_sidecar(path) or {}
            vision_description = sd.get("vision_description", "")
            try:
                image_processor._store_clip_embedding(path, f, cfg, vision_description)
                counts["images"] += 1
            except Exception as exc:
                logger.warning("CLIP-Reindex fehlgeschlagen für %s: %s", f.original_filename, exc)

    if getattr(cfg.processing, "enable_clap_embeddings", False):
        audio_processor = AudioProcessor()
        audio_files = (
            db.query(File)
            .filter(File.content_type == "audio", File.status != "deleted")
            .all()
        )
        for f in audio_files:
            if not f.archive_path:
                continue
            path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
            if not path.exists():
                continue
            sd = sidecar_service.read_json_sidecar(path) or {}
            audio_meta = sd.get("audio_metadata", {})
            text_repr = sd.get("summary") or sd.get("transcript_sample") or f.original_filename
            try:
                audio_processor._store_clap_embedding(path, f, cfg, audio_meta, text_repr)
                counts["audio"] += 1
            except Exception as exc:
                logger.warning("CLAP-Reindex fehlgeschlagen für %s: %s", f.original_filename, exc)

    return counts


def _snapshot_manual_data(db: Session) -> dict:
    """Sichert alle manuell gepflegten Daten vor dem Löschen der `files`-Tabelle
    in Modus B, da Faces/Cluster/Best-of-Serie per FK-CASCADE mitgelöscht werden
    und File-IDs beim Re-Import neu vergeben werden. Schlüssel ist immer der
    sha256-Hash, da dieser über den Rebuild hinweg stabil bleibt.
    """
    from app.db.models import File, FaceEncoding, PersonCluster

    files = db.query(File).all()
    by_id = {f.id: f for f in files}

    tags = {f.sha256: f.tags for f in files if f.tags}

    # Nur manuell bestätigte "beste Aufnahme"-Gruppen sichern (best_manually_set
    # steht auf der besten Datei der Gruppe, siehe repositories.set_best_file)
    best_groups: list[tuple[str, list[str]]] = []
    for f in files:
        if not f.best_manually_set:
            continue
        others = [o.sha256 for o in files if o.best_file_id == f.id]
        if others:
            best_groups.append((f.sha256, others))

    # Gesichts-Labels je Datei sichern (sha256 -> [(face_index, cluster_label), ...])
    face_labels: dict[str, list[tuple[int, str]]] = {}
    clusters_by_id = {c.id: c for c in db.query(PersonCluster).all()}
    for fe in db.query(FaceEncoding).all():
        cluster = clusters_by_id.get(fe.cluster_id) if fe.cluster_id else None
        if not cluster or not cluster.label:
            continue
        file = by_id.get(fe.file_id)
        if not file:
            continue
        face_labels.setdefault(file.sha256, []).append((fe.face_index, cluster.label))

    return {
        "descriptions": {f.sha256: f.user_description for f in files if f.user_description},
        "tags": tags,
        "best_groups": best_groups,
        "face_labels": face_labels,
    }


def _restore_manual_data(db: Session, snapshot: dict) -> dict:
    """Stellt die von `_snapshot_manual_data` gesicherten Daten nach dem
    Re-Import anhand des sha256-Hashs wieder her. Keine Garantie: Dateien, die
    sich inhaltlich geändert haben oder fehlgeschlagen sind, bleiben unversorgt.
    """
    from app.db.models import File, FaceEncoding, PersonCluster

    from app.services import tag_service

    files_by_sha = {f.sha256: f for f in db.query(File).all()}
    counts = {"tags": 0, "best_groups": 0, "face_labels": 0}

    for sha, tag_names in snapshot["tags"].items():
        f = files_by_sha.get(sha)
        if f:
            for name in tag_names:
                tag_service.assign_tag(db, f.id, name, added_by="user")
            counts["tags"] += 1
    db.commit()

    for best_sha, other_shas in snapshot["best_groups"]:
        best_file = files_by_sha.get(best_sha)
        if not best_file:
            continue
        other_ids = [files_by_sha[s].id for s in other_shas if s in files_by_sha]
        if other_ids:
            repo.set_best_file(db, best_file.id, other_ids, manually_set=True)
            counts["best_groups"] += 1

    if snapshot["face_labels"]:
        cluster_by_label = {c.label: c for c in db.query(PersonCluster).all() if c.label}
        for sha, face_entries in snapshot["face_labels"].items():
            f = files_by_sha.get(sha)
            if not f:
                continue
            encodings_by_index = {
                fe.face_index: fe
                for fe in db.query(FaceEncoding).filter(FaceEncoding.file_id == f.id).all()
            }
            for face_index, label in face_entries:
                fe = encodings_by_index.get(face_index)
                if not fe:
                    continue
                cluster = cluster_by_label.get(label)
                if cluster is None:
                    cluster = PersonCluster(
                        id=str(uuid.uuid4()), label=label,
                        created_at=datetime.now().isoformat(),
                    )
                    db.add(cluster)
                    db.flush()
                    cluster_by_label[label] = cluster
                fe.cluster_id = cluster.id
                counts["face_labels"] += 1
        db.commit()

    return counts


def full_rebuild(db: Session, archive_root: Path, resume: bool = False) -> dict:
    """
    Modus B: Vollständiger Rebuild aus dem Filesystem.
    SQLite-Datensätze und Chroma werden komplett neu aufgebaut.

    resume=True: Setzt einen zuvor durch einen App-Neustart unterbrochenen
    Rebuild fort - bereits importierte/fertig verarbeitete Dateien bleiben
    unangetastet, nur fehlende Dateien werden importiert und die zuletzt
    (evtl. nur teilweise) verarbeitete Datei wird zur Sicherheit erneut
    indexiert.
    """
    from app.services import chroma_service
    from app.services.ingestion_service import import_file, process_file

    mode_label = "Fortsetzung eines unterbrochenen Rebuilds" if resume else "Vollständiger Rebuild"
    logger.info("Reindex Modus B (%s) aus %s…", mode_label, archive_root)
    job = repo.create_job(db, file_id=None, job_type="reindex_full")
    repo.start_job(db, job.id)
    # Wird erst nach erfolgreichem/fehlgeschlagenem Abschluss geloescht - bleibt bei
    # hartem Abbruch (Kill/Absturz) stehen und dient als Marker fuer die Fortsetzung
    # beim naechsten App-Start (siehe ingestion_service.requeue_interrupted_jobs).
    repo.set_setting(db, "reindex_full_in_progress", job.id)

    try:
        from app.db.models import Chunk, File, ProcessingJob
        saved_descriptions: dict[str, str] = {}
        snapshot: dict = {}

        if not resume:
            # Manuelle Daten vor dem Löschen sichern (sha256-Hash bleibt stabil)
            snapshot = _snapshot_manual_data(db)
            saved_descriptions = snapshot["descriptions"]
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
        skipped = 0
        errors = 0
        for original in original_files:
            try:
                result = import_file(original, db, archive_root)
                if result["status"] == "imported":
                    process_file(result["file_id"], db)
                    imported += 1
                elif resume and result["status"] == "duplicate":
                    existing = repo.get_file_by_id(db, result["file_id"])
                    if existing and existing.status != "processed":
                        # Datei stand beim Abbruch noch mitten in der Verarbeitung -
                        # zur Sicherheit von vorne (ohne evtl. unvollständige Chunks) neu indexieren.
                        repo.delete_chunks_for_file(db, existing.id)
                        for col in chroma_service.COLLECTIONS.values():
                            chroma_service.delete_by_file_id(col, existing.id)
                        process_file(existing.id, db)
                        imported += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.error("Fehler beim Rebuild von %s: %s", original.name, exc)
                errors += 1

        # Nutzer-Beschreibungen wiederherstellen (nur bei Löschen der Files-Tabelle nötig)
        if not resume and saved_descriptions:
            from app.services import chroma_service as _cs, embedding_service as _es
            from datetime import datetime
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
                            "created_year": datetime.now().year,
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

        restored_counts = (
            _restore_manual_data(db, snapshot) if not resume
            else {"tags": 0, "best_groups": 0, "face_labels": 0}
        )
        logger.info(
            "Rebuild: wiederhergestellt - Tags: %d, "
            "Best-of-Serie-Gruppen: %d, Gesichts-Labels: %d",
            restored_counts["tags"],
            restored_counts["best_groups"], restored_counts["face_labels"],
        )

        _update_index_meta(db)
        summary = (
            f"Modus: {'Fortsetzung' if resume else 'voll'}, "
            f"Imported/reindexiert: {imported}, Übersprungen: {skipped}, Fehler: {errors}, "
            f"wiederhergestellt: Beschreibungen={len(saved_descriptions)}, "
            f"Tags={restored_counts['tags']}, "
            f"Best-of-Serie={restored_counts['best_groups']}, "
            f"Gesichts-Labels={restored_counts['face_labels']}"
        )
        repo.finish_job(db, job.id, success=True, log=summary)
        repo.set_setting(db, "reindex_full_in_progress", "")
        logger.info("Reindex Modus B abgeschlossen. %s", summary)
        return {"success": True, "imported": imported, "skipped": skipped, "errors": errors, **restored_counts}

    except Exception as exc:
        logger.error("Reindex Modus B fehlgeschlagen: %s", exc)
        repo.finish_job(db, job.id, success=False, error_message=str(exc))
        repo.set_setting(db, "reindex_full_in_progress", "")
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
        "last_reindex_at": datetime.now().isoformat(),
    }
    repo.set_setting(db, "index_meta", json.dumps(meta))
