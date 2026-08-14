from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_session
from app.db import repositories as repo
from app.services import scheduler_service

router = APIRouter()


class JobResponse(BaseModel):
    id: str
    file_id: str | None
    original_filename: str | None = None
    job_type: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    error_message: str | None
    log: str | None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: list[JobResponse]
    total: int


@router.get("", response_model=JobListResponse)
def list_jobs(limit: int = 50, offset: int = 0, db: Session = Depends(get_session)):
    items, total = repo.list_jobs(db, limit=limit, offset=offset)
    result = []
    for j in items:
        resp = JobResponse.model_validate(j)
        resp.original_filename = j.file.original_filename if j.file else None
        result.append(resp)
    return JobListResponse(items=result, total=total)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_session)):
    from app.db.models import ProcessingJob
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return JobResponse.model_validate(job)


@router.get("/schedule/status")
def schedule_status(db: Session = Depends(get_session)):
    """Zeigt fuer jeden periodischen Wartungsjob Intervall, letzte/naechste Ausfuehrung und Status."""
    cfg = get_config()
    return {"tasks": scheduler_service.get_schedule_status(db, cfg)}


@router.post("/schedule/{task_name}/run-now")
def schedule_run_now(task_name: str, background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    if task_name not in scheduler_service.TASK_REGISTRY:
        raise HTTPException(status_code=404, detail="Unbekannter Job")
    cfg = get_config()
    background_tasks.add_task(_run_task_in_background, task_name, cfg)
    return {"message": f"Job '{task_name}' gestartet."}


def _run_task_in_background(task_name: str, cfg) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        scheduler_service.run_task_now(task_name, db, cfg)
    finally:
        db.close()
