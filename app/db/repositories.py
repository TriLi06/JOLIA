from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.db.models import (
    Album, AppSetting, Backup, Category, Chunk, FaceEncoding, File, FileAlbumLink, FileTagLink,
    PersonCluster, ProcessingJob, Tag,
)


def _now() -> str:
    return datetime.now().isoformat()


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
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[File], int]:
    q = db.query(File)
    if content_type:
        q = q.filter(File.content_type == content_type)
    if tags:
        tag_file_ids = (
            db.query(FileTagLink.file_id)
            .join(Tag, Tag.id == FileTagLink.tag_id)
            .filter(Tag.name.in_(tags))
            .subquery()
        )
        q = q.filter(File.id.in_(tag_file_ids))
    if albums:
        album_file_ids = (
            db.query(FileAlbumLink.file_id)
            .join(Album, Album.id == FileAlbumLink.album_id)
            .filter(Album.name.in_(albums))
            .subquery()
        )
        q = q.filter(File.id.in_(album_file_ids))
    if status:
        q = q.filter(File.status == status)
    else:
        # Standardmaessig geloeschte Dateien ausblenden, nur bei explizitem Statusfilter anzeigen
        q = q.filter(File.status != "deleted")
    total = q.count()
    items = q.order_by(desc(File.imported_at)).limit(limit).offset(offset).all()
    return items, total


def list_review_files(db: Session, limit: int = 200, offset: int = 0) -> tuple[list[File], int]:
    """Liefert Dateien, die wegen OCR oder KI-Kategorisierung manuell geprueft werden muessen."""
    q = db.query(File).filter(
        File.status != "deleted",
        or_(File.status == "needs_review", File.category_needs_review.is_(True)),
    )
    total = q.count()
    items = q.order_by(desc(File.imported_at)).limit(limit).offset(offset).all()
    return items, total


