from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo
from app.services import backup_service

router = APIRouter()


class BackupStatus(BaseModel):
    id: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    files_copied: int | None
    bytes_copied: int | None
    error_message: str | None


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
    )


def _run_backup_task(backup_id: str) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        cfg = get_config()
        files_copied, bytes_copied, log = backup_service.run_backup(
            cfg.paths.archive_root,
            cfg.paths.data_dir,
            cfg.paths.backup_target,
        )
        repo.finish_backup(db, backup_id, success=True, files_copied=files_copied, bytes_copied=bytes_copied)
    except Exception as exc:
        repo.finish_backup(db, backup_id, success=False, error_message=str(exc))
    finally:
        db.close()
