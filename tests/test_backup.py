import json
import re
import zipfile
from pathlib import Path
from subprocess import CompletedProcess

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


def test_first_restic_backup_initializes_full_snapshot(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    snapshots: list[dict] = []
    commands: list[tuple[str, ...]] = []
    snapshot_id = "a" * 64

    def fake_restic(repository: Path, *args: str) -> CompletedProcess:
        commands.append(args)
        if args[0] == "init":
            repository.mkdir(parents=True, exist_ok=True)
            (repository / "config").touch()
            return CompletedProcess(args, 0, "", "")
        if args[0] == "backup":
            snapshots.append({"id": snapshot_id, "time": "2026-10-14T08:00:00Z"})
            return CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "message_type": "summary",
                        "snapshot_id": snapshot_id,
                        "total_files_processed": 2,
                        "total_bytes_processed": 20,
                    }
                ),
                "",
            )
        if args[:2] == ("snapshots", "--json"):
            return CompletedProcess(args, 0, json.dumps(snapshots), "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup_service, "_checkpoint_sqlite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backup_service, "_run_restic", fake_restic)

    result = backup_service.create_restic_backup(
        archive, data, target, temp_dir=temp
    )

    assert result.snapshot_id == snapshot_id
    assert result.files_copied == 2
    assert result.bytes_copied == 20
    assert commands[0] == ("init",)
    assert any(command[0] == "backup" for command in commands)
    assert ("check", "--read-data") in commands
    assert "Vollständiges" in result.log_lines[-1]
    backup_command = next(command for command in commands if command[0] == "backup")
    assert str(temp) in backup_command
    assert str(target) not in backup_command


