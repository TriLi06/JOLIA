from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.services import tag_service

router = APIRouter()


class TagInfo(BaseModel):
    name: str
    count: int


class TagCreate(BaseModel):
    name: str


@router.get("")
def list_tags(db: Session = Depends(get_session)):
    return {"items": [TagInfo(**t) for t in tag_service.list_tags(db)]}


@router.post("")
def create_tag(payload: TagCreate, db: Session = Depends(get_session)):
    try:
        name = tag_service.add_tag(db, payload.name, created_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"name": name}


@router.delete("/{name}")
def delete_tag(name: str, db: Session = Depends(get_session)):
    tag_service.delete_tag(db, name)
    return {"message": f"Tag '{name}' wurde von allen Dateien entfernt und gelöscht."}
