from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_session)):
    status_counts = repo.count_files_by_status(db)
    recent_files = repo.get_recent_files(db, limit=10)
    last_backup = repo.get_last_backup(db)

    from app.config import get_config
    from app.services import chroma_service
    import json
    cfg = get_config()
    chroma_counts = {}
    for name in chroma_service.COLLECTIONS.values():
        try:
            chroma_counts[name] = chroma_service.get_collection_count(name)
        except Exception:
            chroma_counts[name] = 0

    # Index-Versionswarnung
    model_mismatch_warning = None
    index_meta_str = repo.get_setting(db, "index_meta")
    if index_meta_str:
        index_meta = json.loads(index_meta_str)
        indexed_model = index_meta.get("embedding_model", "")
        if indexed_model and indexed_model != cfg.models.embedding_model:
            model_mismatch_warning = (
                f"Konfiguriertes Modell '{cfg.models.embedding_model}' unterscheidet sich vom "
                f"indizierten Modell '{indexed_model}'. Bitte Reindizierung durchführen."
            )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "status_counts": status_counts,
            "recent_files": recent_files,
            "last_backup": last_backup,
            "chroma_counts": chroma_counts,
            "inbox_path": str(cfg.paths.inbox),
            "model_mismatch_warning": model_mismatch_warning,
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse(request, "search.html")


@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html")


@router.get("/scan", response_class=HTMLResponse)
def scan_page(request: Request):
    return templates.TemplateResponse(request, "scan.html")


@router.get("/files", response_class=HTMLResponse)
def files_page(request: Request, db: Session = Depends(get_session)):
    items, total = repo.list_files(db, limit=100, offset=0)
    return templates.TemplateResponse(
        request, "files.html", {"files": items, "total": total}
    )


@router.get("/files/{file_id}", response_class=HTMLResponse)
def file_detail(request: Request, file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        return HTMLResponse("<h1>Datei nicht gefunden</h1>", status_code=404)

    # Sidecar-Inhalte lesen
    sidecar_md = None
    sidecar_json = None
    from app.services import sidecar_service
    archive_path = Path(f.archive_path)
    if archive_path.exists():
        sidecar_md = sidecar_service.read_md_sidecar(archive_path)
        sidecar_json = sidecar_service.read_json_sidecar(archive_path)

    chunks = repo.get_chunks_for_file(db, file_id)

    return templates.TemplateResponse(
        request,
        "file_detail.html",
        {
            "file": f,
            "sidecar_md": sidecar_md,
            "sidecar_json": sidecar_json,
            "chunks": chunks,
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_session)):
    items, total = repo.list_jobs(db, limit=100)
    return templates.TemplateResponse(
        request, "jobs.html", {"jobs": items, "total": total}
    )


@router.get("/review", response_class=HTMLResponse)
def review_queue(request: Request, db: Session = Depends(get_session)):
    items, total = repo.list_files(db, status="needs_review", limit=200)
    # OCR-Konfidenz aus Sidecar-JSON lesen
    from app.services import sidecar_service
    files_with_conf = []
    for f in items:
        conf = None
        try:
            sj = sidecar_service.read_json_sidecar(Path(f.archive_path))
            if sj:
                conf = sj.get("ocr_confidence") or sj.get("avg_confidence")
        except Exception:
            pass
        f.sidecar_json_confidence = conf  # type: ignore[attr-defined]
        files_with_conf.append(f)
    # Niedrigste Konfidenz zuerst
    files_with_conf.sort(
        key=lambda x: (x.sidecar_json_confidence is None, x.sidecar_json_confidence or 100)
    )
    return templates.TemplateResponse(
        request, "review_queue.html", {"files": files_with_conf, "total": total}
    )


@router.get("/review/{file_id}", response_class=HTMLResponse)
def review_file(request: Request, file_id: str, db: Session = Depends(get_session)):
    f = repo.get_file_by_id(db, file_id)
    if not f:
        return HTMLResponse("<h1>Datei nicht gefunden</h1>", status_code=404)

    from app.services import sidecar_service
    archive_path = Path(f.archive_path)
    sidecar_json = sidecar_service.read_json_sidecar(archive_path) if archive_path.exists() else None
    sidecar_md = sidecar_service.read_md_sidecar(archive_path) if archive_path.exists() else None

    ocr_confidence = None
    current_text = ""
    original_ocr_text = None

    if sidecar_json:
        ocr_confidence = sidecar_json.get("ocr_confidence") or sidecar_json.get("avg_confidence")
        current_text = sidecar_json.get("ocr_text") or sidecar_json.get("text", "")
        original_ocr_text = sidecar_json.get("original_ocr_text")

    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "file": f,
            "sidecar_json": sidecar_json,
            "sidecar_md": sidecar_md,
            "ocr_confidence": ocr_confidence,
            "current_text": current_text,
            "original_ocr_text": original_ocr_text,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_session)):
    from app.config import get_config
    from app.services.ollama_service import get_ollama_service
    cfg = get_config()
    ollama = get_ollama_service()
    ollama_available = ollama.is_available()
    ollama_models = ollama.list_models() if ollama_available else []
    index_meta_str = repo.get_setting(db, "index_meta")

    import json
    index_meta = json.loads(index_meta_str) if index_meta_str else {}

    # Gesichts-Cluster laden (nur wenn Feature aktiv)
    face_clusters = []
    if cfg.processing.enable_face_detection:
        try:
            from app.services.face_service import get_all_clusters
            face_clusters = get_all_clusters(db)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "cfg": cfg,
            "ollama_available": ollama_available,
            "ollama_models": ollama_models,
            "index_meta": index_meta,
            "face_clusters": face_clusters,
        },
    )