def test_subsequent_restic_backup_checks_and_extends_previous_snapshot(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    repository = target / backup_service.RESTIC_REPOSITORY_NAME
    repository.mkdir()
    (repository / "config").touch()
    snapshots = [{"id": "a" * 64, "time": "2026-10-13T08:00:00Z"}]
    commands: list[tuple[str, ...]] = []
    new_snapshot_id = "b" * 64

    def fake_restic(repository: Path, *args: str) -> CompletedProcess:
        commands.append(args)
        if args[:2] == ("snapshots", "--json"):
            return CompletedProcess(args, 0, json.dumps(snapshots), "")
        if args[0] == "backup":
            snapshots.append({"id": new_snapshot_id, "time": "2026-10-14T08:00:00Z"})
            return CompletedProcess(
                args,
                0,
                json.dumps(
                    {
                        "message_type": "summary",
                        "snapshot_id": new_snapshot_id,
                        "total_files_processed": 2,
                        "total_bytes_processed": 20,
                    }
                ),
                "",
            )
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup_service, "_checkpoint_sqlite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backup_service, "_run_restic", fake_restic)

    result = backup_service.create_restic_backup(
        archive, data, target, temp_dir=temp
    )

    assert result.snapshot_id == new_snapshot_id
    assert ("check",) in commands
    assert ("check", "--read-data") in commands
    assert "Inkrementelles" in result.log_lines[-1]


def test_restic_backup_stops_if_previous_repository_has_integrity_errors(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    repository = target / backup_service.RESTIC_REPOSITORY_NAME
    repository.mkdir()
    (repository / "config").touch()
    commands: list[tuple[str, ...]] = []

    def fake_restic(repository: Path, *args: str) -> CompletedProcess:
        commands.append(args)
        if args[:2] == ("snapshots", "--json"):
            snapshots = [{"id": "a" * 64, "time": "2026-10-13T08:00:00Z"}]
            return CompletedProcess(args, 0, json.dumps(snapshots), "")
        if args[0] == "check":
            return CompletedProcess(args, 0, '{"message_type":"summary","num_errors":1}', "")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup_service, "_checkpoint_sqlite", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(backup_service, "_run_restic", fake_restic)

    with pytest.raises(RuntimeError, match="Integritätsfehler"):
        backup_service.create_restic_backup(
            archive, data, target, temp_dir=temp
        )

    assert not any(command[0] == "backup" for command in commands)


def test_restic_backup_refuses_nonempty_uninitialized_repository(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    repository = target / backup_service.RESTIC_REPOSITORY_NAME
    repository.mkdir()
    (repository / "unrecognized").write_text("leave untouched")
    monkeypatch.setattr(backup_service, "_checkpoint_sqlite", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="nichts verändert"):
        backup_service.create_restic_backup(archive, data, target, temp_dir=temp)

    assert (repository / "unrecognized").read_text() == "leave untouched"


def test_restic_password_is_set_automatically_for_every_restic_command(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    seen_passwords: list[str] = []

    def fake_run(args: list[str], *, env: dict, **kwargs) -> CompletedProcess:
        seen_passwords.append(env["RESTIC_PASSWORD"])
        return CompletedProcess(args, 0, "[]", "")

    monkeypatch.setattr(backup_service.subprocess, "run", fake_run)
    backup_service._run_restic(target, "snapshots", "--json")

    assert seen_passwords == ["JOLIABACKUP"]


def test_restic_restore_validates_staging_before_replacing_live_data(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    repository = target / backup_service.RESTIC_REPOSITORY_NAME
    repository.mkdir()
    (repository / "config").touch()
    snapshot_id = "c" * 64

    def fake_restic(repository: Path, *args: str) -> CompletedProcess:
        if args[:2] == ("snapshots", "--json"):
            return CompletedProcess(
                args, 0, json.dumps([{"id": snapshot_id, "time": "2026-10-14T08:00:00Z"}]), ""
            )
        if args[0] == "restore":
            staging = Path(args[args.index("--target") + 1])
            restored_archive = staging.joinpath(*archive.parts[1:])
            restored_data = staging.joinpath(*data.parts[1:])
            (restored_archive / "restored").mkdir(parents=True)
            (restored_archive / "restored" / "file.pdf").write_bytes(b"restored")
            restored_data.mkdir(parents=True)
            (restored_data / "jolia.db").write_bytes(b"restored-db")
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup_service, "_run_restic", fake_restic)
    monkeypatch.setattr(backup_service, "_release_db_handles", lambda _lines: None)

    backup_service.restore_restic_snapshot(
        target, snapshot_id, archive, data, temp_dir=temp
    )

    assert (archive / "restored" / "file.pdf").read_bytes() == b"restored"
    assert (data / "jolia.db").read_bytes() == b"restored-db"
    assert not (archive / "2026" / "09" / "doc.pdf").exists()
    assert not (data / "temp" / "scratch.bin").exists()


def test_restic_restore_keeps_live_data_if_snapshot_is_incomplete(tmp_path: Path, monkeypatch):
    archive, data, temp, target = _make_sources(tmp_path)
    repository = target / backup_service.RESTIC_REPOSITORY_NAME
    repository.mkdir()
    (repository / "config").touch()
    snapshot_id = "d" * 64

    def fake_restic(repository: Path, *args: str) -> CompletedProcess:
        if args[:2] == ("snapshots", "--json"):
            return CompletedProcess(
                args, 0, json.dumps([{"id": snapshot_id, "time": "2026-10-14T08:00:00Z"}]), ""
            )
        if args[0] == "restore":
            staging = Path(args[args.index("--target") + 1])
            restored_archive = staging.joinpath(*archive.parts[1:])
            restored_archive.mkdir(parents=True)
        return CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup_service, "_run_restic", fake_restic)

    with pytest.raises(RuntimeError, match="aktuelle Daten wurden nicht verändert"):
        backup_service.restore_restic_snapshot(
            target, snapshot_id, archive, data, temp_dir=temp
        )

    assert (archive / "2026" / "09" / "doc.pdf").read_bytes() == b"pdf-inhalt"
    assert (data / "jolia.db").read_bytes() == b"db-inhalt"
