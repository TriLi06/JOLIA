from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo

router = APIRouter()


@router.get("/status")
def reindex_status(db: Session = Depends(get_session)):
    """Gibt aktuellen Indexstatus und Versionsmetadaten zurück."""
    cfg = get_config()
    index_meta_str = repo.get_setting(db, "index_meta")
    index_meta = json.loads(index_meta_str) if index_meta_str else {}

    # Prüfen ob konfiguriertes Modell mit indiziertem Modell übereinstimmt
    configured_model = cfg.models.embedding_model
    indexed_model = index_meta.get("embedding_model", "")
    model_mismatch = bool(indexed_model and indexed_model != configured_model)

    return {
        "index_meta": index_meta,
        "configured_embedding_model": configured_model,
        "model_mismatch": model_mismatch,
        "warning": (
            f"Konfiguriertes Modell '{configured_model}' unterscheidet sich vom "
            f"indizierten Modell '{indexed_model}'. Bitte Reindizierung durchführen."
            if model_mismatch else None
        ),
    }


@router.post("/vectors")
def reindex_vectors(background_tasks: BackgroundTasks):
    """Modus A: Nur ChromaDB-Vektorindex neu aufbauen."""
    background_tasks.add_task(_run_reindex_vectors)
    return {"message": "Reindizierung (Modus A: Vektoren) wurde gestartet."}


@router.post("/full")
def reindex_full(background_tasks: BackgroundTasks, resume: bool = False):
    """Modus B: Vollständiger Rebuild aus Archiv-Filesystem.

    resume=true: Setzt einen unterbrochenen Rebuild fort, statt Files/Chunks
    zu löschen (bereits verarbeitete Dateien bleiben erhalten).
    """
    background_tasks.add_task(_run_reindex_full, resume)
    message = (
        "Fortsetzung des vollständigen Rebuilds wurde gestartet."
        if resume else "Vollständiger Rebuild (Modus B) wurde gestartet."
    )
    return {"message": message}


def _run_reindex_vectors() -> None:
    from app.db.database import _SessionLocal
    from app.services import reindex_service
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        reindex_service.reindex_vectors_only(db)
    finally:
        db.close()


def _run_reindex_full(resume: bool = False) -> None:
    from app.db.database import _SessionLocal
    from app.services import reindex_service
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        cfg = get_config()
        reindex_service.full_rebuild(db, cfg.paths.archive_root, resume=resume)
    finally:
        db.close()
