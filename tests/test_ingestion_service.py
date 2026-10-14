import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.processors.base_processor import BaseProcessor, RetryableProcessingError
from app.services import ingestion_service, sidecar_service
from app.services.image_compression_service import CompressionResult
from app.services.hashing_service import compute_sha256
from app.services.video_compression_service import VideoCompressionResult


def test_audio_metadata_date_takes_precedence_over_existing_import_date():
    file_record = SimpleNamespace(
        content_type="audio",
        created_at="2026-10-14T00:00:00",
        created_at_user_edited=False,
    )
    result = SimpleNamespace(created_at="1979-10-26T00:00:00")

    assert ingestion_service._select_created_at(file_record, result, None) == (
        "1979-10-26T00:00:00"
    )


def test_user_edited_audio_date_keeps_precedence_over_metadata():
    file_record = SimpleNamespace(
        content_type="audio",
        created_at="1980-01-01",
        created_at_user_edited=True,
    )
    result = SimpleNamespace(created_at="1979-10-26T00:00:00")

    assert ingestion_service._select_created_at(file_record, result, None) == "1980-01-01"


def test_scan_inbox_finds_files_in_subdirectories(monkeypatch, tmp_path):
    inbox = tmp_path / "inbox"
    nested = inbox / "nested"
    nested.mkdir(parents=True)
    top_level_file = inbox / "top.txt"
    nested_file = nested / "photo.jpg"
    metadata_file = nested / "20250524_122538.jpg.supplemental-metadata.json"
    top_level_file.write_bytes(b"text")
    nested_file.write_bytes(b"image")
    metadata_file.write_text('{"title": "photo"}', encoding="utf-8")
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(scan=SimpleNamespace(bundle_enabled=False)),
    )

    files = ingestion_service.scan_inbox(inbox)

    assert set(files) == {top_level_file, nested_file}
    assert not metadata_file.exists()


def test_scan_inbox_deletes_metadata_and_prunes_empty_directories(monkeypatch, tmp_path):
    inbox = tmp_path / "inbox"
    empty_after_metadata = inbox / "album" / "metadata-only"
    empty_after_metadata.mkdir(parents=True)
    metadata_file = empty_after_metadata / "photo.jpg.supplemental-metadata.json"
    metadata_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(scan=SimpleNamespace(bundle_enabled=False)),
    )

    assert ingestion_service.scan_inbox(inbox) == []

    assert not metadata_file.exists()
    assert not (inbox / "album").exists()
    assert inbox.exists()


def test_cleanup_empty_inbox_directories_removes_only_empty_subdirectories(tmp_path):
    inbox = tmp_path / "inbox"
    nested_empty = inbox / "album" / "empty"
    nested_empty.mkdir(parents=True)
    nonempty = inbox / "album" / "keep"
    nonempty.mkdir()
    (nonempty / "photo.jpg").write_bytes(b"image")

    removed = ingestion_service.cleanup_empty_inbox_directories(inbox)

    assert removed == 1
    assert inbox.exists()
    assert (inbox / "album").exists()
    assert not nested_empty.exists()
    assert (nonempty / "photo.jpg").exists()


def test_image_import_compresses_but_keeps_original_sha_for_reindex(monkeypatch, tmp_path):
    source = tmp_path / "photo.jpg"
    original_bytes = b"original-jpeg-data"
    compressed_bytes = b"compressed-avif-data"
    source.write_bytes(original_bytes)
    original_sha256 = compute_sha256(source)
    archive_root = tmp_path / "archive"
    created_records = []
    compression_calls = []

    def compress_image(source_path, output_path):
        compression_calls.append(source_path)
        output_path.write_bytes(compressed_bytes)
        return CompressionResult(
            source_path,
            output_path,
            len(original_bytes),
            len(compressed_bytes),
        )

    monkeypatch.setattr(ingestion_service, "compress_image", compress_image)
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_sha256", lambda *_: None)
    monkeypatch.setattr(
        ingestion_service.repo,
        "create_file",
        lambda _db, **values: (
            created_records.append(values) or SimpleNamespace(id=values["id"])
        ),
    )

    first = ingestion_service.import_file(source, db=None, archive_root=archive_root)
    archived_path = archive_root / first["archive_path"]
    assert first["status"] == "imported"
    assert archived_path.suffix == ".avif"
    assert archived_path.read_bytes() == compressed_bytes
    assert not source.exists()
    assert created_records[0]["sha256"] == original_sha256
    assert created_records[0]["mime_type"] == "image/avif"
    assert created_records[0]["file_size"] == len(compressed_bytes)

    result = ingestion_service.import_file(archived_path, db=None, archive_root=archive_root)
    reindexed_path = archive_root / result["archive_path"]
    assert result["status"] == "imported"
    assert created_records[1]["sha256"] == created_records[0]["sha256"]
    assert created_records[1]["original_filename"] == "photo.jpg"
    assert reindexed_path.suffix == ".avif"
    assert compression_calls == [source]


