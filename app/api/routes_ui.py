from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo
from app.config import get_config
from app.services import archive_service

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    # Dashboard entfällt – die Timeline ist die neue Startseite.
    return RedirectResponse(url="/files", status_code=302)


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
    # Zeilen werden per Virtual-Scrolling im Client geladen; hier nur die Gesamtzahl fuer die Ueberschrift.
    _, total = repo.list_files(db, limit=0, offset=0)
    return templates.TemplateResponse(
        request, "files.html", {"total": total}
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
    cfg = get_config()
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
    if archive_path.exists():
        sidecar_md = sidecar_service.read_md_sidecar(archive_path)
        sidecar_json = sidecar_service.read_json_sidecar(archive_path)

    chunks = repo.get_chunks_for_file(db, file_id)

    from app.services import face_service
    person_names = face_service.get_person_names_for_file(db, file_id)

    return templates.TemplateResponse(
        request,
        "file_detail.html",
        {
            "file": f,
            "sidecar_md": sidecar_md,
            "sidecar_json": sidecar_json,
            "chunks": chunks,
            "person_names": person_names,
        },
    )


@router.get("/files/{file_id}/panel", response_class=HTMLResponse)
def file_detail_panel(request: Request, file_id: str, db: Session = Depends(get_session)):
    """Rendert nur den Detail-Inhalt (ohne Basislayout) fuer die AJAX-Sidebar der Dateien-Ansicht."""
    f = repo.get_file_by_id(db, file_id)
    if not f:
        return HTMLResponse("<p>Datei nicht gefunden</p>", status_code=404)

    sidecar_md = None
    sidecar_json = None
    from app.services import sidecar_service
    cfg = get_config()
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
    if archive_path.exists():
        sidecar_md = sidecar_service.read_md_sidecar(archive_path)
        sidecar_json = sidecar_service.read_json_sidecar(archive_path)

    chunks = repo.get_chunks_for_file(db, file_id)

    from app.services import face_service
    person_names = face_service.get_person_names_for_file(db, file_id)

    return templates.TemplateResponse(
        request,
        "file_detail_panel.html",
        {
            "file": f,
            "sidecar_md": sidecar_md,
            "sidecar_json": sidecar_json,
            "chunks": chunks,
            "person_names": person_names,
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, db: Session = Depends(get_session)):
    # Job-Zeilen werden per Infinite-Scroll im Client nachgeladen; hier nur die Gesamtzahl.
    _, total = repo.list_jobs(db, limit=0, offset=0)
    return templates.TemplateResponse(
        request, "jobs.html", {"total": total}
    )


@router.get("/review", response_class=HTMLResponse)
def review_queue(request: Request, db: Session = Depends(get_session)):
    items, total = repo.list_files(db, status="needs_review", limit=200)
    # OCR-Konfidenz aus Sidecar-JSON lesen
    from app.services import sidecar_service
    files_with_conf = []
    cfg = get_config()
    for f in items:
        conf = None
        try:
            sj = sidecar_service.read_json_sidecar(archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root))
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
    cfg = get_config()
    archive_path = archive_service.resolve_archive_path(f.archive_path, cfg.paths.archive_root)
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
    from app.services import clip_service, clap_service
    cfg = get_config()
    ollama = get_ollama_service()
    ollama_available = ollama.is_available()
    ollama_models = ollama.list_models() if ollama_available else []
    clip_available = clip_service.is_available()
    clap_available = clap_service.is_available()
    try:
        import whisper as _whisper_check  # noqa: F401
        whisper_python_available = True
    except ImportError:
        whisper_python_available = False
    index_meta_str = repo.get_setting(db, "index_meta")

    import json
    index_meta = json.loads(index_meta_str) if index_meta_str else {}

    # Gesichts-Cluster laden (nur wenn Feature aktiv)
    face_clusters = []
    person_groups = []
    if cfg.processing.enable_face_detection:
        try:
            from app.services.face_service import get_all_clusters, get_person_groups
            face_clusters = get_all_clusters(db)
            person_groups = get_person_groups(db)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "cfg": cfg,
            "ollama_available": ollama_available,
            "ollama_models": ollama_models,
            "clip_available": clip_available,
            "clap_available": clap_available,
            "whisper_python_available": whisper_python_available,
            "index_meta": index_meta,
            "face_clusters": face_clusters,
            "person_groups": person_groups,
        },
    )