from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo

router = APIRouter()


class JobResponse(BaseModel):
    id: str
    file_id: str | None
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
    return JobListResponse(items=[JobResponse.model_validate(j) for j in items], total=total)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_session)):
    from app.db.models import ProcessingJob
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return JobResponse.model_validate(job)
