from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_config
from app.services import ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_MIME = {"image/jpeg", "image/jpg", "image/png"}
MAX_SIZE_BYTES = 30 * 1024 * 1024  # 30 MB per file


@router.post("/upload")
async def scan_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Empfängt gescannte Seiten als JPEG-Dateien und legt sie in die Inbox."""
    cfg = get_config()
    inbox: Path = cfg.paths.inbox
    inbox.mkdir(parents=True, exist_ok=True)

    if not files:
        raise HTTPException(status_code=400, detail="Keine Dateien übermittelt.")

    saved: list[str] = []
    errors: list[str] = []

    for upload in files:
        if upload.content_type not in ALLOWED_MIME:
            errors.append(f"{upload.filename}: Ungültiger Dateityp ({upload.content_type})")
            continue

        data = await upload.read()
        if len(data) > MAX_SIZE_BYTES:
            errors.append(f"{upload.filename}: Datei zu groß (max. 30 MB)")
            continue

        # Sicheren Dateinamen ableiten
        safe_name = Path(upload.filename or f"scan_{uuid.uuid4().hex}.jpg").name
        dest = inbox / safe_name
        # Kollision vermeiden
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            dest = inbox / f"{stem}_{uuid.uuid4().hex[:6]}{suffix}"

        dest.write_bytes(data)
        saved.append(dest.name)
        logger.info("Scan gespeichert: %s", dest)

    if not saved:
        raise HTTPException(status_code=400, detail=f"Keine Datei gespeichert. Fehler: {'; '.join(errors)}")

    # Sofortigen Import als Hintergrundaufgabe starten
    background_tasks.add_task(_import_saved, saved, inbox, cfg.paths.archive_root)

    return JSONResponse(
        status_code=202,
        content={
            "saved": saved,
            "errors": errors,
            "message": f"{len(saved)} Seite(n) empfangen und zur Verarbeitung eingeplant.",
        },
    )


def _import_saved(saved: list[str], inbox: Path, archive_root: Path) -> None:
    """Importiert und verarbeitet gespeicherte Scans in einer eigenen DB-Session."""
    from app.db.database import _SessionLocal

    if _SessionLocal is None:
        logger.error("Datenbank nicht initialisiert – Scan-Import übersprungen.")
        return

    db = _SessionLocal()
    try:
        for fname in saved:
            file_path = inbox / fname
            try:
                result = ingestion_service.import_file(file_path, db, archive_root)
                if result.get("status") == "imported":
                    ingestion_service.process_file(result["file_id"], db)
            except Exception as exc:
                logger.error("Fehler beim Import von %s: %s", fname, exc)
    finally:
        db.close()
