import json
import subprocess
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import video_compression_service as compression


def _metadata(width=1920, height=1080, video_codec="h264", creation_time=None):
    tags = {"creation_time": creation_time} if creation_time else {}
    return {
        "format": {"tags": tags},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": video_codec,
                "width": width,
                "height": height,
                "tags": tags,
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    }


def test_archive_profile_encodes_and_validates_before_publishing(monkeypatch, tmp_path, caplog):
    source = tmp_path / "capture.mov"
    source.write_bytes(b"source-video")
    output = tmp_path / "capture.mp4"
    source_metadata = _metadata(3840, 2160, creation_time="2024-02-03T04:05:06.000000Z")
    encoded_metadata = _metadata(2560, 1440, video_codec="av1")
    calls = []
    caplog.set_level("WARNING", logger="app.services.video_compression_service")

    monkeypatch.setattr(
        compression,
        "probe_video",
        lambda path, _binary: (
            encoded_metadata if Path(path) != source else source_metadata
        ),
    )

    def fake_run(command, *, step, source_path):
        calls.append((command, step, source_path))
        if step == "FFmpeg-Encoding":
            Path(command[-1]).write_bytes(b"encoded-av1")
            return subprocess.CompletedProcess(
                command, 0, stdout="", stderr="Warning: encoder adjusted parameters"
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(compression, "_run_command", fake_run)

    result = compression.compress_video(source, output)

    command, step, _ = calls[0]
    assert step == "FFmpeg-Encoding"
    assert command[command.index("-vf") + 1] == "scale=-2:1440"
    assert command[command.index("-c:v") + 1] == "libsvtav1"
    assert command[command.index("-crf") + 1] == "38"
    assert command[command.index("-preset") + 1] == "8"
    assert command[command.index("-g") + 1] == "240"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "96k"
    assert command[command.index("-metadata") + 1] == (
        "creation_time=2024-02-03T04:05:06.000000Z"
    )
    assert [step for _cmd, step, _source in calls] == [
        "FFmpeg-Encoding",
        "Ausgabedekodierung",
    ]
    assert result.original_size == len(b"source-video")
    assert result.compressed_size == len(b"encoded-av1")
    assert output.read_bytes() == b"encoded-av1"
    assert source.read_bytes() == b"source-video"
    assert list(tmp_path.glob(".jolia-video-*")) == []
    assert "FFmpeg-Diagnose" in caplog.text
    assert "Warning: encoder adjusted parameters" in caplog.text


def test_ffmpeg_failure_logs_command_output_and_reraises(monkeypatch, tmp_path, caplog):
    source = tmp_path / "capture.mov"
    source.write_bytes(b"source-video")
    error = subprocess.CalledProcessError(
        12,
        ["ffmpeg", "capture.mov"],
        output="encoder stdout details",
        stderr="SVT-AV1 encoder initialization failed",
    )
    monkeypatch.setattr(compression, "probe_video", lambda *_args: _metadata())

    def fail_command(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(compression.subprocess, "run", fail_command)

    with caplog.at_level("ERROR", logger="app.services.video_compression_service"):
        with pytest.raises(subprocess.CalledProcessError):
            compression.compress_video(source, tmp_path / "capture-compressed.mp4")

    assert "Videokomprimierung fehlgeschlagen" in caplog.text
    assert "Schritt=FFmpeg-Encoding" in caplog.text
    assert "Exitcode=12" in caplog.text
    assert "encoder stdout details" in caplog.text
    assert "SVT-AV1 encoder initialization failed" in caplog.text


def test_failed_validation_does_not_publish_output_or_delete_source(monkeypatch, tmp_path):
    source = tmp_path / "capture.mp4"
    source.write_bytes(b"source-video")
    output = tmp_path / "capture-compressed.mp4"

    monkeypatch.setattr(compression, "probe_video", lambda *_args: _metadata(video_codec="h264"))

    def fake_run(command, *, step, **_kwargs):
        if step == "FFmpeg-Encoding":
            Path(command[-1]).write_bytes(b"not-av1")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(compression, "_run_command", fake_run)

    with pytest.raises(RuntimeError, match="erwartet wurde 'av1'"):
        compression.compress_video(source, output)

    assert source.read_bytes() == b"source-video"
    assert not output.exists()
    assert list(tmp_path.glob(".jolia-video-*")) == []


def test_invalid_profile_fails_without_running_encoder(tmp_path):
    source = tmp_path / "capture.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="Unbekanntes Videoprofil"):
        compression.compress_video(source, tmp_path / "output.mp4", profile="INVALID")


def test_existing_output_is_not_overwritten(monkeypatch, tmp_path):
    source = tmp_path / "capture.mov"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"source")
    output.write_bytes(b"existing-output")
    monkeypatch.setattr(compression, "probe_video", lambda *_args: pytest.fail("ffprobe must not run"))

    with pytest.raises(FileExistsError, match="existiert bereits"):
        compression.compress_video(source, output)

    assert source.read_bytes() == b"source"
    assert output.read_bytes() == b"existing-output"


def test_profile_table_matches_documented_values():
    assert compression.PROFILES == {
        "LIGHT": compression.VideoCompressionProfile(32, 6, "128k"),
        "BALANCED": compression.VideoCompressionProfile(35, 7, "128k"),
        "ARCHIVE": compression.VideoCompressionProfile(38, 8, "96k"),
        "EXTREME": compression.VideoCompressionProfile(42, 8, "64k"),
    }


def test_batch_replaces_sources_after_encoding_and_skips_av1(monkeypatch, tmp_path):
    source = tmp_path / "vacation.mov"
    source.write_bytes(b"original-mov")
    already_processed = tmp_path / "already.mp4"
    already_processed.write_bytes(b"existing-av1")
    destination = tmp_path / "vacation.mp4"
    submitted = []

    class FakePool:
        def __init__(self, max_workers):
            submitted.append(("workers", max_workers))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def submit(self, function, task):
            future = Future()
            try:
                future.set_result(function(task))
            except Exception as exc:
                future.set_exception(exc)
            submitted.append(task)
            return future

    monkeypatch.setattr(
        compression,
        "is_already_compressed_video",
        lambda path, _binary: Path(path).name == "already.mp4",
    )
    monkeypatch.setattr(compression, "ProcessPoolExecutor", FakePool)

    def encode(task):
        source_arg, output_arg, _profile, _ffmpeg, _ffprobe = task
        Path(output_arg).write_bytes(b"encoded-av1")
        return compression.VideoCompressionResult(
            Path(source_arg), Path(output_arg), 12, 11, 0.25
        )

    monkeypatch.setattr(compression, "_encode_video_task", encode)
    results = compression.compress_directory(tmp_path, max_workers=1)

    assert len(results) == 1
    assert destination.read_bytes() == b"encoded-av1"
    assert not source.exists()
    assert already_processed.read_bytes() == b"existing-av1"
    assert results[0].output_path == destination
    assert submitted[0] == ("workers", 1)


def test_batch_keeps_mp4_source_when_encoder_fails(monkeypatch, tmp_path):
    source = tmp_path / "vacation.mp4"
    source.write_bytes(b"original-mp4")

    class FakePool:
        def __init__(self, max_workers):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def submit(self, _function, task):
            future = Future()
            Path(task[1]).write_bytes(b"partial-output")
            future.set_exception(RuntimeError("synthetic encoder failure"))
            return future

    monkeypatch.setattr(compression, "is_already_compressed_video", lambda *_args: False)
    monkeypatch.setattr(compression, "ProcessPoolExecutor", FakePool)

    with pytest.raises(RuntimeError, match="1 Video"):
        compression.compress_directory(tmp_path, max_workers=1)

    assert source.read_bytes() == b"original-mp4"
    assert list(tmp_path.glob(".jolia-video-*")) == []


def test_probe_video_parses_ffprobe_json(monkeypatch, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    expected = _metadata()
    monkeypatch.setattr(
        compression,
        "_run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(expected), stderr=""
        ),
    )

    assert compression.probe_video(source) == expected