def _build_search_query(
    db: Session,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    """Baut die gefilterte File-Query (ohne Sortierung/Pagination) fuer Suche, Timeline und Zaehlungen.

    Gibt (query, has_join) zurueck; has_join signalisiert, dass wegen des Chunk-Outerjoins
    beim Materialisieren `.distinct()` noetig ist.
    """
    query = db.query(File)
    has_join = False
    if q_text:
        has_join = True
        like = f"%{q_text}%"
        # Datei-IDs sammeln, deren Gesichts-Cluster-Label (Personenname) zur Query passt
        person_file_ids = (
            db.query(FaceEncoding.file_id)
            .join(PersonCluster, PersonCluster.id == FaceEncoding.cluster_id)
            .filter(func.lower(PersonCluster.label).like(func.lower(like)))
            .subquery()
        )
        # Datei-IDs sammeln, deren Tag-Name zur Query passt (Freitextsuche findet auch Tags)
        tag_match_file_ids = (
            db.query(FileTagLink.file_id)
            .join(Tag, Tag.id == FileTagLink.tag_id)
            .filter(func.lower(Tag.name).like(func.lower(like)))
            .subquery()
        )
        # SQLite: ueber func.lower emulieren statt ilike (Backend-unabhaengig)
        query = query.outerjoin(Chunk, Chunk.file_id == File.id).filter(
            func.lower(File.original_filename).like(func.lower(like))
            | func.lower(func.coalesce(File.ai_summary, "")).like(func.lower(like))
            | func.lower(func.coalesce(File.user_description, "")).like(func.lower(like))
            | func.lower(func.coalesce(Chunk.text, "")).like(func.lower(like))
            | File.id.in_(person_file_ids)
            | File.id.in_(tag_match_file_ids)
        )
    if content_type:
        query = query.filter(File.content_type == content_type)
    if tags:
        tag_file_ids = (
            db.query(FileTagLink.file_id)
            .join(Tag, Tag.id == FileTagLink.tag_id)
            .filter(Tag.name.in_(tags))
            .subquery()
        )
        query = query.filter(File.id.in_(tag_file_ids))
    if albums:
        album_file_ids = (
            db.query(FileAlbumLink.file_id)
            .join(Album, Album.id == FileAlbumLink.album_id)
            .filter(Album.name.in_(albums))
            .subquery()
        )
        query = query.filter(File.id.in_(album_file_ids))
    if status:
        query = query.filter(File.status == status)
    else:
        query = query.filter(File.status != "deleted")
    if date_from:
        query = query.filter(func.coalesce(File.created_at, File.imported_at) >= date_from)
    if date_to:
        query = query.filter(func.coalesce(File.created_at, File.imported_at) <= date_to)
    return query, has_join


def search_files(
    db: Session,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[File], int]:
    """Volltext-/Filter-Suche ueber Dateiname, Zusammenfassung, Beschreibung, Chunk-Text, Tags/Alben und Personennamen."""
    query, has_join = _build_search_query(
        db, q_text=q_text, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    total = query.with_entities(func.count(func.distinct(File.id))).scalar() or 0
    items = query.order_by(desc(func.coalesce(File.created_at, File.imported_at)))
    if has_join:
        items = items.distinct()
    items = items.limit(limit).offset(offset).all()
    return items, total


# Ausdruck fuer den Kalendertag (YYYY-MM-DD) einer Datei (Aufnahme- oder Importdatum)
def _day_expr():
    return func.substr(func.coalesce(File.created_at, File.imported_at), 1, 10)


def count_files_by_day(
    db: Session,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Zaehlt Dateien pro Kalendertag (fuer die Timeline-Uebersicht) - guenstig auch bei sehr vielen Dateien."""
    query, _ = _build_search_query(
        db, q_text=q_text, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    day = _day_expr()
    rows = (
        query.with_entities(day.label("day"), func.count(func.distinct(File.id)))
        .group_by(day)
        .all()
    )
    days = [{"date": (d or "unbekannt"), "count": int(c)} for d, c in rows]
    days.sort(key=lambda x: x["date"], reverse=True)
    return days


def list_files_for_day(
    db: Session,
    day: str,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 1000,
) -> list[File]:
    """Liefert die Dateien eines einzelnen Kalendertags (fuer das lazy-Laden der Timeline)."""
    query, has_join = _build_search_query(
        db, q_text=q_text, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    day_col = _day_expr()
    if day == "unbekannt":
        query = query.filter(day_col.is_(None))
    else:
        query = query.filter(day_col == day)
    items = query.order_by(desc(func.coalesce(File.created_at, File.imported_at)))
    if has_join:
        items = items.distinct()
    return items.limit(limit).all()


def list_files_by_day(
    db: Session,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 2000,
) -> list[File]:
    """Wie search_files, aber ohne Pagination - fuer Timeline-Gruppierung nach Tag im API-Layer."""
    items, _ = search_files(
        db, q_text=q_text, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to, limit=limit, offset=0,
    )
    return items


def list_file_ids_for_filter(
    db: Session,
    q_text: str | None = None,
    content_type: str | None = None,
    tags: list[str] | None = None,
    albums: list[str] | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[str]:
    """Liefert nur die File-IDs, die zum Filter passen (ohne Pagination) - fuer Album-Massenoperationen."""
    query, _ = _build_search_query(
        db, q_text=q_text, content_type=content_type, tags=tags, albums=albums, status=status,
        date_from=date_from, date_to=date_to,
    )
    rows = query.with_entities(File.id).distinct().all()
    return [row[0] for row in rows]


def soft_delete_file(db: Session, file_id: str) -> None:
    f = db.get(File, file_id)
    if f:
        f.status = "deleted"
        db.commit()


def restore_file(db: Session, file_id: str) -> None:
    f = db.get(File, file_id)
    if f:
        f.status = "processed"
        db.commit()


def get_duplicate_group(db: Session, file_id: str) -> list[File]:
    """Liefert alle Dateien derselben Serie (inkl. der besten Aufnahme)."""
    f = db.get(File, file_id)
    if not f:
        return []
    group_root_id = f.best_file_id or f.id
    return (
        db.query(File)
        .filter((File.id == group_root_id) | (File.best_file_id == group_root_id))
        .order_by(desc(File.sharpness_score))
        .all()
    )


def set_best_file(db: Session, best_id: str, other_ids: list[str], manually_set: bool = False) -> None:
    """Setzt best_id als beste Aufnahme der Gruppe, alle anderen zeigen auf sie."""
    best = db.get(File, best_id)
    if best:
        best.best_file_id = None
        best.status = "processed"
        best.best_manually_set = manually_set
    for other_id in other_ids:
        if other_id == best_id:
            continue
        other = db.get(File, other_id)
        if other:
            other.best_file_id = best_id
            other.status = "potential_duplicate"
    db.commit()


def mark_group_deleted_except_best(db: Session, best_id: str, other_ids: list[str]) -> int:
    count = 0
    for other_id in other_ids:
        if other_id == best_id:
            continue
        other = db.get(File, other_id)
        if other:
            other.status = "deleted"
            count += 1
    db.commit()
    return count


def update_file_image_metrics(
    db: Session, file_id: str, sharpness_score: float | None, perceptual_hash: str | None
) -> None:
    f = db.get(File, file_id)
    if f:
        if sharpness_score is not None:
            f.sharpness_score = sharpness_score
        if perceptual_hash is not None:
            f.perceptual_hash = perceptual_hash
        db.commit()


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


def list_file_ids_by_status(db: Session, statuses: list[str]) -> list[str]:
    """IDs aller Dateien, deren Status in *statuses* liegt (z.B. nach einem Absturz)."""
    rows = (
        db.query(File.id)
        .filter(File.status.in_(statuses))
        .order_by(File.imported_at)
        .all()
    )
    return [r[0] for r in rows]


def update_file_summary(db: Session, file_id: str, summary: str) -> None:
    f = db.get(File, file_id)
    if f:
        f.ai_summary = summary[:400]  # Sicherheitsgrenze
        db.commit()


def update_file_created_at(db: Session, file_id: str, created_at: str) -> None:
    """Setzt das inhaltliche Erstellungs-/Belegdatum (Timeline-Sortierung)."""
    f = db.get(File, file_id)
    if f:
        f.created_at = created_at
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


# ---------------------------------------------------------------------------
# Tag repository (freie Schlagworte, z.B. Rechnung, Arzt, Homoeopathie, Louisa)
# ---------------------------------------------------------------------------

def list_tags(db: Session) -> list[tuple[Tag, int]]:
    """Liefert alle Tags mit Nutzungszaehler (Anzahl verknuepfter Dateien), alphabetisch sortiert."""
    rows = (
        db.query(Tag, func.count(FileTagLink.file_id))
        .outerjoin(FileTagLink, FileTagLink.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
        .all()
    )
    return [(tag, count) for tag, count in rows]


def get_tag_by_name(db: Session, name: str) -> Optional[Tag]:
    return db.query(Tag).filter(Tag.name == name).first()


def create_tag(db: Session, name: str, created_by: str = "user") -> Tag:
    tag = Tag(name=name, created_by=created_by)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def delete_tag(db: Session, name: str) -> None:
    """Loescht einen Tag global; die Verknuepfungen zu Dateien fallen per Cascade weg."""
    tag = get_tag_by_name(db, name)
    if tag:
        db.delete(tag)
        db.commit()


def get_tags_for_file(db: Session, file_id: str) -> list[Tag]:
    return (
        db.query(Tag)
        .join(FileTagLink, FileTagLink.tag_id == Tag.id)
        .filter(FileTagLink.file_id == file_id)
        .order_by(Tag.name)
        .all()
    )


def add_file_tag(db: Session, file_id: str, tag_name: str, added_by: str = "user") -> Tag:
    """Verknuepft eine Datei mit einem Tag (legt ihn bei Bedarf global an); idempotent."""
    tag = get_tag_by_name(db, tag_name)
    if not tag:
        tag = create_tag(db, tag_name, created_by=added_by if added_by == "user" else "ai")
    link = (
        db.query(FileTagLink)
        .filter(FileTagLink.file_id == file_id, FileTagLink.tag_id == tag.id)
        .first()
    )
    if not link:
        db.add(FileTagLink(file_id=file_id, tag_id=tag.id, added_by=added_by))
        db.commit()
    return tag


def remove_file_tag(db: Session, file_id: str, tag_name: str) -> None:
    """Entfernt die Verknuepfung eines Tags von einer Datei; der Tag selbst bleibt global bestehen."""
    tag = get_tag_by_name(db, tag_name)
    if not tag:
        return
    db.query(FileTagLink).filter(
        FileTagLink.file_id == file_id, FileTagLink.tag_id == tag.id
    ).delete()
    db.commit()


def get_recent_files(db: Session, limit: int = 10) -> list[File]:
    return db.query(File).order_by(desc(File.imported_at)).limit(limit).all()


# ---------------------------------------------------------------------------
# Album repository (spezielle Tags mit Namen + optionaler Beschreibung)
# ---------------------------------------------------------------------------

def list_albums(db: Session) -> list[tuple[Album, int]]:
    """Liefert alle Alben mit Nutzungszaehler (Anzahl verknuepfter Dateien), alphabetisch sortiert."""
    rows = (
        db.query(Album, func.count(FileAlbumLink.file_id))
        .outerjoin(FileAlbumLink, FileAlbumLink.album_id == Album.id)
        .group_by(Album.id)
        .order_by(Album.name)
        .all()
    )
    return [(album, count) for album, count in rows]


def get_album_by_name(db: Session, name: str) -> Optional[Album]:
    return db.query(Album).filter(Album.name == name).first()


def get_album_by_id(db: Session, album_id: str) -> Optional[Album]:
    return db.get(Album, album_id)


def create_album(db: Session, name: str, description: str | None = None, created_by: str = "user") -> Album:
    album = Album(name=name, description=description, created_by=created_by)
    db.add(album)
    db.commit()
    db.refresh(album)
    return album


def delete_album(db: Session, album_id: str) -> None:
    """Loescht ein Album; die Verknuepfungen zu Dateien fallen per Cascade weg."""
    album = get_album_by_id(db, album_id)
    if album:
        db.delete(album)
        db.commit()


def update_album(db: Session, album_id: str, name: str, description: str | None) -> Optional[Album]:
    album = get_album_by_id(db, album_id)
    if not album:
        return None
    album.name = name
    album.description = description
    db.commit()
    db.refresh(album)
    return album


def get_albums_for_file(db: Session, file_id: str) -> list[Album]:
    return (
        db.query(Album)
        .join(FileAlbumLink, FileAlbumLink.album_id == Album.id)
        .filter(FileAlbumLink.file_id == file_id)
        .order_by(Album.name)
        .all()
    )


def add_file_album(db: Session, file_id: str, album_id: str, added_by: str = "user") -> None:
    """Verknuepft eine Datei mit einem bestehenden Album; idempotent."""
    link = (
        db.query(FileAlbumLink)
        .filter(FileAlbumLink.file_id == file_id, FileAlbumLink.album_id == album_id)
        .first()
    )
    if not link:
        db.add(FileAlbumLink(file_id=file_id, album_id=album_id, added_by=added_by))
        db.commit()


def remove_file_album(db: Session, file_id: str, album_id: str) -> None:
    """Entfernt die Verknuepfung eines Albums von einer Datei; das Album selbst bleibt bestehen."""
    db.query(FileAlbumLink).filter(
        FileAlbumLink.file_id == file_id, FileAlbumLink.album_id == album_id
    ).delete()
    db.commit()


# ---------------------------------------------------------------------------
# Category repository (hierarchischer Baum, genau ein Knoten je Datei)
# ---------------------------------------------------------------------------

def list_categories(db: Session) -> list[Category]:
    """Liefert alle Kategorie-Knoten (flach, Client/Service baut daraus den Baum)."""
    return db.query(Category).order_by(Category.name).all()


def get_category_by_id(db: Session, category_id: str) -> Optional[Category]:
    return db.get(Category, category_id)


def get_child_category_by_name(db: Session, parent_id: str | None, name: str) -> Optional[Category]:
    """Sucht einen Knoten mit gegebenem Namen unter einem Elternknoten (case-insensitive)."""
    q = db.query(Category).filter(func.lower(Category.name) == func.lower(name))
    if parent_id is None:
        q = q.filter(Category.parent_id.is_(None))
    else:
        q = q.filter(Category.parent_id == parent_id)
    return q.first()


def create_category(
    db: Session, name: str, parent_id: str | None = None, created_by: str = "user"
) -> Category:
    category = Category(name=name, parent_id=parent_id, created_by=created_by)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def rename_category(db: Session, category_id: str, name: str) -> Optional[Category]:
    category = get_category_by_id(db, category_id)
    if not category:
        return None
    category.name = name
    db.commit()
    db.refresh(category)
    return category


def get_category_descendant_ids(db: Session, category_id: str) -> set[str]:
    """Sammelt die IDs eines Knotens und aller seiner Nachfahren (fuer Zyklus-Checks/Subtree-Filter)."""
    all_categories = list_categories(db)
    children_by_parent: dict[str | None, list[str]] = {}
    for c in all_categories:
        children_by_parent.setdefault(c.parent_id, []).append(c.id)
    result: set[str] = set()
    stack = [category_id]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children_by_parent.get(current, []))
    return result


def move_category(db: Session, category_id: str, new_parent_id: str | None) -> Category:
    """Verschiebt einen Knoten unter einen neuen Elternknoten; verhindert Zyklen (Verschieben in eigenen Teilbaum)."""
    category = get_category_by_id(db, category_id)
    if not category:
        raise ValueError("Kategorie nicht gefunden.")
    if new_parent_id:
        if new_parent_id == category_id:
            raise ValueError("Eine Kategorie kann nicht ihr eigener Elternknoten sein.")
        if new_parent_id in get_category_descendant_ids(db, category_id):
            raise ValueError("Eine Kategorie kann nicht in ihren eigenen Teilbaum verschoben werden.")
        if not get_category_by_id(db, new_parent_id):
            raise ValueError("Ziel-Kategorie nicht gefunden.")
    category.parent_id = new_parent_id
    db.commit()
    db.refresh(category)
    return category


def delete_category(db: Session, category_id: str) -> None:
    """Loescht einen Kategorie-Knoten; nur zulaessig wenn er keine Kinder/Dateien hat (Service prueft das)."""
    category = get_category_by_id(db, category_id)
    if category:
        db.delete(category)
        db.commit()


def count_files_in_category(db: Session, category_id: str) -> int:
    return db.query(File).filter(File.category_id == category_id).count()


def count_files_by_category(db: Session) -> dict[str, int]:
    """Liefert Datei-Anzahl je Kategorie-ID (nur direkt zugeordnete Dateien, kein Subtree)."""
    rows = (
        db.query(File.category_id, func.count(File.id))
        .filter(File.category_id.isnot(None), File.status != "deleted")
        .group_by(File.category_id)
        .all()
    )
    return {cat_id: int(count) for cat_id, count in rows}


def list_files_for_category(
    db: Session, category_ids: list[str], status: str | None = None, limit: int = 500, offset: int = 0
) -> tuple[list[File], int]:
    """Liefert Dateien fuer eine Menge von Kategorie-IDs (z.B. Knoten + Subtree)."""
    q = db.query(File).filter(File.category_id.in_(category_ids))
    if status:
        q = q.filter(File.status == status)
    else:
        q = q.filter(File.status != "deleted")
    total = q.count()
    items = q.order_by(desc(func.coalesce(File.created_at, File.imported_at))).limit(limit).offset(offset).all()
    return items, total


def list_uncategorized_files(db: Session, limit: int = 1000) -> list[File]:
    """Liefert unkategorisierte, verarbeitete Dateien (fuer die Batch-Nachkategorisierung)."""
    return (
        db.query(File)
        .filter(File.category_id.is_(None), File.status.in_(["processed", "needs_review"]))
        .order_by(File.imported_at)
        .limit(limit)
        .all()
    )


def assign_file_category(
    db: Session, file_id: str, category_id: str | None, assigned_by: str, needs_review: bool = False,
    ai_response: str | None = None, review_reason: str | None = None,
) -> None:
    f = db.get(File, file_id)
    if not f:
        return
    f.category_id = category_id
    f.category_assigned_by = assigned_by if category_id else None
    f.category_needs_review = needs_review
    if ai_response is not None:
        f.category_ai_response = ai_response
    f.category_review_reason = review_reason if needs_review else None
    db.commit()




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
    try:
        job = db.get(ProcessingJob, job_id)
        if job:
            job.status = "done" if success else "failed"
            job.finished_at = _now()
            job.error_message = error_message
            job.log = log
            db.commit()
    except Exception:
        db.rollback()
        raise


def list_jobs(
    db: Session, limit: int = 50, offset: int = 0
) -> tuple[list[ProcessingJob], int]:
    q = db.query(ProcessingJob)
    total = q.count()
    items = q.order_by(desc(ProcessingJob.started_at)).limit(limit).offset(offset).all()
    return items, total


def list_unfinished_jobs(db: Session) -> list[ProcessingJob]:
    """Jobs, die noch nicht abgeschlossen sind (z.B. weil die App abgestuerzt ist)."""
    return (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status.in_(["running", "queued"]))
        .all()
    )


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
    try:
        s = db.get(AppSetting, key)
        if s:
            s.value = value
            s.updated_at = _now()
        else:
            s = AppSetting(key=key, value=value, updated_at=_now())
            db.add(s)
        db.commit()
    except Exception:
        db.rollback()
        raise
