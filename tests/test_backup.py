import re
import zipfile
from pathlib import Path

import pytest

from app.services import backup_service


def _make_sources(root: Path) -> tuple[Path, Path, Path, Path]:
    archive = root / "source_documents"
    data = root / "store"
    temp = data / "temp"
    target = root / "backup"
    (archive / "2026" / "09").mkdir(parents=True)
    (archive / "2026" / "09" / "doc.pdf").write_bytes(b"pdf-inhalt")
    data.mkdir(parents=True)
    (data / "jolia.db").write_bytes(b"db-inhalt")
    temp.mkdir(parents=True)
    (temp / "scratch.bin").write_bytes(b"x" * 1024)
    target.mkdir(parents=True)
    return archive, data, temp, target


def test_backup_creates_timestamped_zip(tmp_path: Path):
    archive, data, temp, target = _make_sources(tmp_path)

    result = backup_service.create_backup(archive, data, target, temp_dir=temp)

    assert re.match(r"^jolia_\d{10}_backup\.zip$", result.zip_path.name)
    with zipfile.ZipFile(result.zip_path) as zf:
        names = set(zf.namelist())
    assert "source_documents/2026/09/doc.pdf" in names
    assert "data/jolia.db" in names
    assert "manifest.json" in names
    # temp_dir liegt unter data_dir, darf aber nicht im Backup landen
    assert not any(n.startswith("data/temp/") for n in names)

    entries = backup_service.list_backups(target)
    assert [e.name for e in entries] == [result.zip_path.name]


def test_second_backup_does_not_overwrite(tmp_path: Path):
    archive, data, temp, target = _make_sources(tmp_path)

    first = backup_service.create_backup(archive, data, target, temp_dir=temp)
    second = backup_service.create_backup(archive, data, target, temp_dir=temp)

    assert first.zip_path != second.zip_path
    assert first.zip_path.exists() and second.zip_path.exists()


def test_max_backups_removes_oldest(tmp_path: Path):
    archive, data, temp, target = _make_sources(tmp_path)

    for _ in range(3):
        backup_service.create_backup(archive, data, target, temp_dir=temp, max_backups=2)

    assert len(backup_service.list_backups(target)) == 2


def test_insufficient_space_deletes_old_backups(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    backup_service.create_backup(archive, data, target, temp_dir=temp)
    backup_service.create_backup(archive, data, target, temp_dir=temp)
    assert len(backup_service.list_backups(target)) == 2

    # Erst "voll", nach dem Löschen eines alten Backups wieder genug Platz.
    responses = iter([0])
    monkeypatch.setattr(backup_service, "get_free_bytes", lambda _p: next(responses, 10**12))

    backup_service.create_backup(archive, data, target, temp_dir=temp, keep_min_backups=1)

    # Das älteste wurde geopfert, das neueste blieb geschützt, dazu das neue Backup.
    assert len(backup_service.list_backups(target)) == 2


def test_restore_replaces_current_state(tmp_path: Path):
    archive, data, temp, target = _make_sources(tmp_path)
    result = backup_service.create_backup(archive, data, target, temp_dir=temp)
    progress: list[tuple[str, int]] = []

    (archive / "2026" / "09" / "doc.pdf").unlink()
    (archive / "neu.txt").write_text("nach dem Backup")
    (data / "jolia.db").write_bytes(b"veraendert")

    backup_service.restore_backup(
        result.zip_path,
        archive,
        data,
        progress_callback=lambda phase, percent: progress.append((phase, percent)),
    )

    assert (archive / "2026" / "09" / "doc.pdf").read_bytes() == b"pdf-inhalt"
    assert (data / "jolia.db").read_bytes() == b"db-inhalt"
    assert not (archive / "neu.txt").exists()
    assert [percent for _, percent in progress] == sorted(percent for _, percent in progress)
    assert progress[-1] == ("Wiederherstellung abgeschlossen", 100)


def test_member_target_rejects_path_traversal(tmp_path: Path):
    archive = tmp_path / "archive"
    data = tmp_path / "data"
    with pytest.raises(ValueError):
        backup_service._member_target("source_documents/../../evil.txt", archive, data)
    assert backup_service._member_target("unbekannt/foo.txt", archive, data) is None


def test_resolve_backup_rejects_foreign_names(tmp_path: Path):
    with pytest.raises(ValueError):
        backup_service.resolve_backup(tmp_path, "../../etc/passwd")
