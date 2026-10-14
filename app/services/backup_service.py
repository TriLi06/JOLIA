"""
Backup & Wiederherstellung.

Neue Sicherungen werden als verschlüsseltes Restic-Repository mit vollständigen
und danach inkrementellen Snapshots angelegt. Die Repository-Struktur wird vor
jedem inkrementellen Lauf geprüft; nach jedem Backup werden die Datenblöcke
vollständig gelesen und validiert. Alte ZIP-Backups bleiben weiterhin
wiederherstellbar.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
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
RESTIC_REPOSITORY_NAME = "restic-repository"
RESTIC_PASSWORD = "JOLIABACKUP"
_SNAPSHOT_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")
_RESTIC_LOCK = threading.Lock()

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
            "type": "zip",
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


@dataclass(frozen=True)
class ResticBackupEntry:
    name: str
    created_at: datetime

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": None,
            "size_bytes": None,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "type": "restic",
        }


@dataclass
class ResticBackupResult:
    snapshot_id: str
    files_copied: int
    bytes_copied: int
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


def list_all_backups(backup_target: Path) -> list[dict]:
    """Listet Restic-Snapshots und noch vorhandene ZIP-Backups gemeinsam auf."""
    entries = [entry.as_dict() for entry in list_backups(backup_target)]
    entries.extend(entry.as_dict() for entry in list_restic_backups(backup_target))
    entries.sort(key=lambda entry: (entry["created_at"], entry["name"]), reverse=True)
    return entries


def list_restic_backups(backup_target: Path) -> list[ResticBackupEntry]:
    repository = _restic_repository_path(backup_target)
    if not (repository / "config").is_file():
        if repository.exists() and any(repository.iterdir()):
            raise RuntimeError(
                f"Restic-Repository {repository} enthält Dateien, aber keine gültige "
                "Repository-Konfiguration."
            )
        return []

    snapshots = _restic_snapshots(repository)
    entries = [
        ResticBackupEntry(snapshot["id"], _parse_snapshot_time(snapshot["time"]))
        for snapshot in snapshots
        if snapshot.get("id") and snapshot.get("time")
    ]
    entries.sort(key=lambda entry: (entry.created_at, entry.name), reverse=True)
    return entries


def is_restic_snapshot_id(name: str) -> bool:
    return bool(_SNAPSHOT_ID_RE.fullmatch(name))


def resolve_restic_snapshot(backup_target: Path, name: str) -> str:
    if not is_restic_snapshot_id(name):
        raise ValueError(f"Ungültige Restic-Snapshot-ID: {name}")
    repository = _restic_repository_path(backup_target)
    snapshots = _restic_snapshots(repository)
    if not any(snapshot.get("id") == name for snapshot in snapshots):
        raise FileNotFoundError(f"Restic-Snapshot nicht gefunden: {name}")
    return name


def delete_restic_snapshot(backup_target: Path, name: str) -> None:
    snapshot_id = resolve_restic_snapshot(backup_target, name)
    _run_restic(
        _restic_repository_path(backup_target),
        "forget",
        "--prune",
        snapshot_id,
    )


def create_restic_backup(
    archive_root: Path,
    data_dir: Path,
    backup_target: Path,
    *,
    temp_dir: Path | None = None,
    max_backups: int = 0,
) -> ResticBackupResult:
    """Erzeugt einen vollständigen oder inkrementellen, geprüften Restic-Snapshot."""
    backup_target.mkdir(parents=True, exist_ok=True)
    _validate_backup_sources(archive_root, data_dir, backup_target=backup_target)
    resolved_temp = _resolve(temp_dir) if temp_dir is not None else None
    if resolved_temp == _resolve(data_dir):
        raise ValueError("Temporärer Ordner darf nicht mit der Datenquelle identisch sein.")
    if resolved_temp is not None and _is_within(resolved_temp, _resolve(archive_root)):
        raise ValueError("Temporärer Ordner darf nicht im Archiv liegen.")
    with _RESTIC_LOCK:
        log_lines: list[str] = []
        _checkpoint_sqlite(log_lines, raise_on_error=True)
        repository = _restic_repository_path(backup_target)
        repository_was_initialized = (repository / "config").is_file()
        previous = _prepare_restic_repository(repository, log_lines)

        if repository_was_initialized:
            log_lines.append(f"{len(previous)} vorhandene Snapshots gefunden; Repository wird geprüft.")
            _check_restic_repository(repository)
        if not previous:
            log_lines.append("Keine Snapshots vorhanden; dieser Lauf erstellt das erste vollständige Backup.")

        args = ["backup", "--json", "--host", "jolia", "--tag", "jolia"]
        if resolved_temp is not None and _is_within(resolved_temp, _resolve(data_dir)):
            args.extend(("--exclude", str(temp_dir)))
        for source in (archive_root, data_dir):
            if _is_within(_resolve(backup_target), _resolve(source)):
                args.extend(("--exclude", str(backup_target)))
        args.extend((str(archive_root), str(data_dir)))
        completed = _run_restic(repository, *args)
        summary = _restic_backup_summary(completed.stdout)
        snapshot_id = summary.get("snapshot_id")
        if not isinstance(snapshot_id, str) or not is_restic_snapshot_id(snapshot_id):
            raise RuntimeError("Restic hat keinen gültigen Snapshot für dieses Backup gemeldet.")

        snapshots = _restic_snapshots(repository)
        if not any(snapshot.get("id") == snapshot_id for snapshot in snapshots):
            raise RuntimeError(
                f"Restic meldet den Snapshot {snapshot_id}, dieser ist im Repository aber nicht auffindbar."
            )

        log_lines.append(f"Snapshot {snapshot_id} wurde geschrieben; vollständige Datenprüfung läuft.")
        _check_restic_repository(repository, read_data=True)

        if max_backups > 0:
            _run_restic(
                repository,
                "forget",
                "--keep-last",
                str(max_backups),
                "--tag",
                "jolia",
                "--prune",
            )

        files_copied = int(summary.get("total_files_processed", 0))
        bytes_copied = int(summary.get("total_bytes_processed", 0))
        log_lines.append(
            f"{'Inkrementelles' if previous else 'Vollständiges'} Backup geprüft: "
            f"{files_copied} Dateien, {_fmt_bytes(bytes_copied)} verarbeitet."
        )
        return ResticBackupResult(snapshot_id, files_copied, bytes_copied, log_lines)


def _validate_backup_sources(
    archive_root: Path, data_dir: Path, *, backup_target: Path | None = None
) -> None:
    for source in (archive_root, data_dir):
        if not source.is_absolute():
            raise ValueError(f"Backup-Quelle muss ein absoluter Pfad sein: {source}")
        if not source.is_dir():
            raise FileNotFoundError(f"Backup-Quelle fehlt oder ist kein Ordner: {source}")
    archive_resolved, data_resolved = _resolve(archive_root), _resolve(data_dir)
    if _is_within(archive_resolved, data_resolved) or _is_within(data_resolved, archive_resolved):
        raise ValueError("Archiv- und Datenordner dürfen nicht ineinander liegen.")
    if backup_target is not None:
        target_resolved = _resolve(backup_target)
        if target_resolved in {archive_resolved, data_resolved}:
            raise ValueError("Backup-Ziel darf nicht zugleich ein Backup-Quellordner sein.")


def _restic_repository_path(backup_target: Path) -> Path:
    return backup_target / RESTIC_REPOSITORY_NAME


def _prepare_restic_repository(
    repository: Path, log_lines: list[str]
) -> list[dict]:
    if not repository.exists():
        repository.mkdir(parents=True)
    if not repository.is_dir():
        raise RuntimeError(f"Restic-Repository-Pfad ist kein Ordner: {repository}")

    config_file = repository / "config"
    if not config_file.exists():
        if any(repository.iterdir()):
            raise RuntimeError(
                f"Restic-Repository {repository} enthält Dateien, aber keine gültige "
                "Repository-Konfiguration. Es wurde nichts verändert."
            )
        _run_restic(repository, "init")
        log_lines.append("Verschlüsseltes Restic-Repository initialisiert.")
        return []

    return _restic_snapshots(repository)


def _restic_snapshots(repository: Path) -> list[dict]:
    completed = _run_restic(repository, "snapshots", "--json")
    try:
        snapshots = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Restic lieferte eine ungültige Snapshot-Liste.") from exc
    if not isinstance(snapshots, list):
        raise RuntimeError("Restic lieferte eine unerwartete Snapshot-Liste.")
    return [snapshot for snapshot in snapshots if isinstance(snapshot, dict)]


def _restic_backup_summary(output: str) -> dict:
    summary = None
    for line in output.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("message_type") == "summary":
            summary = entry
    if summary is None:
        raise RuntimeError("Restic beendete das Backup ohne eine Zusammenfassung.")
    return summary


def _check_restic_repository(
    repository: Path, *, read_data: bool = False
) -> None:
    arguments = ("check", "--read-data") if read_data else ("check",)
    completed = _run_restic(repository, *arguments)
    for line in completed.stdout.splitlines():
        try:
            result = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(result, dict) or result.get("message_type") != "summary":
            continue
        if result.get("num_errors", 0) or result.get("broken_packs"):
            raise RuntimeError(f"Restic meldet Integritätsfehler: {result}")


def _parse_snapshot_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise RuntimeError(f"Ungültiger Zeitstempel in Restic-Snapshot: {value}") from exc


def _run_restic(repository: Path, *arguments: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = RESTIC_PASSWORD
    try:
        completed = subprocess.run(
            ["restic", "-r", str(repository), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Restic ist nicht installiert oder im PATH nicht verfügbar.") from exc
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Restic-Befehl fehlgeschlagen: {detail}")
    return completed


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


def _checkpoint_sqlite(log_lines: list[str], *, raise_on_error: bool = False) -> None:
    """Schreibt offene WAL-Transaktionen in die Haupt-DB, damit das Backup konsistent ist."""
    try:
        from app.db.database import get_engine

        engine = get_engine()
        if engine is None:
            return
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            status = result.fetchone()
            if raise_on_error and status and status[0] != 0:
                raise RuntimeError(f"SQLite-WAL-Checkpoint meldet BUSY ({status[0]}).")
    except Exception as exc:  # pragma: no cover - reiner Best-Effort-Schritt
        if raise_on_error:
            raise RuntimeError(f"SQLite-WAL-Checkpoint fehlgeschlagen: {exc}") from exc
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


def restore_restic_snapshot(
    backup_target: Path,
    snapshot_id: str,
    archive_root: Path,
    data_dir: Path,
    *,
    temp_dir: Path | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> list[str]:
    if not _RESTIC_LOCK.acquire(blocking=False):
        raise RuntimeError("Ein Backup oder eine andere Restic-Wiederherstellung läuft bereits.")
    try:
        return _restore_restic_snapshot(
            backup_target,
            snapshot_id,
            archive_root,
            data_dir,
            temp_dir=temp_dir,
            progress_callback=progress_callback,
        )
    finally:
        _RESTIC_LOCK.release()


def _restore_restic_snapshot(
    backup_target: Path,
    snapshot_id: str,
    archive_root: Path,
    data_dir: Path,
    *,
    temp_dir: Path | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> list[str]:
    """Stellt einen geprüften Snapshot erst in einen Staging-Ordner wieder her."""
    _validate_backup_sources(archive_root, data_dir, backup_target=backup_target)
    repository = _restic_repository_path(backup_target)
    resolve_restic_snapshot(backup_target, snapshot_id)

    log_lines: list[str] = []

    def report_progress(phase: str, progress: int) -> None:
        if progress_callback is not None:
            progress_callback(phase, progress)

    report_progress("Backup-Repository wird vollständig geprüft", 1)
    _check_restic_repository(repository, read_data=True)

    staging_parent = temp_dir if temp_dir is not None else data_dir / "temp"
    if staging_parent.is_symlink():
        raise RuntimeError(f"Temporärer Wiederherstellungsordner darf kein Symlink sein: {staging_parent}")
    if _is_within(_resolve(staging_parent), _resolve(archive_root)):
        raise RuntimeError("Temporärer Wiederherstellungsordner darf nicht im Archiv liegen.")
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jolia-restic-restore-", dir=staging_parent))
    try:
        report_progress("Snapshot wird in einen temporären Ordner geladen", 5)
        _run_restic(repository, "restore", snapshot_id, "--target", str(staging))

        restored_archive = staging.joinpath(*archive_root.parts[1:])
        restored_data = staging.joinpath(*data_dir.parts[1:])
        if not restored_archive.is_dir() or not restored_data.is_dir():
            raise RuntimeError(
                "Der Snapshot enthält nicht beide erforderlichen Ordner "
                f"({archive_root} und {data_dir}); aktuelle Daten wurden nicht verändert."
            )

        report_progress("Datenbankverbindungen werden geschlossen", 80)
        _release_db_handles(log_lines)
        report_progress("Vorhandene Daten werden ersetzt", 85)
        _clear_directory_preserving(archive_root, staging)
        _clear_directory_preserving(data_dir, staging)
        _move_directory_contents(restored_archive, archive_root)
        _move_directory_contents(restored_data, data_dir, skip_names={"temp"})

        log_lines.append(f"Restic-Snapshot {snapshot_id} wurde vollständig wiederhergestellt.")
        report_progress("Wiederherstellung abgeschlossen", 100)
        return log_lines
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _clear_directory_preserving(path: Path, preserved: Path) -> int:
    """Leert ein Verzeichnis, lässt aber einen darin liegenden Staging-Pfad bestehen."""
    path.mkdir(parents=True, exist_ok=True)
    preserved_absolute = preserved.absolute()

    def clear(current: Path) -> int:
        removed = 0
        for child in current.iterdir():
            child_absolute = child.absolute()
            if child_absolute == preserved_absolute:
                continue
            if _is_within(preserved_absolute, child_absolute):
                removed += clear(child)
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        return removed

    return clear(path)


def _move_directory_contents(source: Path, destination: Path, *, skip_names: set[str] | None = None) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    skipped = skip_names or set()
    for child in source.iterdir():
        if child.name in skipped:
            continue
        shutil.move(str(child), str(destination / child.name))


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
