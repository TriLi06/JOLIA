from __future__ import annotations

import logging
import threading
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo
from app.services import backup_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Zustand der Wiederherstellung im Prozessspeicher: die Datenbank wird dabei selbst
# ersetzt, kann den Status also nicht halten. Nach dem Neustart steht er wieder auf
# "idle" - genau das signalisiert dem UI "fertig".
_restore_state: dict = {
    "status": "idle", "backup": None, "message": "", "log": "",
    "progress": 0, "phase": "",
}
_restore_lock = threading.Lock()


class BackupStatus(BaseModel):
    id: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    files_copied: int | None
    bytes_copied: int | None
    error_message: str | None
    backup_path: str | None = None


class RestoreRequest(BaseModel):
    name: str


@router.post("/start")
def start_backup(background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    cfg = get_config()
    record = repo.create_backup_record(db, str(cfg.paths.backup_target))
    background_tasks.add_task(_run_backup_task, record.id)
    return {"message": "Backup gestartet.", "backup_id": record.id}


@router.get("/status", response_model=BackupStatus)
def backup_status(db: Session = Depends(get_session)):
    last = repo.get_last_backup(db)
    if not last:
        return BackupStatus(
            id=None, status="never", started_at=None, finished_at=None,
            files_copied=None, bytes_copied=None, error_message=None
        )
    return BackupStatus(
        id=last.id,
        status=last.status or "unknown",
        started_at=last.started_at,
        finished_at=last.finished_at,
        files_copied=last.files_copied,
        bytes_copied=last.bytes_copied,
        error_message=last.error_message,
        backup_path=last.backup_path,
    )


@router.get("/list")
def list_backups():
    cfg = get_config()
    target: Path = cfg.paths.backup_target
    return {
        "target": str(target),
        "free_bytes": backup_service.get_free_bytes(target),
        "backups": [e.as_dict() for e in backup_service.list_backups(target)],
    }


@router.delete("/{name}")
def delete_backup(name: str):
    cfg = get_config()
    try:
        backup_service.delete_backup(cfg.paths.backup_target, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"message": f"{name} gelöscht."}


@router.post("/restore")
def restore_backup(payload: RestoreRequest, background_tasks: BackgroundTasks):
    cfg = get_config()
    try:
        zip_path = backup_service.resolve_backup(cfg.paths.backup_target, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    with _restore_lock:
        if _restore_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Es läuft bereits eine Wiederherstellung.")
        _restore_state.update(
            {
                "status": "running",
                "backup": payload.name,
                "message": "Wiederherstellung läuft…",
                "log": "",
                "progress": 0,
                "phase": "Vorbereitung",
            }
        )

    background_tasks.add_task(_run_restore_task, zip_path)
    return {
        "message": f"Wiederherstellung von {payload.name} gestartet.",
        "backup": payload.name,
    }


@router.get("/restore/status")
def restore_status():
    return dict(_restore_state)


def _run_backup_task(backup_id: str) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        cfg = get_config()
        result = backup_service.create_backup(
            cfg.paths.archive_root,
            cfg.paths.data_dir,
            cfg.paths.backup_target,
            temp_dir=cfg.paths.temp_dir,
            keep_min_backups=cfg.backup.keep_min_backups,
            max_backups=cfg.backup.max_backups,
            space_safety_factor=cfg.backup.space_safety_factor,
            compress=cfg.backup.compress,
        )
        repo.finish_backup(
            db,
            backup_id,
            success=True,
            files_copied=result.files_copied,
            bytes_copied=result.bytes_written,
            backup_path=str(result.zip_path),
        )
    except Exception as exc:
        logger.exception("Backup fehlgeschlagen")
        repo.finish_backup(db, backup_id, success=False, error_message=str(exc))
    finally:
        db.close()


def _run_restore_task(zip_path: Path) -> None:
    cfg = get_config()

    def update_progress(phase: str, progress: int) -> None:
        _restore_state.update({"phase": phase, "progress": progress})

    try:
        log_lines = backup_service.restore_backup(
            zip_path, cfg.paths.archive_root, cfg.paths.data_dir,
            progress_callback=update_progress,
        )
        _restore_state.update(
            {
                "status": "restarting" if cfg.backup.restart_after_restore else "done",
                "message": "Wiederherstellung abgeschlossen.",
                "log": "\n".join(log_lines),
                "progress": 100,
                "phase": "Wiederherstellung abgeschlossen",
            }
        )
        if cfg.backup.restart_after_restore:
            backup_service.request_restart()
    except Exception as exc:
        logger.exception("Wiederherstellung fehlgeschlagen")
        _restore_state.update({"status": "failed", "message": str(exc), "phase": "Fehler"})
