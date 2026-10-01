"""
Backup & Wiederherstellung.

Jedes Backup ist genau EINE ZIP-Datei mit Zeitstempel im Namen
(``jolia_JJMMTTHHMM_backup.zip``), die im Backup-Ziel (z.B. NAS-Freigabe) liegt.
Frühere Backups werden dadurch nicht mehr überschrieben, sondern bleiben als
eigenständige, in sich konsistente Stände erhalten.

Aufbau des Archivs:

    source_documents/...   -> Inhalt von paths.archive_root
    data/...               -> Inhalt von paths.data_dir (ohne temp_dir)
    manifest.json          -> Metadaten des Backups

Vor dem Schreiben wird geprüft, wie viel Platz im Backup-Ziel frei ist; reicht er
nicht, werden die ältesten Backups gelöscht (die neuesten ``keep_min_backups``
bleiben geschützt).

``restore_backup()`` setzt Archiv und Datenverzeichnis exakt auf den Stand eines
gewählten Backups zurück – alles, was nicht im Archiv enthalten ist, geht dabei
verloren. Danach muss der Prozess neu starten, da SQLite/ChromaDB offene Handles
auf die ersetzten Dateien halten.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

logger = logging.getLogger(__name__)

ARCHIVE_MEMBER_ROOT = "source_documents"
DATA_MEMBER_ROOT = "data"
MANIFEST_NAME = "manifest.json"

BACKUP_GLOB = "jolia_*_backup.zip"
_NAME_RE = re.compile(r"^jolia_(?P<ts>\d{10})(?:-(?P<seq>\d+))?_backup\.zip$")
_TS_FORMAT = "%y%m%d%H%M"
PART_SUFFIX = ".part"

# Kleiner Puffer zusätzlich zur geschätzten Backup-Größe (Dateisystem-Overhead).
_SPACE_HEADROOM_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class BackupEntry:
    name: str
    path: Path
    size_bytes: int
    created_at: datetime

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat(timespec="seconds"),
        }


@dataclass
class BackupResult:
    zip_path: Path
    files_copied: int
    bytes_written: int
    log_lines: list[str] = field(default_factory=list)

    @property
    def log(self) -> str:
        return "\n".join(self.log_lines)


# ---------------------------------------------------------------------------
# Auflisten / Löschen
# ---------------------------------------------------------------------------

def list_backups(backup_target: Path) -> list[BackupEntry]:
    """Alle Backup-ZIPs im Zielordner, neuestes zuerst."""
    if not backup_target.exists():
        return []
    entries: list[BackupEntry] = []
    for path in backup_target.glob(BACKUP_GLOB):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        created = _created_at_from_name(path.name) or datetime.fromtimestamp(stat.st_mtime)
        entries.append(BackupEntry(path.name, path, stat.st_size, created))
    entries.sort(key=lambda e: (e.created_at, e.name), reverse=True)
    return entries


def resolve_backup(backup_target: Path, name: str) -> Path:
    """Ermittelt den Pfad eines Backups anhand des Dateinamens (ohne Pfad-Ausbruch)."""
    if not _NAME_RE.match(name):
        raise ValueError(f"Ungültiger Backup-Name: {name}")
    path = backup_target / name
    if not path.is_file():
        raise FileNotFoundError(f"Backup nicht gefunden: {name}")
    return path


def delete_backup(backup_target: Path, name: str) -> None:
    resolve_backup(backup_target, name).unlink()


def get_free_bytes(path: Path) -> int | None:
    try:
        return shutil.disk_usage(str(path)).free
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Backup erstellen
# ---------------------------------------------------------------------------

def create_backup(
    archive_root: Path,
    data_dir: Path,
    backup_target: Path,
    *,
    temp_dir: Path | None = None,
    keep_min_backups: int = 1,
    max_backups: int = 0,
    space_safety_factor: float = 1.15,
    compress: bool = True,
) -> BackupResult:
    """Schreibt ein vollständiges Backup als eine ZIP-Datei mit Zeitstempel."""
    backup_target.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    _checkpoint_sqlite(log_lines)
    _remove_stale_parts(backup_target, log_lines)

    excludes = [p for p in (temp_dir, backup_target) if p is not None]
    members, source_bytes = _collect_members(archive_root, data_dir, excludes)
    log_lines.append(f"Quelldaten: {len(members)} Dateien, {_fmt_bytes(source_bytes)}")

    required = int(source_bytes * max(space_safety_factor, 1.0)) + _SPACE_HEADROOM_BYTES
    _ensure_free_space(backup_target, required, keep_min_backups, log_lines)

    zip_path = _next_backup_path(backup_target)
    part_path = zip_path.with_name(zip_path.name + PART_SUFFIX)
    compression = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED

    files_written = 0
    try:
        with zipfile.ZipFile(
            part_path,
            "w",
            compression=compression,
            compresslevel=1 if compress else None,
            allowZip64=True,
        ) as zf:
            for src, arcname in members:
                try:
                    zf.write(str(src), arcname)
                    files_written += 1
                except (OSError, ValueError) as exc:
                    log_lines.append(f"Übersprungen: {src} ({exc})")
            zf.writestr(
                MANIFEST_NAME,
                json.dumps(
                    {
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "archive_root": str(archive_root),
                        "data_dir": str(data_dir),
                        "file_count": files_written,
                        "source_bytes": source_bytes,
                    },
                    indent=2,
                ),
            )
        part_path.replace(zip_path)
    except BaseException:
        part_path.unlink(missing_ok=True)
        raise

    bytes_written = zip_path.stat().st_size
    log_lines.append(f"Backup geschrieben: {zip_path.name} ({_fmt_bytes(bytes_written)})")
    _apply_retention(backup_target, max_backups, log_lines)

    return BackupResult(zip_path, files_written, bytes_written, log_lines)


def _collect_members(
    archive_root: Path,
    data_dir: Path,
    excludes: list[Path],
) -> tuple[list[tuple[Path, str]], int]:
    members: list[tuple[Path, str]] = []
    total = 0
    resolved_excludes = [_resolve(p) for p in excludes]

    for src_root, member_root in ((archive_root, ARCHIVE_MEMBER_ROOT), (data_dir, DATA_MEMBER_ROOT)):
        if not src_root.exists():
            continue
        root_resolved = _resolve(src_root)
        active_excludes = [ex for ex in resolved_excludes if ex != root_resolved]
        for src in sorted(src_root.rglob("*")):
            if src.is_symlink() or not src.is_file():
                continue
            src_resolved = _resolve(src)
            if any(_is_within(src_resolved, ex) for ex in active_excludes):
                continue
            try:
                total += src.stat().st_size
            except OSError:
                continue
            rel = src.relative_to(src_root).as_posix()
            members.append((src, f"{member_root}/{rel}"))
    return members, total


def _ensure_free_space(
    backup_target: Path,
    required_bytes: int,
    keep_min_backups: int,
    log_lines: list[str],
) -> None:
    free = get_free_bytes(backup_target)
    if free is None:
        log_lines.append("Freier Speicher im Backup-Ziel nicht ermittelbar – Prüfung übersprungen.")
        return

    log_lines.append(f"Benötigt ca. {_fmt_bytes(required_bytes)}, frei: {_fmt_bytes(free)}")
    if free >= required_bytes:
        return

    backups = list_backups(backup_target)
    protected = max(keep_min_backups, 0)
    for entry in reversed(backups[protected:]):  # älteste zuerst
        if free >= required_bytes:
            break
        try:
            entry.path.unlink()
        except OSError as exc:
            log_lines.append(f"Konnte altes Backup nicht löschen: {entry.name} ({exc})")
            continue
        log_lines.append(f"Altes Backup gelöscht: {entry.name} (+{_fmt_bytes(entry.size_bytes)})")
        free = max(get_free_bytes(backup_target) or 0, free + entry.size_bytes)

    if free < required_bytes:
        raise RuntimeError(
            f"Nicht genug Platz im Backup-Ziel: benötigt ca. {_fmt_bytes(required_bytes)}, "
            f"frei nur {_fmt_bytes(free)}. Alle löschbaren alten Backups wurden bereits "
            f"entfernt (geschützt sind die {protected} neuesten)."
        )


def _apply_retention(backup_target: Path, max_backups: int, log_lines: list[str]) -> None:
    if max_backups <= 0:
        return
    for entry in list_backups(backup_target)[max_backups:]:
        try:
            entry.path.unlink()
            log_lines.append(f"Aufbewahrungsgrenze: {entry.name} gelöscht")
        except OSError as exc:
            log_lines.append(f"Konnte {entry.name} nicht löschen: {exc}")


def _remove_stale_parts(backup_target: Path, log_lines: list[str]) -> None:
    for part in backup_target.glob(f"*{PART_SUFFIX}"):
        try:
            part.unlink()
            log_lines.append(f"Abgebrochenes Backup entfernt: {part.name}")
        except OSError:
            pass


def _next_backup_path(backup_target: Path) -> Path:
    stamp = datetime.now().strftime(_TS_FORMAT)
    candidate = backup_target / f"jolia_{stamp}_backup.zip"
    seq = 2
    while candidate.exists():
        candidate = backup_target / f"jolia_{stamp}-{seq}_backup.zip"
        seq += 1
    return candidate


def _checkpoint_sqlite(log_lines: list[str]) -> None:
    """Schreibt offene WAL-Transaktionen in die Haupt-DB, damit das Backup konsistent ist."""
    try:
        from app.db.database import get_engine

        engine = get_engine()
        if engine is None:
            return
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as exc:  # pragma: no cover - reiner Best-Effort-Schritt
        log_lines.append(f"Hinweis: WAL-Checkpoint fehlgeschlagen ({exc})")


# ---------------------------------------------------------------------------
# Wiederherstellung
# ---------------------------------------------------------------------------

def restore_backup(
    zip_path: Path,
    archive_root: Path,
    data_dir: Path,
    progress_callback: Callable[[str, int], None] | None = None,
) -> list[str]:
    """
    Setzt Archiv und Datenverzeichnis exakt auf den Stand des Backups.

    Alle aktuellen Inhalte beider Verzeichnisse werden vorher gelöscht. Nach dem
    Aufruf MUSS der Prozess neu gestartet werden.
    """
    log_lines: list[str] = []

    def report_progress(phase: str, percent: int) -> None:
        if progress_callback is not None:
            progress_callback(phase, percent)

    with zipfile.ZipFile(zip_path) as zf:
        report_progress("Backup wird geprüft", 1)
        targets: list[tuple[zipfile.ZipInfo, Path]] = []
        needed_bytes = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = _member_target(info.filename, archive_root, data_dir)
            if target is None:
                continue
            targets.append((info, target))
            needed_bytes += info.file_size

        if not targets:
            raise ValueError(
                f"{zip_path.name} enthält keine Daten unter '{ARCHIVE_MEMBER_ROOT}/' "
                f"oder '{DATA_MEMBER_ROOT}/'."
            )

        _check_restore_space(archive_root, data_dir, needed_bytes, log_lines)
        _release_db_handles(log_lines)

        report_progress("Vorhandene Daten werden entfernt", 5)
        for target_root in (archive_root, data_dir):
            removed = _clear_directory(target_root)
            log_lines.append(f"{target_root}: {removed} Einträge entfernt")

        report_progress("Dateien werden wiederhergestellt", 10)
        extracted = 0
        restored_bytes = 0
        total_work = max(needed_bytes, len(targets), 1)
        for info, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                    restored_bytes += len(chunk)
                    progress = 10 + int(89 * restored_bytes / total_work)
                    report_progress("Dateien werden wiederhergestellt", min(progress, 99))
            extracted += 1
            if info.file_size == 0:
                restored_bytes += 1
                progress = 10 + int(89 * restored_bytes / total_work)
                report_progress("Dateien werden wiederhergestellt", min(progress, 99))

    log_lines.append(
        f"{extracted} Dateien aus {zip_path.name} wiederhergestellt ({_fmt_bytes(needed_bytes)})"
    )
    report_progress("Wiederherstellung abgeschlossen", 100)
    return log_lines


def _member_target(name: str, archive_root: Path, data_dir: Path) -> Path | None:
    """Mappt einen ZIP-Eintrag auf ein Ziel – oder None, wenn er ignoriert wird."""
    parts = PurePosixPath(name).parts
    if len(parts) < 2:
        return None
    if parts[0] == ARCHIVE_MEMBER_ROOT:
        base = archive_root
    elif parts[0] == DATA_MEMBER_ROOT:
        base = data_dir
    else:
        return None
    rel = parts[1:]
    if any(part in ("", ".", "..") or ":" in part or part.startswith("/") for part in rel):
        raise ValueError(f"Unsicherer Pfad im Backup-Archiv: {name}")
    target = base.joinpath(*rel)
    if not _is_within(_resolve(target), _resolve(base)):
        raise ValueError(f"Unsicherer Pfad im Backup-Archiv: {name}")
    return target


def _check_restore_space(
    archive_root: Path,
    data_dir: Path,
    needed_bytes: int,
    log_lines: list[str],
) -> None:
    probe = archive_root if archive_root.exists() else archive_root.parent
    free = get_free_bytes(probe)
    if free is None:
        return
    reclaimed = _dir_size(archive_root) + _dir_size(data_dir)
    available = free + reclaimed
    log_lines.append(
        f"Wiederherstellung benötigt {_fmt_bytes(needed_bytes)}, verfügbar ca. {_fmt_bytes(available)}"
    )
    if available < needed_bytes + _SPACE_HEADROOM_BYTES:
        raise RuntimeError(
            f"Nicht genug freier Speicher für die Wiederherstellung: benötigt "
            f"{_fmt_bytes(needed_bytes)}, verfügbar nur {_fmt_bytes(available)}."
        )


def _release_db_handles(log_lines: list[str]) -> None:
    try:
        from app.db.database import get_engine

        engine = get_engine()
        if engine is not None:
            engine.dispose()
            log_lines.append("Datenbankverbindungen geschlossen")
    except Exception as exc:  # pragma: no cover
        log_lines.append(f"Hinweis: Datenbank konnte nicht sauber geschlossen werden ({exc})")


def _clear_directory(path: Path) -> int:
    """Leert ein Verzeichnis, ohne es selbst zu löschen (es kann ein Mountpoint sein)."""
    path.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in path.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("Konnte %s nicht löschen: %s", child, exc)
    return removed


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def request_restart(delay_seconds: float = 1.5) -> None:
    """Beendet den Prozess, damit Docker/systemd JOLIA mit dem neuen Datenstand neu startet."""
    import threading

    def _exit() -> None:
        logger.warning("Neustart nach Wiederherstellung – Prozess wird beendet.")
        os._exit(0)

    threading.Timer(delay_seconds, _exit).start()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _created_at_from_name(name: str) -> datetime | None:
    match = _NAME_RE.match(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("ts"), _TS_FORMAT)
    except ValueError:
        return None


def _fmt_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
