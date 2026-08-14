"""
Duplikat-/Serienerkennung für Bilder: gruppiert sehr ähnliche, kurz nacheinander
aufgenommene Fotos (perceptual Hash + Aufnahmezeit) und markiert automatisch die
schärfste Aufnahme als "beste Aufnahme" der Serie.

Aktivierung/Feintuning in config.yaml:
    processing:
      duplicate_hash_threshold: 8
      duplicate_time_window_seconds: 120
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db import repositories as repo
from app.db.models import File

logger = logging.getLogger(__name__)


def _parse_time(file: File) -> datetime | None:
    raw = file.created_at or file.imported_at
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Normalisieren auf naive Systemzeit, da Werte gemischt tz-aware/naive vorkommen können
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _hamming_distance(hash_a: str, hash_b: str) -> int:
    import imagehash
    return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)


def rebuild_duplicate_groups(db: Session, hash_threshold: int = 8, time_window_seconds: int = 120) -> dict:
    """Gruppiert ähnliche Bilder (Union-Find) und setzt best_file_id/status je Gruppe."""
    files = (
        db.query(File)
        .filter(File.content_type == "images")
        .filter(File.perceptual_hash.isnot(None))
        .filter(File.status != "deleted")
        .all()
    )
    if len(files) < 2:
        return {"groups": 0, "files": len(files)}

    times = {f.id: _parse_time(f) for f in files}

    # Union-Find zur Gruppenbildung
    parent: dict[str, str] = {f.id: f.id for f in files}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    n = len(files)
    for i in range(n):
        for j in range(i + 1, n):
            fa, fb = files[i], files[j]
            ta, tb = times[fa.id], times[fb.id]
            if ta is None or tb is None:
                continue
            if abs((ta - tb).total_seconds()) > time_window_seconds:
                continue
            try:
                distance = _hamming_distance(fa.perceptual_hash, fb.perceptual_hash)
            except Exception:
                continue
            if distance <= hash_threshold:
                union(fa.id, fb.id)

    groups: dict[str, list[File]] = {}
    for f in files:
        groups.setdefault(find(f.id), []).append(f)

    updated_groups = 0
    for members in groups.values():
        if len(members) < 2:
            continue

        # Manuelle Best-Auswahl respektieren, falls in dieser Gruppe vorhanden
        manual_best = next(
            (f for f in members if f.best_manually_set and (f.best_file_id is None)),
            None,
        )
        if manual_best is None:
            manual_best = next((f for f in members if f.best_manually_set), None)

        if manual_best is not None:
            best = manual_best
        else:
            best = max(members, key=lambda f: (f.sharpness_score or 0.0, f.file_size or 0))

        other_ids = [f.id for f in members if f.id != best.id]
        repo.set_best_file(db, best.id, other_ids, manually_set=bool(manual_best))
        updated_groups += 1

    logger.info("Duplikat-Gruppen aktualisiert: %d Gruppen unter %d Bildern.", updated_groups, len(files))
    return {"groups": updated_groups, "files": len(files)}
