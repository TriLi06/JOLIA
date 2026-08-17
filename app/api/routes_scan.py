from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import get_config
from app.services import ingestion_service, scan_bundle_service

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heic",
    "image/tiff": ".tif",
}
MAX_SIZE_BYTES = 30 * 1024 * 1024  # 30 MB per file


def _extension_for(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in scan_bundle_service.PAGE_EXTENSIONS:
        return suffix
    return ALLOWED_MIME.get(upload.content_type or "", ".jpg")


def _next_page_index(inbox: Path, bundle_id: str) -> int:
    """Naechste freie Seitennummer eines Bundles (erlaubt Uploads in mehreren Schueben)."""
    highest = 0
    for entry in inbox.glob(f"{bundle_id}_*"):
        parsed = scan_bundle_service.parse_page_name(entry)
        if parsed:
            highest = max(highest, parsed[1])
    return highest + 1


@router.post("/upload")
async def scan_upload(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    bundle_id: str | None = Form(default=None),
    title: str | None = Form(default=None),
    source: str | None = Form(default=None),
    complete: bool = Form(default=True),
):
    """Nimmt Scan-Seiten entgegen und bündelt sie zu einem durchsuchbaren PDF.

    Mehrere Aufrufe mit derselben `bundle_id` und `complete=false` hängen weitere
    Seiten an dasselbe Dokument an; abgeschlossen wird es mit `complete=true` oder
    über `POST /bundles/{bundle_id}/complete`.
    """
    cfg = get_config()
    inbox: Path = cfg.paths.inbox
    inbox.mkdir(parents=True, exist_ok=True)

    if not files:
        raise HTTPException(status_code=400, detail="Keine Dateien übermittelt.")

    bundling = cfg.scan.bundle_enabled
    next_index = 1
    if bundling:
        if bundle_id and not scan_bundle_service.is_valid_bundle_id(bundle_id):
            raise HTTPException(status_code=400, detail="Ungültige bundle_id (UUID erwartet).")
        bundle_id = bundle_id or scan_bundle_service.new_bundle_id()
        next_index = _next_page_index(inbox, bundle_id)

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

        if bundling and bundle_id:
            dest = inbox / scan_bundle_service.page_filename(
                bundle_id, next_index, _extension_for(upload)
            )
            next_index += 1
        else:
            safe_name = Path(upload.filename or f"scan_{uuid.uuid4().hex}.jpg").name
            dest = inbox / safe_name
            if dest.exists():
                dest = inbox / f"{dest.stem}_{uuid.uuid4().hex[:6]}{dest.suffix}"

        dest.write_bytes(data)
        saved.append(dest.name)
        logger.info("Scan gespeichert: %s", dest)

    if not saved:
        raise HTTPException(status_code=400, detail=f"Keine Datei gespeichert. Fehler: {'; '.join(errors)}")

    if not bundling or not bundle_id:
        background_tasks.add_task(_import_saved, saved, inbox, cfg.paths.archive_root)
        return JSONResponse(
            status_code=202,
            content={
                "saved": saved,
                "errors": errors,
                "message": f"{len(saved)} Seite(n) empfangen und zur Verarbeitung eingeplant.",
            },
        )

    scan_bundle_service.write_manifest(
        inbox,
        bundle_id,
        title=title,
        source=source or "api",
        complete=complete,
    )

    if complete:
        background_tasks.add_task(_finalize_and_import, bundle_id)
        message = f"{len(saved)} Seite(n) empfangen – PDF wird erstellt und verarbeitet."
    else:
        message = f"{len(saved)} Seite(n) empfangen – Bundle bleibt für weitere Seiten offen."

    return JSONResponse(
        status_code=202,
        content={
            "bundle_id": bundle_id,
            "saved": saved,
            "errors": errors,
            "complete": complete,
            "message": message,
        },
    )


@router.post("/bundles/{bundle_id}/complete")
def complete_bundle(
    bundle_id: str,
    background_tasks: BackgroundTasks,
    title: str | None = Form(default=None),
):
    """Schließt ein offenes Scan-Bundle ab und startet die PDF-Erzeugung."""
    cfg = get_config()
    if not scan_bundle_service.is_valid_bundle_id(bundle_id):
        raise HTTPException(status_code=400, detail="Ungültige bundle_id (UUID erwartet).")

    bundles = {b.bundle_id: b for b in scan_bundle_service.collect_bundles(cfg.paths.inbox)}
    bundle = bundles.get(bundle_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="Kein offenes Bundle mit dieser ID gefunden.")

    scan_bundle_service.write_manifest(
        cfg.paths.inbox,
        bundle_id,
        title=title or bundle.title,
        source=bundle.source,
        complete=True,
    )
    background_tasks.add_task(_finalize_and_import, bundle_id)

    return JSONResponse(
        status_code=202,
        content={
            "bundle_id": bundle_id,
            "pages": len(bundle.pages),
            "message": f"Bundle mit {len(bundle.pages)} Seite(n) wird zu einem PDF verarbeitet.",
        },
    )


@router.get("/bundles")
def list_bundles():
    """Listet noch offene Scan-Bundles in der Inbox."""
    cfg = get_config()
    bundles = scan_bundle_service.collect_bundles(cfg.paths.inbox)
    return {
        "bundles": [
            {
                "bundle_id": b.bundle_id,
                "pages": len(b.pages),
                "title": b.title,
                "source": b.source,
                "complete": b.is_complete_flagged,
                "ready": scan_bundle_service.is_ready(b, cfg),
            }
            for b in bundles
        ]
    }


def _finalize_and_import(bundle_id: str) -> None:
    """Baut das PDF eines Bundles und schleust es durch Import + Verarbeitung."""
    cfg = get_config()
    try:
        pdf_paths = scan_bundle_service.finalize_ready_bundles(cfg, only_bundle_id=bundle_id)
    except Exception:
        logger.exception("Scan-Bundle %s konnte nicht gebündelt werden.", bundle_id)
        return

    if not pdf_paths:
        logger.warning("Scan-Bundle %s: kein PDF erzeugt (Bundle nicht bereit?).", bundle_id)
        return

    _import_saved([p.name for p in pdf_paths], cfg.paths.inbox, cfg.paths.archive_root)


def _import_saved(saved: list[str], inbox: Path, archive_root: Path) -> None:
    """Importiert und verarbeitet gespeicherte Scans in einer eigenen DB-Session."""
    from app.db.database import _SessionLocal

    if _SessionLocal is None:
        logger.error("Datenbank nicht initialisiert – Scan-Import übersprungen.")
        return

    for fname in saved:
        file_path = inbox / fname
        # Semaphore vor der Session holen, damit nicht mehr Sessions offen sind
        # als der Connection-Pool erlaubt (siehe ingestion_service).
        with ingestion_service._get_processing_semaphore():
            db = _SessionLocal()
            try:
                result = ingestion_service.import_file(file_path, db, archive_root)
                if result.get("status") == "imported":
                    ingestion_service.process_file(result["file_id"], db)
            except Exception as exc:
                logger.error("Fehler beim Import von %s: %s", fname, exc)
            finally:
                db.close()
