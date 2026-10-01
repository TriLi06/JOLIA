from types import SimpleNamespace

import pytest

from app.processors.base_processor import BaseProcessor, RetryableProcessingError
from app.services import ingestion_service


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


def test_retryable_processing_error_queues_file(monkeypatch, tmp_path):
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