def test_failed_image_compression_keeps_original_and_cleans_partial_output(
    monkeypatch, tmp_path
):
    source = tmp_path / "photo.jpg"
    original_bytes = b"original-jpeg-data"
    source.write_bytes(original_bytes)
    archive_root = tmp_path / "archive"

    def fail_compression(_source_path, output_path):
        output_path.write_bytes(b"partial-avif")
        raise RuntimeError("synthetic image encoder failure")

    monkeypatch.setattr(ingestion_service, "compress_image", fail_compression)
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_sha256", lambda *_: None)

    with pytest.raises(RuntimeError, match="synthetic image encoder failure"):
        ingestion_service.import_file(source, db=None, archive_root=archive_root)

    assert source.read_bytes() == original_bytes
    assert list(archive_root.rglob("*")) == []


def test_video_import_compresses_to_mp4_and_keeps_original_hash(monkeypatch, tmp_path):
    source = tmp_path / "holiday.mov"
    original_bytes = b"phone-video-original"
    compressed_bytes = b"verified-av1-mp4"
    source.write_bytes(original_bytes)
    original_sha256 = compute_sha256(source)
    archive_root = tmp_path / "archive"
    created_records = []
    compression_calls = []

    def compress_video(
        source_path,
        output_path,
        *,
        profile,
        ffmpeg_binary,
        ffprobe_binary,
    ):
        compression_calls.append(source_path)
        assert profile == "ARCHIVE"
        assert ffmpeg_binary == "ffmpeg-custom"
        assert ffprobe_binary == "ffprobe-custom"
        output_path.write_bytes(compressed_bytes)
        return VideoCompressionResult(
            source_path,
            output_path,
            len(original_bytes),
            len(compressed_bytes),
            2.5,
        )

    monkeypatch.setattr(ingestion_service, "compress_video", compress_video)
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(
            models=SimpleNamespace(ffmpeg_binary="ffmpeg-custom", ffprobe_binary="ffprobe-custom")
        ),
    )
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_sha256", lambda *_: None)
    monkeypatch.setattr(
        ingestion_service.repo,
        "create_file",
        lambda _db, **values: (
            created_records.append(values) or SimpleNamespace(id=values["id"])
        ),
    )

    imported = ingestion_service.import_file(source, db=None, archive_root=archive_root)
    archived_path = archive_root / imported["archive_path"]
    assert imported["status"] == "imported"
    assert archived_path.suffix == ".mp4"
    assert archived_path.read_bytes() == compressed_bytes
    assert not source.exists()
    assert created_records[0]["sha256"] == original_sha256
    assert created_records[0]["mime_type"] == "video/mp4"
    assert created_records[0]["file_size"] == len(compressed_bytes)

    reindexed = ingestion_service.import_file(archived_path, db=None, archive_root=archive_root)
    assert reindexed["status"] == "imported"
    assert created_records[1]["sha256"] == original_sha256
    assert created_records[1]["original_filename"] == "holiday.mov"
    assert created_records[1]["mime_type"] == "video/mp4"
    assert compression_calls == [source]


def test_failed_video_compression_keeps_original_and_cleans_partial_output(
    monkeypatch, tmp_path
):
    source = tmp_path / "holiday.mov"
    original_bytes = b"original-video-data"
    source.write_bytes(original_bytes)
    archive_root = tmp_path / "archive"
    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(
            models=SimpleNamespace(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")
        ),
    )
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_sha256", lambda *_: None)

    def fail_compression(_source_path, output_path, **_kwargs):
        output_path.write_bytes(b"partial-mp4")
        raise RuntimeError("synthetic video encoder failure")

    monkeypatch.setattr(ingestion_service, "compress_video", fail_compression)

    with pytest.raises(RuntimeError, match="synthetic video encoder failure"):
        ingestion_service.import_file(source, db=None, archive_root=archive_root)

    assert source.read_bytes() == original_bytes
    assert list(archive_root.rglob("*")) == []


