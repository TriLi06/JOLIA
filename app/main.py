from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import load_config
from app.db.database import init_db
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config_path = Path("config.yaml")
    cfg = load_config(config_path)

    log_level = "DEBUG" if cfg.app.debug else "INFO"
    setup_logging(log_level, log_file=cfg.paths.data_dir / "docstoreai.log")

    logger.info("DocStoreAI startet…")
    logger.info("Inbox:    %s", cfg.paths.inbox)
    logger.info("Archiv:   %s", cfg.paths.archive_root)

    # Verzeichnisse anlegen
    for p in (
        cfg.paths.archive_root,
        cfg.paths.data_dir,
        cfg.paths.temp_dir,
        cfg.paths.inbox,
    ):
        p.mkdir(parents=True, exist_ok=True)

    # Datenbank initialisieren
    db_path = cfg.paths.data_dir / "archive.db"
    init_db(db_path)
    logger.info("Datenbank bereit: %s", db_path)

    # Embedding-Modell vorwärmen (lazy, beim ersten Aufruf)
    # ChromaDB initialisieren
    from app.services.chroma_service import init_chroma
    init_chroma(cfg.paths.data_dir / "chroma")

    # Optional: Watchdog starten
    if cfg.watcher.enabled:
        from app.services.watcher_service import start_watcher
        start_watcher(cfg)

    logger.info("DocStoreAI läuft auf %s:%d", cfg.app.host, cfg.app.port)
    yield

    # Shutdown
    if cfg.watcher.enabled:
        from app.services.watcher_service import stop_watcher
        stop_watcher()
    logger.info("DocStoreAI wird beendet.")


# ---------------------------------------------------------------------------
# App-Instanz
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title="DocStoreAI",
        description="Lokale KI-gestützte Dokumentenverwaltung",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Session-Middleware (benötigt für Auth)
    from starlette.middleware.sessions import SessionMiddleware
    # Konfiguration vorab laden um Session-Secret zu lesen
    try:
        from app.config import get_config, load_config
        try:
            _cfg = get_config()
        except Exception:
            _cfg = load_config()
        _session_secret = _cfg.app.auth_session_secret
    except Exception:
        _session_secret = "docstoreai-default-session-secret"
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret,
        session_cookie="docstoreai_session",
        https_only=False,  # lokale LAN-Nutzung ohne HTTPS
        max_age=86400 * 7,  # 7 Tage
    )

    # Auth-Middleware: schützt alle Routen außer /auth/* und /static/*
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        from app.api.auth import is_authenticated
        path = request.url.path
        # Öffentliche Pfade immer erlauben
        if (
            path.startswith("/auth")
            or path.startswith("/static")
            or path == "/health"
            or path == "/"
        ):
            return await call_next(request)
        # Prüfen ob eingeloggt
        if not is_authenticated(request):
            from urllib.parse import quote
            return RedirectResponse(
                url=f"/auth/login?next={quote(path)}",
                status_code=302,
            )
        return await call_next(request)

    # Statische Dateien
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # API-Routes registrieren
    from app.api.routes_files import router as files_router
    from app.api.routes_search import router as search_router
    from app.api.routes_chat import router as chat_router
    from app.api.routes_jobs import router as jobs_router
    from app.api.routes_backup import router as backup_router
    from app.api.routes_reindex import router as reindex_router
    from app.api.routes_ui import router as ui_router
    from app.api.auth import router as auth_router
    from app.api.routes_scan import router as scan_router

    app.include_router(auth_router, tags=["auth"])
    app.include_router(files_router, prefix="/api/files", tags=["files"])
    app.include_router(search_router, prefix="/api/search", tags=["search"])
    app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
    app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
    app.include_router(backup_router, prefix="/api/backup", tags=["backup"])
    app.include_router(reindex_router, prefix="/api/reindex", tags=["reindex"])
    app.include_router(scan_router, prefix="/api/scan", tags=["scan"])
    app.include_router(ui_router, tags=["ui"])

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "ok", "app": "DocStoreAI"}

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/dashboard")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.app.host,
        port=cfg.app.port,
        reload=cfg.app.debug,
    )
