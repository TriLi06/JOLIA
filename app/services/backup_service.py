from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_backup(
    archive_root: Path,
    data_dir: Path,
    backup_target: Path,
) -> tuple[int, int, str]:
    """
    Führt ein inkrementelles Backup durch.
    Gibt (files_copied, bytes_copied, log) zurück.
    """
    backup_target.mkdir(parents=True, exist_ok=True)
    log_lines: list[str] = []

    if platform.system() == "Linux" and shutil.which("rsync"):
        files_copied, bytes_copied = _rsync_backup(archive_root, data_dir, backup_target, log_lines)
    else:
        files_copied, bytes_copied = _python_backup(archive_root, data_dir, backup_target, log_lines)

    return files_copied, bytes_copied, "\n".join(log_lines)


def _rsync_backup(
    archive_root: Path,
    data_dir: Path,
    backup_target: Path,
    log_lines: list[str],
) -> tuple[int, int]:
    src_archive = str(archive_root).rstrip("/") + "/"
    src_data = str(data_dir).rstrip("/") + "/"
    dst_archive = str(backup_target / "source_documents") + "/"
    dst_data = str(backup_target / "data") + "/"

    files_copied = 0
    bytes_copied = 0

    for src, dst in [(src_archive, dst_archive), (src_data, dst_data)]:
        cmd = ["rsync", "-av", "--delete", src, dst]
        log_lines.append(f"rsync {src} → {dst}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        log_lines.append(result.stdout[-2000:] if result.stdout else "")
        if result.returncode != 0:
            raise RuntimeError(f"rsync fehlgeschlagen: {result.stderr[:500]}")
        # Grobe Zählung aus rsync-Ausgabe
        for line in result.stdout.splitlines():
            if line.startswith("Number of created files:"):
                try:
                    files_copied += int(line.split(":")[1].strip().replace(",", ""))
                except ValueError:
                    pass
            if line.startswith("Total transferred file size:"):
                try:
                    bytes_copied += int(
                        line.split(":")[1].strip().split()[0].replace(",", "")
                    )
                except ValueError:
                    pass

    return files_copied, bytes_copied


def _python_backup(
    archive_root: Path,
    data_dir: Path,
    backup_target: Path,
    log_lines: list[str],
) -> tuple[int, int]:
    files_copied = 0
    bytes_copied = 0

    for src_root, dst_name in [
        (archive_root, "source_documents"),
        (data_dir, "data"),
    ]:
        dst_root = backup_target / dst_name
        dst_root.mkdir(parents=True, exist_ok=True)
        log_lines.append(f"Kopiere {src_root} → {dst_root}")

        if not src_root.exists():
            continue

        for src_file in src_root.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src_root)
            dst_file = dst_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if _needs_copy(src_file, dst_file):
                shutil.copy2(str(src_file), str(dst_file))
                files_copied += 1
                bytes_copied += src_file.stat().st_size

    log_lines.append(f"Fertig: {files_copied} Dateien, {bytes_copied // 1024} KB")
    return files_copied, bytes_copied


def _needs_copy(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    src_stat = src.stat()
    dst_stat = dst.stat()
    return src_stat.st_size != dst_stat.st_size or src_stat.st_mtime > dst_stat.st_mtime