def test_video_reindex_detects_compressed_archive_without_sidecar(
    monkeypatch, tmp_path
):
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    source = archive_root / "already-compressed.mp4"
    source.write_bytes(b"av1-aac-video")
    created_records = []

    monkeypatch.setattr(
        "app.config.get_config",
        lambda: SimpleNamespace(models=SimpleNamespace(ffprobe_binary="ffprobe")),
    )
    monkeypatch.setattr(
        ingestion_service,
        "is_already_compressed_video",
        lambda path, _binary: Path(path) == source,
    )
    monkeypatch.setattr(
        ingestion_service,
        "compress_video",
        lambda *_args, **_kwargs: pytest.fail(
            "compressed archive must not be encoded again"
        ),
    )
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_sha256", lambda *_: None)
    monkeypatch.setattr(
        ingestion_service.repo,
        "create_file",
        lambda _db, **values: (
            created_records.append(values) or SimpleNamespace(id=values["id"])
        ),
    )

    imported = ingestion_service.import_file(source, db=None, archive_root=archive_root)
    archived_path = archive_root / imported["archive_path"]
    sidecar = sidecar_service.read_json_sidecar(archived_path)

    assert imported["status"] == "imported"
    assert archived_path.suffix == ".mp4"
    assert archived_path.read_bytes() == b"av1-aac-video"
    assert sidecar["video_compression"]["detected"] is True
    assert created_records[0]["mime_type"] == "video/mp4"


def test_vision_connection_error_is_retryable(monkeypatch, tmp_path):
    class UnavailableOllama:
        def __init__(self, **_kwargs):
            pass

        def describe_image(self, *_args, **_kwargs):
            raise OSError("connection refused")

    class ConcreteProcessor(BaseProcessor):
        def process(self, *_args):
            raise NotImplementedError

    monkeypatch.setattr("app.services.ollama_service.OllamaService", UnavailableOllama)

    with pytest.raises(RetryableProcessingError, match="connection refused"):
        ConcreteProcessor()._run_vision_ollama_structured(
            tmp_path / "image.jpg", "vision-model", "http://localhost:11434", 1.0
        )


def test_retryable_processing_error_queues_file_and_logs_durations(monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="app.services.ingestion_service")
    file_path = tmp_path / "image.jpg"
    file_path.touch()
    file_record = SimpleNamespace(
        id="file-id",
        archive_path="image.jpg",
        mime_type="image/jpeg",
        original_filename="image.jpg",
    )
    config = SimpleNamespace(paths=SimpleNamespace(archive_root=tmp_path))
    statuses = []
    finished_jobs = []

    class FailingProcessor:
        def process(self, *_args):
            raise RetryableProcessingError("Vision-Modell nicht erreichbar")

    monkeypatch.setattr("app.config.get_config", lambda: config)
    monkeypatch.setattr(ingestion_service.repo, "get_file_by_id", lambda *_: file_record)
    monkeypatch.setattr(
        ingestion_service.repo,
        "create_job",
        lambda *_args, **_kwargs: SimpleNamespace(id="job-id"),
    )
    monkeypatch.setattr(ingestion_service.repo, "start_job", lambda *_: None)
    monkeypatch.setattr(
        ingestion_service.repo,
        "update_file_status",
        lambda _db, _file_id, status, **_kwargs: statuses.append(status),
    )
    monkeypatch.setattr(
        ingestion_service.repo,
        "finish_job",
        lambda _db, _job_id, success, **kwargs: finished_jobs.append((success, kwargs)),
    )
    monkeypatch.setattr(
        ingestion_service,
        "resolve_archive_path",
        lambda *_: file_path,
    )
    monkeypatch.setattr(
        ingestion_service,
        "_get_processor_registry",
        lambda: {"image/jpeg": FailingProcessor(), "__default__": FailingProcessor()},
    )

    ingestion_service.process_file("file-id", db=None)

    assert statuses == ["processing", "queued"]
    assert finished_jobs[0][0] is False
    assert finished_jobs[0][1]["error_message"] == "Vision-Modell nicht erreichbar"
    assert "Schritt=Datei-Extraktion" in caplog.text
    assert "Schritt=Gesamtverarbeitung" in caplog.text