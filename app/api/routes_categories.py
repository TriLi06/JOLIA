from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo
from app.services import category_service

router = APIRouter()


class CategoryInfo(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    created_by: str
    count: int


class CategoryCreate(BaseModel):
    name: str
    parent_id: str | None = None


class CategoryRename(BaseModel):
    name: str


class CategoryMove(BaseModel):
    parent_id: str | None = None


class FileCategoryAssign(BaseModel):
    category_id: str | None = None


class FileCategoryBatchAssign(FileCategoryAssign):
    file_ids: list[str]


@router.get("")
def list_categories(db: Session = Depends(get_session)):
    return {"items": [CategoryInfo(**c) for c in category_service.list_category_tree(db)]}


@router.post("")
def create_category(payload: CategoryCreate, db: Session = Depends(get_session)):
    try:
        category = category_service.create_category(db, payload.name, payload.parent_id, created_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return category


@router.put("/{category_id}")
def rename_category(category_id: str, payload: CategoryRename, db: Session = Depends(get_session)):
    try:
        category = category_service.rename_category(db, category_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return category


@router.put("/{category_id}/move")
def move_category(category_id: str, payload: CategoryMove, db: Session = Depends(get_session)):
    try:
        category = category_service.move_category(db, category_id, payload.parent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return category


@router.delete("/{category_id}")
def delete_category(
    category_id: str,
    reassign_to_parent: bool = False,
    dissolve_subtree: bool = False,
    db: Session = Depends(get_session),
):
    try:
        if dissolve_subtree:
            category_service.delete_category_subtree(db, category_id)
        else:
            category_service.delete_category(db, category_id, reassign_to_parent=reassign_to_parent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Kategorie gelöscht."}


@router.post("/files/assign")
def assign_files_to_category(payload: FileCategoryBatchAssign, db: Session = Depends(get_session)):
    try:
        category_service.assign_categories_manually(db, payload.file_ids, payload.category_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Dateien kategorisiert.", "file_ids": list(dict.fromkeys(payload.file_ids))}


@router.get("/{category_id}/files")
def list_category_files(
    category_id: str,
    include_subtree: bool = True,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_session),
):
    if not repo.get_category_by_id(db, category_id):
        raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
    from app.api.routes_files import FileResponse

    items, total = category_service.list_files_for_category(
        db, category_id, include_subtree=include_subtree, status=status, limit=limit, offset=offset,
    )
    return {
        "items": [FileResponse.model_validate(f) for f in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/uncategorized/files")
def list_uncategorized_files(db: Session = Depends(get_session)):
    from app.api.routes_files import FileResponse

    files = repo.list_uncategorized_files(db, limit=500)
    return {"items": [FileResponse.model_validate(f) for f in files], "total": len(files)}


@router.post("/recategorize-uncategorized")
def recategorize_uncategorized(background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    """Stoesst die Batch-Nachkategorisierung als ProcessingJob an (Fortschritt/Ergebnis siehe /jobs)."""
    job = repo.create_job(db, file_id=None, job_type="recategorize")
    background_tasks.add_task(_run_recategorize_job_in_background, job.id)
    return {
        "message": "Batch-Nachkategorisierung gestartet - Fortschritt siehe Jobs-Seite.",
        "job_id": job.id,
    }


def _run_recategorize_job_in_background(job_id: str) -> None:
    from app.db.database import _SessionLocal
    if _SessionLocal is None:
        return
    db = _SessionLocal()
    try:
        category_service.run_categorize_all_uncategorized_job(job_id, db)
    finally:
        db.close()
