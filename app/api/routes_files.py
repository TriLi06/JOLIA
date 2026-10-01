from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse as FastAPIFileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo
from app.services import archive_service, ingestion_service

router = APIRouter()


class FileResponse(BaseModel):
    id: str
    original_filename: str
    archive_path: str
    mime_type: str | None
    content_type: str | None
    tags: list[str] = []
    albums: list[str] = []
    file_size: int | None
    status: str
    imported_at: str
    processed_at: str | None
    error_message: str | None
    created_at: str | None = None
    ai_summary: str | None = None
    thumbnail_path: str | None = None
    sharpness_score: float | None = None
    best_file_id: str | None = None
    category_id: str | None = None
    category_path: str | None = None
    category_needs_review: bool = False
    category_ai_response: str | None = None
    category_review_reason: str | None = None

    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    items: list[FileResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=FileListResponse)
def list_files(
    content_type: str | None = None,
    tags: list[str] | None = Query(None),
    albums: list[str] | None = Query(None),
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    if q or date_from or date_to:
        items, total = repo.search_files(
            db, q_text=q, content_type=content_type, tags=tags, albums=albums, status=status,
            date_from=date_from, date_to=date_to, limit=limit, offset=offset,
        )
    else:
        items, total = repo.list_files(
            db, content_type=content_type, tags=tags, albums=albums, status=status,
            limit=limit, offset=offset,
        )
    return FileListResponse(
        items=[FileResponse.model_validate(f) for f in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/timeline")
def list_files_timeline(
    content_type: str | None = None,
    tags: list[str] | None = Query(None),
    albums: list[str] | None = Query(None),
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_session),
):
    """Liefert Dateien nach Kalendertag gruppiert (Aufnahme-/Importdatum) fuer die Timeline-Ansicht."""
    items = repo.list_files_by_day(
        db, q_text=q, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    days: dict[str, list] = {}
    for f in items:
        raw = f.created_at or f.imported_at or ""
        day = raw[:10] if raw else "unbekannt"
        days.setdefault(day, []).append(FileResponse.model_validate(f).model_dump())
    ordered = [{"date": day, "files": files} for day, files in sorted(days.items(), reverse=True)]
    return {"days": ordered}


@router.get("/timeline/days")
def list_files_timeline_days(
    content_type: str | None = None,
    tags: list[str] | None = Query(None),
    albums: list[str] | None = Query(None),
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_session),
):
    """Liefert nur die Kalendertage mit Anzahl (guenstig) - Basis fuer das lazy-ladende Timeline-Scrolling."""
    days = repo.count_files_by_day(
        db, q_text=q, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    total = sum(d["count"] for d in days)
    return {"days": days, "total": total}


@router.get("/timeline/day")
def list_files_timeline_day(
    date: str = Query(...),
    content_type: str | None = None,
    tags: list[str] | None = Query(None),
    albums: list[str] | None = Query(None),
    status: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_session),
):
    """Liefert die Dateien eines einzelnen Kalendertags - wird beim Timeline-Scrollen bedarfsgesteuert geladen."""
    items = repo.list_files_for_day(
        db, date, q_text=q, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    return {
        "date": date,
        "files": [FileResponse.model_validate(f).model_dump() for f in items],
    }


@router.get("/{file_id}/download")
def download_file(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    cfg = get_config()
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht im Archiv vorhanden")
    return FastAPIFileResponse(
        path=str(archive_path),
        filename=f.original_filename,
        media_type=f.mime_type or "application/octet-stream",
    )


@router.get("/{file_id}", response_model=FileResponse)
def get_file(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    return FileResponse.model_validate(f)


@router.post("/import-inbox")
def import_inbox(background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    cfg = get_config()
    files = ingestion_service.scan_inbox(cfg.paths.inbox)

    if not files:
        return {"queued": 0, "message": "Keine neuen Dateien in der Inbox."}

    results = []
    for file_path in files:
        result = ingestion_service.import_file(file_path, db, cfg.paths.archive_root)
        results.append(result)
        if result["status"] == "imported":
            file_id = result["file_id"]
            background_tasks.add_task(_process_in_background, file_id)

    imported = sum(1 for r in results if r["status"] == "imported")
    duplicates = sum(1 for r in results if r["status"] == "duplicate")
    return {
        "queued": imported,
        "duplicates": duplicates,
        "total_found": len(files),
        "message": f"{imported} Dateien importiert, {duplicates} Duplikate übersprungen.",
    }


@router.post("/{file_id}/reprocess")
def reprocess_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    repo.update_file_status(db, file_id, "queued")
    background_tasks.add_task(_process_in_background, file_id)
    return {"message": "Verarbeitung neu gestartet.", "file_id": file_id}


@router.patch("/{file_id}/review-text")
def update_review_text(
    file_id: str,
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_session),
):
    """Korrektur von OCR-Text für Handschriften; triggert Re-Embedding."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    corrected_text = payload.get("text", "").strip()
    if not corrected_text:
        raise HTTPException(status_code=400, detail="Kein Text übermittelt.")

    from app.services import sidecar_service
    cfg = get_config()
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)

    # Korrigierten Text in MD-Sidecar speichern
    md_content = sidecar_service.build_image_md(
        f.original_filename,
        corrected_text,
        {"SHA256": f.sha256, "Korrektur": "Manuell korrigiert"},
    )
    md_path = sidecar_service.write_md_sidecar(archive_path, md_content)
    repo.update_file_status(db, file_id, "processed", sidecar_md_path=str(md_path))

    # Chunks löschen und Datei neu einbetten
    repo.delete_chunks_for_file(db, file_id)
    background_tasks.add_task(_process_in_background, file_id)
    return {"message": "Text gespeichert. Re-Embedding wird durchgeführt."}


@router.patch("/{file_id}/mark-reviewed")
def mark_reviewed(
    file_id: str,
    db: Session = Depends(get_session),
):
    """Markiert eine needs_review-Datei als processed, ohne den Text zu ändern."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    repo.update_file_status(db, file_id, "processed")
    f.category_needs_review = False
    f.category_review_reason = None
    db.commit()
    return {"message": "Datei als verarbeitet markiert.", "file_id": file_id}


@router.patch("/{file_id}/mark-reviewed")
def mark_reviewed(
    file_id: str,
    db: Session = Depends(get_session),
):
    """Markiert eine needs_review-Datei als processed, ohne den Text zu ändern."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    repo.update_file_status(db, file_id, "processed")
    f.category_needs_review = False
    f.category_review_reason = None
    db.commit()
    return {"message": "Datei als verarbeitet markiert.", "file_id": file_id}


@router.patch("/{file_id}/user-description")
def update_user_description(
    file_id: str,
    payload: dict,
    db: Session = Depends(get_session),
):
    """Speichert eine manuelle Beschreibung und indexiert sie als durchsuchbaren Chunk."""
    import uuid as _uuid
    from datetime import datetime
    from app.services import chroma_service, embedding_service

    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    description = payload.get("description", "").strip()

    # Bestehenden user_description-Chunk aus SQLite und Chroma entfernen
    existing = [c for c in repo.get_chunks_for_file(db, file_id) if c.chunk_type == "user_description"]
    for c in existing:
        if c.chroma_collection and c.chroma_id:
            try:
                col = chroma_service._get_collection(c.chroma_collection)
                col.delete(ids=[c.chroma_id])
            except Exception:
                pass
        db.delete(c)
    db.commit()

    # Beschreibung speichern (auch wenn leer – dann nur löschen)
    repo.update_user_description(db, file_id, description or None)

    if description:
        chunk_id = str(_uuid.uuid4())
        content_label = {
            "audio": "Audio-Datei",
            "video": "Video-Datei",
            "images": "Bild-Datei",
            "documents": "Dokument",
        }.get(f.content_type or "", "Datei")
        chunk_text = (
            f"Datei: {f.original_filename}\n"
            f"Typ: {content_label}\n"
            f"Nutzer-Beschreibung: {description}"
        )
        try:
            embedding = embedding_service.embed_text(chunk_text)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Embedding fehlgeschlagen: {exc}")

        # Passende Chroma-Collection je nach Content-Type
        collection_map = {
            "audio": "audio_transcripts",
            "video": "audio_transcripts",
            "images": "image_descriptions",
        }
        collection_name = collection_map.get(f.content_type or "", "text_chunks")

        chroma_service.upsert_chunks(
            collection_name=collection_name,
            ids=[chunk_id],
            texts=[chunk_text],
            embeddings=[embedding],
            metadatas=[{
                "file_id": file_id,
                "chunk_id": chunk_id,
                "source_path": f.archive_path,
                "file_name": f.original_filename,
                "content_type": f.content_type or "",
                "chunk_type": "user_description",
                "page": 0,
                "created_year": datetime.now().year,
            }],
        )

        # Chunk in SQLite speichern
        repo.create_chunk(db, **{
            "id": chunk_id,
            "file_id": file_id,
            "chunk_index": 9000,
            "chunk_type": "user_description",
            "text": chunk_text,
            "chroma_collection": collection_name,
            "chroma_id": chunk_id,
        })

    return {"message": "Beschreibung gespeichert.", "file_id": file_id}


class FileTagCreate(BaseModel):
    name: str


@router.get("/{file_id}/tags")
def get_file_tags(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import tag_service
    return {"items": tag_service.get_file_tags(db, file_id)}


@router.post("/{file_id}/tags")
def add_file_tag(file_id: str, payload: FileTagCreate, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import tag_service
    try:
        name = tag_service.assign_tag(db, file_id, payload.name, added_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Tag hinzugefügt.", "file_id": file_id, "name": name}


@router.delete("/{file_id}/tags/{name}")
def remove_file_tag(file_id: str, name: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import tag_service
    tag_service.unassign_tag(db, file_id, name)
    return {"message": "Tag entfernt.", "file_id": file_id, "name": name}


class FileAlbumCreate(BaseModel):
    album_id: str


@router.get("/{file_id}/albums")
def get_file_albums(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import album_service
    return {"items": album_service.get_file_albums(db, file_id)}


@router.post("/{file_id}/albums")
def add_file_album(file_id: str, payload: FileAlbumCreate, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import album_service
    try:
        album = album_service.assign_album(db, file_id, payload.album_id, added_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Album hinzugefügt.", "file_id": file_id, **album}


@router.delete("/{file_id}/albums/{album_id}")
def remove_file_album(file_id: str, album_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import album_service
    album_service.unassign_album(db, file_id, album_id)
    return {"message": "Album entfernt.", "file_id": file_id, "album_id": album_id}


class FileCategoryAssign(BaseModel):
    category_id: str | None = None


@router.post("/{file_id}/category")
def set_file_category(file_id: str, payload: FileCategoryAssign, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import category_service
    try:
        category_service.assign_category_manually(db, file_id, payload.category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Kategorie zugewiesen.", "file_id": file_id}


@router.delete("/{file_id}/category")
def remove_file_category(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    from app.services import category_service
    category_service.assign_category_manually(db, file_id, None)
    return {"message": "Kategorie entfernt.", "file_id": file_id}


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: str, db: Session = Depends(get_session)):
    """Liefert eine Thumbnail-Vorschau für Bild- und PDF-Dateien (aus Cache oder on-demand)."""
    from fastapi.responses import FileResponse as FastAPIFileResponse, Response
    import io
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    is_image = f.content_type == "images" or (f.mime_type or "").startswith("image/")
    is_pdf = (f.mime_type or "") == "application/pdf" or Path(f.archive_path).suffix.lower() == ".pdf"
    if not is_image and not is_pdf and not f.thumbnail_path:
        raise HTTPException(status_code=400, detail="Keine Vorschau für diesen Dateityp verfügbar")

    cfg = get_config()

    # Gecachtes Thumbnail aus DB-Pfad verwenden
    if f.thumbnail_path:
        thumb_abs = cfg.paths.data_dir / f.thumbnail_path
        if thumb_abs.exists():
            return FastAPIFileResponse(str(thumb_abs), media_type="image/jpeg")

    # Thumbnail on-demand generieren und cachen (Bild und PDF)
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht im Archiv vorhanden")

    try:
        from app.services import thumbnail_service
        rel_path = thumbnail_service.generate_and_store(archive_path, file_id, cfg.paths.data_dir)
        if rel_path:
            repo.update_file_thumbnail(db, file_id, rel_path)
            thumb_abs = cfg.paths.data_dir / rel_path
            return FastAPIFileResponse(str(thumb_abs), media_type="image/jpeg")

        if not is_image:
            raise HTTPException(status_code=404, detail="Vorschau konnte nicht erzeugt werden")

        # Letzter Fallback nur für Bilder: on-demand ohne Speicherung
        from PIL import Image
        img = Image.open(str(archive_path))
        img.thumbnail((400, 400))
        buf = io.BytesIO()
        if img.mode not in ("RGB",):
            img = img.convert("RGB")
        img.save(buf, format="JPEG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Thumbnail-Fehler: {exc}")


def _process_in_background(file_id: str) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    # Semaphore VOR dem Öffnen der DB-Session erwerben, damit nicht mehr Sessions
    # gleichzeitig offen sind als der Connection-Pool erlaubt (siehe ingestion_service).
    with ingestion_service._get_processing_semaphore():
        db = _SessionLocal()
        try:
            ingestion_service.process_file(file_id, db)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Soft-Delete & Duplikat-Gruppen
# ---------------------------------------------------------------------------

@router.post("/{file_id}/delete")
def delete_file(file_id: str, db: Session = Depends(get_session)):
    """Markiert eine Datei (jeden Typs) als geloescht - kein echtes Loeschen, nur Statuswechsel."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    repo.soft_delete_file(db, file_id)
    return {"message": "Datei als gelöscht markiert.", "file_id": file_id}


@router.post("/{file_id}/restore")
def restore_file(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    repo.restore_file(db, file_id)
    return {"message": "Datei wiederhergestellt.", "file_id": file_id}


@router.get("/{file_id}/duplicates")
def get_duplicates(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    group = repo.get_duplicate_group(db, file_id)
    return {
        "file_id": file_id,
        "members": [
            {
                "id": m.id,
                "original_filename": m.original_filename,
                "status": m.status,
                "sharpness_score": m.sharpness_score,
                "is_best": m.best_file_id is None,
                "thumbnail_url": f"/api/files/{m.id}/thumbnail",
            }
            for m in group
        ],
    }


@router.post("/{file_id}/mark-best")
def mark_best(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    group = repo.get_duplicate_group(db, file_id)
    if len(group) < 2:
        raise HTTPException(status_code=400, detail="Datei gehört zu keiner Serie.")
    other_ids = [m.id for m in group if m.id != file_id]
    repo.set_best_file(db, file_id, other_ids, manually_set=True)
    return {"message": "Als beste Aufnahme markiert.", "file_id": file_id}


@router.post("/{file_id}/mark-group-deleted")
def mark_group_deleted(file_id: str, db: Session = Depends(get_session)):
    """Markiert alle ANDEREN Mitglieder der Duplikat-Gruppe (nicht die beste Aufnahme) als geloescht."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    group = repo.get_duplicate_group(db, file_id)
    best = next((m for m in group if m.best_file_id is None), f)
    other_ids = [m.id for m in group if m.id != best.id]
    count = repo.mark_group_deleted_except_best(db, best.id, other_ids)
    return {"message": f"{count} Datei(en) als gelöscht markiert.", "best_file_id": best.id}


@router.post("/duplicates/rebuild")
def rebuild_duplicates(db: Session = Depends(get_session)):
    """Manueller Sofort-Trigger der Duplikat-/Serienerkennung (laeuft sonst periodisch im Scheduler)."""
    from app.services import duplicate_service
    cfg = get_config()
    result = duplicate_service.rebuild_duplicate_groups(
        db,
        hash_threshold=cfg.processing.duplicate_hash_threshold,
        time_window_seconds=cfg.processing.duplicate_time_window_seconds,
    )
    return result


# ---------------------------------------------------------------------------
# Ähnlichkeitssuche-Endpunkte
# ---------------------------------------------------------------------------

class SimilarResult(BaseModel):
    file_id: str
    file_name: str
    source_path: str
    content_type: str
    score: float
    ai_summary: str | None = None
    thumbnail_url: str | None = None


class SimilarResponse(BaseModel):
    results: list[SimilarResult]
    total: int


def _rag_results_to_similar(results: list[dict], db) -> list[SimilarResult]:
    """Konvertiert RAG-Suchergebnisse in SimilarResult-Objekte mit Summary und Thumbnail."""
    output = []
    for r in results:
        meta = r.get("metadata", {})
        fid = meta.get("file_id", r.get("file_id", ""))
        f = repo.get_file_by_id(db, fid) if fid else None
        output.append(SimilarResult(
            file_id=fid,
            file_name=meta.get("file_name", ""),
            source_path=meta.get("source_path", ""),
            content_type=meta.get("content_type", ""),
            score=round(r.get("score", 0.0), 3),
            ai_summary=f.ai_summary if f else None,
            thumbnail_url=f"/api/files/{fid}/thumbnail" if (f and f.content_type == "images") else None,
        ))
    return output


@router.get("/{file_id}/similar", response_model=SimilarResponse)
def get_similar_files(file_id: str, n: int = 10, db: Session = Depends(get_session)):
    """Findet semantisch ähnliche Dateien basierend auf Chunk-Embeddings."""
    from app.services import rag_service
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    results = rag_service.search_similar_by_file(file_id, n_results=n)
    items = _rag_results_to_similar(results, db)
    return SimilarResponse(results=items, total=len(items))


@router.get("/{file_id}/similar-audio", response_model=SimilarResponse)
def get_similar_audio(file_id: str, n: int = 10, db: Session = Depends(get_session)):
    """Findet ähnliche Musik/Audio via CLAP-Embedding."""
    from app.services import rag_service
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if f.content_type != "audio":
        raise HTTPException(status_code=400, detail="Nur für Audiodateien verfügbar")
    results = rag_service.search_similar_audio(file_id, n_results=n)
    items = _rag_results_to_similar(results, db)
    return SimilarResponse(results=items, total=len(items))


@router.get("/{file_id}/similar-persons", response_model=SimilarResponse)
def get_similar_persons(file_id: str, n: int = 20, db: Session = Depends(get_session)):
    """Findet Bilder mit gleichen/ähnlichen Personen via Gesichtserkennungs-Cluster."""
    from app.services import rag_service
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if f.content_type != "images":
        raise HTTPException(status_code=400, detail="Nur für Bilddateien verfügbar")
    results = rag_service.search_similar_persons(file_id, n_results=n)
    items = _rag_results_to_similar(results, db)
    return SimilarResponse(results=items, total=len(items))


@router.get("/{file_id}/similar-location", response_model=SimilarResponse)
def get_similar_location(file_id: str, n: int = 20, db: Session = Depends(get_session)):
    """Findet Bilder am gleichen GPS-Standort."""
    from app.services import rag_service
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if f.content_type != "images":
        raise HTTPException(status_code=400, detail="Nur für Bilddateien verfügbar")
    results = rag_service.search_similar_location(file_id, n_results=n)
    items = _rag_results_to_similar(results, db)
    return SimilarResponse(results=items, total=len(items))


@router.get("/{file_id}/similar-date", response_model=SimilarResponse)
def get_similar_date(file_id: str, n: int = 20, db: Session = Depends(get_session)):
    """Findet Bilder mit gleichem Aufnahmedatum."""
    from app.services import rag_service
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if f.content_type != "images":
        raise HTTPException(status_code=400, detail="Nur für Bilddateien verfügbar")
    results = rag_service.search_similar_date(file_id, n_results=n)
    items = _rag_results_to_similar(results, db)
    return SimilarResponse(results=items, total=len(items))
