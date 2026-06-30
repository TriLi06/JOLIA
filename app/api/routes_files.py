from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse as FastAPIFileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo
from app.services import ingestion_service

router = APIRouter()


class FileResponse(BaseModel):
    id: str
    original_filename: str
    archive_path: str
    mime_type: str | None
    content_type: str | None
    file_size: int | None
    status: str
    imported_at: str
    processed_at: str | None
    error_message: str | None

    model_config = {"from_attributes": True}


class FileListResponse(BaseModel):
    items: list[FileResponse]
    total: int
    limit: int
    offset: int


@router.get("", response_model=FileListResponse)
def list_files(
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    items, total = repo.list_files(db, content_type=content_type, status=status, limit=limit, offset=offset)
    return FileListResponse(
        items=[FileResponse.model_validate(f) for f in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{file_id}/download")
def download_file(file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    archive_path = Path(f.archive_path)
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

    from pathlib import Path
    from app.services import sidecar_service
    archive_path = Path(f.archive_path)

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
    return {"message": "Datei als verarbeitet markiert.", "file_id": file_id}


@router.patch("/{file_id}/user-description")
def update_user_description(
    file_id: str,
    payload: dict,
    db: Session = Depends(get_session),
):
    """Speichert eine manuelle Beschreibung und indexiert sie als durchsuchbaren Chunk."""
    import uuid as _uuid
    from datetime import datetime, timezone
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
                "created_year": datetime.now(timezone.utc).year,
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


@router.get("/{file_id}/thumbnail")
def get_thumbnail(file_id: str, db: Session = Depends(get_session)):
    """Liefert eine Thumbnail-Vorschau für Bilddateien (aus Cache oder on-demand)."""
    from fastapi.responses import FileResponse as FastAPIFileResponse, Response
    import io
    f = repo.get_file_by_id(db, file_id)
    if not f:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")
    if not (f.content_type == "images" or (f.mime_type or "").startswith("image/")):
        raise HTTPException(status_code=400, detail="Keine Bilddatei")

    cfg = get_config()

    # Gecachtes Thumbnail aus DB-Pfad verwenden
    if f.thumbnail_path:
        thumb_abs = cfg.paths.data_dir / f.thumbnail_path
        if thumb_abs.exists():
            return FastAPIFileResponse(str(thumb_abs), media_type="image/jpeg")

    # Thumbnail on-demand generieren und cachen
    archive_path = Path(f.archive_path)
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="Datei nicht im Archiv vorhanden")

    try:
        from app.services import thumbnail_service
        rel_path = thumbnail_service.generate_and_store(archive_path, file_id, cfg.paths.data_dir)
        if rel_path:
            repo.update_file_thumbnail(db, file_id, rel_path)
            thumb_abs = cfg.paths.data_dir / rel_path
            return FastAPIFileResponse(str(thumb_abs), media_type="image/jpeg")

        # Letzter Fallback: on-demand ohne Speicherung
        from PIL import Image
        img = Image.open(str(archive_path))
        img.thumbnail((400, 400))
        buf = io.BytesIO()
        if img.mode not in ("RGB",):
            img = img.convert("RGB")
        img.save(buf, format="JPEG")
        buf.seek(0)
        return Response(content=buf.read(), media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Thumbnail-Fehler: {exc}")


def _process_in_background(file_id: str) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        ingestion_service.process_file(file_id, db)
    finally:
        db.close()


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
