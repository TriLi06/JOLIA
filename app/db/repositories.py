from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db.models import AppSetting, Backup, Chunk, File, ProcessingJob


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# File repository
# ---------------------------------------------------------------------------

def create_file(db: Session, **kwargs) -> File:
    f = File(**kwargs)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def get_file_by_id(db: Session, file_id: str) -> Optional[File]:
    return db.get(File, file_id)


def get_file_by_sha256(db: Session, sha256: str) -> Optional[File]:
    return db.query(File).filter(File.sha256 == sha256).first()


def list_files(
    db: Session,
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[File], int]:
    q = db.query(File)
    if content_type:
        q = q.filter(File.content_type == content_type)
    if status:
        q = q.filter(File.status == status)
    total = q.count()
    items = q.order_by(desc(File.imported_at)).limit(limit).offset(offset).all()
    return items, total


def update_file_status(
    db: Session,
    file_id: str,
    status: str,
    error_message: str | None = None,
    processed_at: str | None = None,
    sidecar_json_path: str | None = None,
    sidecar_md_path: str | None = None,
) -> None:
    f = db.get(File, file_id)
    if f:
        f.status = status
        if error_message is not None:
            f.error_message = error_message
        if processed_at is not None:
            f.processed_at = processed_at
        if sidecar_json_path is not None:
            f.sidecar_json_path = sidecar_json_path
        if sidecar_md_path is not None:
            f.sidecar_md_path = sidecar_md_path
        db.commit()


def count_files_by_status(db: Session) -> dict[str, int]:
    rows = db.query(File.status, func.count(File.id)).group_by(File.status).all()
    return {row[0]: row[1] for row in rows}


def update_file_summary(db: Session, file_id: str, summary: str) -> None:
    f = db.get(File, file_id)
    if f:
        f.ai_summary = summary[:400]  # Sicherheitsgrenze
        db.commit()


def update_file_thumbnail(db: Session, file_id: str, thumbnail_path: str) -> None:
    f = db.get(File, file_id)
    if f:
        f.thumbnail_path = thumbnail_path
        db.commit()


def update_user_description(db: Session, file_id: str, description: str | None) -> None:
    f = db.get(File, file_id)
    if f:
        f.user_description = description
        db.commit()


def get_recent_files(db: Session, limit: int = 10) -> list[File]:
    return db.query(File).order_by(desc(File.imported_at)).limit(limit).all()


# ---------------------------------------------------------------------------
# Chunk repository
# ---------------------------------------------------------------------------

def create_chunk(db: Session, **kwargs) -> Chunk:
    c = Chunk(**kwargs)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def bulk_create_chunks(db: Session, chunks: list[dict]) -> list[Chunk]:
    objs = [Chunk(**c) for c in chunks]
    db.add_all(objs)
    db.commit()
    return objs


def get_chunks_for_file(db: Session, file_id: str) -> list[Chunk]:
    return (
        db.query(Chunk)
        .filter(Chunk.file_id == file_id)
        .order_by(Chunk.chunk_index)
        .all()
    )


def delete_chunks_for_file(db: Session, file_id: str) -> None:
    db.query(Chunk).filter(Chunk.file_id == file_id).delete()
    db.commit()


def get_all_chunks(db: Session) -> list[Chunk]:
    return db.query(Chunk).all()


# ---------------------------------------------------------------------------
# ProcessingJob repository
# ---------------------------------------------------------------------------

def create_job(db: Session, file_id: str | None, job_type: str) -> ProcessingJob:
    job = ProcessingJob(file_id=file_id, job_type=job_type, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def start_job(db: Session, job_id: str) -> None:
    job = db.get(ProcessingJob, job_id)
    if job:
        job.status = "running"
        job.started_at = _now()
        db.commit()


def finish_job(
    db: Session,
    job_id: str,
    success: bool,
    error_message: str | None = None,
    log: str | None = None,
) -> None:
    job = db.get(ProcessingJob, job_id)
    if job:
        job.status = "done" if success else "failed"
        job.finished_at = _now()
        job.error_message = error_message
        job.log = log
        db.commit()


def list_jobs(
    db: Session, limit: int = 50, offset: int = 0
) -> tuple[list[ProcessingJob], int]:
    q = db.query(ProcessingJob)
    total = q.count()
    items = q.order_by(desc(ProcessingJob.started_at)).limit(limit).offset(offset).all()
    return items, total


# ---------------------------------------------------------------------------
# Backup repository
# ---------------------------------------------------------------------------

def create_backup_record(db: Session, backup_path: str) -> Backup:
    b = Backup(backup_path=backup_path, status="running", started_at=_now())
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def finish_backup(
    db: Session,
    backup_id: str,
    success: bool,
    files_copied: int = 0,
    bytes_copied: int = 0,
    error_message: str | None = None,
) -> None:
    b = db.get(Backup, backup_id)
    if b:
        b.status = "done" if success else "failed"
        b.finished_at = _now()
        b.files_copied = files_copied
        b.bytes_copied = bytes_copied
        b.error_message = error_message
        db.commit()


def get_last_backup(db: Session) -> Optional[Backup]:
    return db.query(Backup).order_by(desc(Backup.started_at)).first()


# ---------------------------------------------------------------------------
# AppSetting repository
# ---------------------------------------------------------------------------

def get_setting(db: Session, key: str) -> Optional[str]:
    s = db.get(AppSetting, key)
    return s.value if s else None


def set_setting(db: Session, key: str, value: str) -> None:
    s = db.get(AppSetting, key)
    if s:
        s.value = value
        s.updated_at = _now()
    else:
        s = AppSetting(key=key, value=value, updated_at=_now())
        db.add(s)
    db.commit()
