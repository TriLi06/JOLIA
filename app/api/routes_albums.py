from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_session
from app.db import repositories as repo
from app.services import album_service

router = APIRouter()


class AlbumInfo(BaseModel):
    id: str
    name: str
    description: str | None = None
    count: int


class AlbumCreate(BaseModel):
    name: str
    description: str | None = None


class AlbumBulkFilter(BaseModel):
    """Filterkriterien der Timeline/Liste - werden serverseitig erneut ausgewertet,
    damit die Massenoperation auf ALLE passenden Dateien wirkt (nicht nur die geladene Seite)."""
    content_type: str | None = None
    tags: list[str] | None = None
    albums: list[str] | None = None
    status: str | None = None
    q: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@router.get("")
def list_albums(db: Session = Depends(get_session)):
    return {"items": [AlbumInfo(**a) for a in album_service.list_albums(db)]}


@router.post("")
def create_album(payload: AlbumCreate, db: Session = Depends(get_session)):
    try:
        album = album_service.create_album(db, payload.name, payload.description, created_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return album


@router.delete("/{album_id}")
def delete_album(album_id: str, db: Session = Depends(get_session)):
    album_service.delete_album(db, album_id)
    return {"message": "Album wurde von allen Dateien entfernt und gelöscht."}


@router.put("/{album_id}")
def update_album(album_id: str, payload: AlbumCreate, db: Session = Depends(get_session)):
    try:
        album = album_service.update_album(db, album_id, payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return album


@router.post("/{album_id}/bulk-add")
def bulk_add_to_album(album_id: str, payload: AlbumBulkFilter, db: Session = Depends(get_session)):
    file_ids = repo.list_file_ids_for_filter(
        db, q_text=payload.q, content_type=payload.content_type, tags=payload.tags,
        albums=payload.albums, status=payload.status, date_from=payload.date_from, date_to=payload.date_to,
    )
    try:
        count = album_service.bulk_add_files_to_album(db, album_id, file_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"{count} Datei(en) zum Album hinzugefügt.", "count": count}


@router.post("/{album_id}/bulk-remove")
def bulk_remove_from_album(album_id: str, payload: AlbumBulkFilter, db: Session = Depends(get_session)):
    file_ids = repo.list_file_ids_for_filter(
        db, q_text=payload.q, content_type=payload.content_type, tags=payload.tags,
        albums=payload.albums, status=payload.status, date_from=payload.date_from, date_to=payload.date_to,
    )
    try:
        count = album_service.bulk_remove_files_from_album(db, album_id, file_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": f"{count} Datei(en) aus Album entfernt.", "count": count}
