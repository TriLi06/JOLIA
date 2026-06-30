from __future__ import annotations

import re
import shutil
import uuid as _uuid_mod
from datetime import datetime, timezone
from pathlib import Path


_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_NAME_LEN = 180


def sanitize_filename(name: str) -> str:
    name = _UNSAFE_CHARS.sub("_", name)
    name = name.strip(". ")
    return name[:_MAX_NAME_LEN] if len(name) > _MAX_NAME_LEN else name


def calculate_archive_path(
    archive_root: Path,
    original_filename: str,
    content_type: str,
    date: datetime | None = None,
    file_id: str | None = None,
) -> Path:
    """Berechnet den Archivpfad.

    Dateiname = UUID (kollisionsfrei, unabhängig vom Originalnamen).
    Struktur:  archive_root / content_type / YYYY / MM / <uuid><ext>

    Der Originalname wird ausschliesslich in der DB gespeichert.
    """
    if date is None:
        date = datetime.now(timezone.utc)
    if file_id is None:
        file_id = str(_uuid_mod.uuid4())

    year = date.strftime("%Y")
    month = date.strftime("%m")
    suffix = Path(original_filename).suffix  # z.B. ".jpg"
    filename = f"{file_id}{suffix}"
    return archive_root / content_type / year / month / filename


def move_to_archive(source: Path, target: Path) -> Path:
    """Verschiebt eine Datei ins Archiv.

    Da der Dateiname eine UUID ist, kann keine Kollision auftreten.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return target
