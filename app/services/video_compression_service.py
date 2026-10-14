from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".mts", ".m2ts"}


@dataclass(frozen=True)
class VideoCompressionProfile:
    crf: int
    preset: int
    audio_bitrate: str


PROFILES = {
    "LIGHT": VideoCompressionProfile(crf=32, preset=6, audio_bitrate="128k"),
    "BALANCED": VideoCompressionProfile(crf=35, preset=7, audio_bitrate="128k"),
    "ARCHIVE": VideoCompressionProfile(crf=38, preset=8, audio_bitrate="96k"),
    "EXTREME": VideoCompressionProfile(crf=42, preset=8, audio_bitrate="64k"),
}


@dataclass(frozen=True)
class VideoCompressionResult:
    source_path: Path
    output_path: Path
    original_size: int
    compressed_size: int
    processing_time: float
    skipped: bool = False

    @property
    def saved_percentage(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.original_size - self.compressed_size) * 100 / self.original_size


def _run_command(command: list[str], *, step: str, source_path: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Videokomprimierung fehlgeschlagen | Datei=%s | Schritt=%s | Exitcode=%s "
            "| stdout=%s | stderr=%s",
            source_path,
            step,
            exc.returncode,
            (exc.stdout or "").strip() or "(leer)",
            (exc.stderr or "").strip() or "(leer)",
            exc_info=True,
        )
        raise
    except OSError:
        logger.exception(
            "Videokomprimierung fehlgeschlagen | Datei=%s | Schritt=%s | Kommando=%s",
            source_path,
            step,
            command[0],
        )
        raise


def probe_video(
    file_path: Path,
    ffprobe_binary: str = "ffprobe",
) -> dict:
    """Return ffprobe's JSON metadata for a video file."""
    file_path = Path(file_path)
    completed = _run_command(
        [
            ffprobe_binary,
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(file_path),
        ],
        step="ffprobe",
        source_path=file_path,
    )
    try:
        metadata = json.loads(completed.stdout)
    except json.JSONDecodeError:
        logger.exception("ffprobe lieferte ungültiges JSON | Datei=%s", file_path)
        raise

    streams = metadata.get("streams", [])
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError(f"Kein Videostream in Datei gefunden: {file_path}")
    return metadata


def _creation_time(metadata: dict) -> str | None:
    format_tags = metadata.get("format", {}).get("tags", {})
    stream_tags = next(
        (
            stream.get("tags", {})
            for stream in metadata.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        {},
    )
    for tags in (format_tags, stream_tags):
        for key, value in tags.items():
            if key.lower() == "creation_time" and value:
                return str(value)
    return None


def _video_stream(metadata: dict) -> dict:
    return next(
        stream
        for stream in metadata.get("streams", [])
        if stream.get("codec_type") == "video"
    )


def _validate_encoded_video(
    encoded_path: Path,
    source_metadata: dict,
    ffmpeg_binary: str,
    ffprobe_binary: str,
    source_path: Path,
) -> dict:
    if not encoded_path.is_file() or encoded_path.stat().st_size == 0:
        raise RuntimeError(f"FFmpeg hat keine gültige Ausgabedatei erstellt: {encoded_path}")

    encoded_metadata = probe_video(encoded_path, ffprobe_binary)
    encoded_video = _video_stream(encoded_metadata)
    if encoded_video.get("codec_name") != "av1":
        raise RuntimeError(
            f"Ausgabeprüfung fehlgeschlagen: Video-Codec ist "
            f"{encoded_video.get('codec_name')!r}, erwartet wurde 'av1'."
        )
    if any(
        stream.get("codec_type") == "audio" and stream.get("codec_name") != "aac"
        for stream in encoded_metadata.get("streams", [])
    ):
        raise RuntimeError("Ausgabeprüfung fehlgeschlagen: Audiospur ist nicht AAC.")
    source_audio_count = sum(
        stream.get("codec_type") == "audio"
        for stream in source_metadata.get("streams", [])
    )
    output_audio_count = sum(
        stream.get("codec_type") == "audio"
        for stream in encoded_metadata.get("streams", [])
    )
    if output_audio_count < source_audio_count:
        raise RuntimeError(
            "Ausgabeprüfung fehlgeschlagen: Nicht alle Audiospuren wurden übernommen."
        )

    original_video = _video_stream(source_metadata)
    original_width = int(original_video.get("width") or 0)
    original_height = int(original_video.get("height") or 0)
    output_width = int(encoded_video.get("width") or 0)
    output_height = int(encoded_video.get("height") or 0)
    downscale_required = original_width >= 3840 or original_height >= 2160
    if output_width <= 0 or output_height <= 0:
        raise RuntimeError("Ausgabeprüfung fehlgeschlagen: Videoauflösung fehlt.")
    if downscale_required and output_height > 1440:
        raise RuntimeError(
            f"Ausgabeprüfung fehlgeschlagen: 4K-Video wurde nicht auf 1440p "
            f"skaliert ({output_width}x{output_height})."
        )
    if not downscale_required and (
        output_width > original_width or output_height > original_height
    ):
        raise RuntimeError("Ausgabeprüfung fehlgeschlagen: Auflösung wurde unerwartet erhöht.")
    try:
        source_duration = float(source_metadata.get("format", {}).get("duration"))
        output_duration = float(encoded_metadata.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        source_duration = output_duration = 0.0
    if source_duration > 0 and output_duration > 0:
        allowed_duration_difference = max(2.0, source_duration * 0.05)
        if abs(source_duration - output_duration) > allowed_duration_difference:
            raise RuntimeError(
                "Ausgabeprüfung fehlgeschlagen: Videodauer weicht stärker als "
                f"{allowed_duration_difference:.1f} s ab."
            )

    _run_command(
        [
            ffmpeg_binary,
            "-v", "error",
            "-xerror",
            "-i", str(encoded_path),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-f", "null",
            "-",
        ],
        step="Ausgabedekodierung",
        source_path=source_path,
    )

    source_creation_time = _creation_time(source_metadata)
    encoded_creation_time = _creation_time(encoded_metadata)
    if source_creation_time and encoded_creation_time != source_creation_time:
        logger.warning(
            "Videometadaten-Warnung | Datei=%s | creation_time Quelle=%s "
            "| Ausgabe=%s; Zeitstempel konnte nicht unverändert erhalten werden.",
            source_path,
            source_creation_time,
            encoded_creation_time or "(fehlt)",
        )
    return encoded_metadata


def compress_video(
    source_path: Path,
    output_path: Path,
    profile: str = "ARCHIVE",
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
) -> VideoCompressionResult:
    """Encode one supported video and publish output only after stream/decode checks."""
    source_path = Path(source_path)
    output_path = Path(output_path)
    selected_profile = profile.upper()
    if selected_profile not in PROFILES:
        raise ValueError(
            f"Unbekanntes Videoprofil {profile!r}; gültig sind: {', '.join(PROFILES)}"
        )
    if source_path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise ValueError(f"Nicht unterstütztes Videoformat: {source_path.suffix}")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("Die AV1/AAC-Ausgabedatei muss den MP4-Container verwenden.")
    if source_path.resolve() == output_path.resolve():
        raise ValueError("Ein temporärer Ausgabepfad muss sich von der Eingabedatei unterscheiden.")
    if output_path.exists():
        raise FileExistsError(f"Ausgabedatei existiert bereits: {output_path}")

    started_at = time.perf_counter()
    original_size = source_path.stat().st_size
    logger.info(
        "Videokomprimierung gestartet | Datei=%s | Profil=%s | Original=%.2f MB",
        source_path,
        selected_profile,
        original_size / (1024 * 1024),
    )

    temporary_path: Path | None = None
    try:
        source_metadata = probe_video(source_path, ffprobe_binary)
        video = _video_stream(source_metadata)
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ValueError(f"Ungültige Videoauflösung {width}x{height}: {source_path}")

        profile_settings = PROFILES[selected_profile]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".jolia-video-",
            suffix=".mp4",
            dir=output_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        command = [
            ffmpeg_binary,
            "-hide_banner",
            "-v", "warning",
            "-y",
            "-i", str(source_path),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-map_metadata", "0",
            "-map_chapters", "0",
        ]
        creation_time = _creation_time(source_metadata)
        if creation_time:
            command.extend(["-metadata", f"creation_time={creation_time}"])
        if width >= 3840 or height >= 2160:
            command.extend(["-vf", "scale=-2:1440"])
        command.extend(
            [
                "-c:v", "libsvtav1",
                "-crf", str(profile_settings.crf),
                "-preset", str(profile_settings.preset),
                "-g", "240",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", profile_settings.audio_bitrate,
                "-movflags", "+faststart",
                str(temporary_path),
            ]
        )
        encoded = _run_command(command, step="FFmpeg-Encoding", source_path=source_path)
        for line in (encoded.stderr or "").splitlines():
            if line.strip():
                logger.warning(
                    "FFmpeg-Diagnose | Datei=%s | %s",
                    source_path,
                    line.strip(),
                )

        _validate_encoded_video(
            temporary_path,
            source_metadata,
            ffmpeg_binary,
            ffprobe_binary,
            source_path,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            raise FileExistsError(f"Ausgabedatei wurde während der Kodierung angelegt: {output_path}")
        os.replace(temporary_path, output_path)
        temporary_path = None

        compressed_size = output_path.stat().st_size
        elapsed = time.perf_counter() - started_at
        result = VideoCompressionResult(
            source_path=source_path,
            output_path=output_path,
            original_size=original_size,
            compressed_size=compressed_size,
            processing_time=elapsed,
        )
        logger.info(
            "[OK] %s | original_size_mb=%.2f | compressed_size_mb=%.2f "
            "| saved_percentage=%.1f%% | processing_time=%.1fs",
            source_path.name,
            original_size / (1024 * 1024),
            compressed_size / (1024 * 1024),
            result.saved_percentage,
            elapsed,
        )
        return result
    except Exception:
        logger.exception("Videokomprimierung fehlgeschlagen | Datei=%s", source_path)
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _encode_video_task(
    task: tuple[str, str, str, str, str],
) -> VideoCompressionResult:
    source_path, output_path, profile, ffmpeg_binary, ffprobe_binary = task
    return compress_video(
        Path(source_path),
        Path(output_path),
        profile,
        ffmpeg_binary,
        ffprobe_binary,
    )


def is_already_compressed_video(
    source_path: Path,
    ffprobe_binary: str,
) -> bool:
    metadata = probe_video(source_path, ffprobe_binary)
    video_stream = _video_stream(metadata)
    audio_streams = [
        stream
        for stream in metadata.get("streams", [])
        if stream.get("codec_type") == "audio"
    ]
    return (
        video_stream.get("codec_name") == "av1"
        and all(stream.get("codec_name") == "aac" for stream in audio_streams)
    )


def compress_directory(
    directory: Path,
    profile: str = "ARCHIVE",
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    max_workers: int | None = None,
) -> list[VideoCompressionResult]:
    """Recursively compress video files, replacing sources only after validation."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(directory)
    if profile.upper() not in PROFILES:
        raise ValueError(
            f"Unbekanntes Videoprofil {profile!r}; gültig sind: {', '.join(PROFILES)}"
        )

    source_paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES
    )
    tasks: list[tuple[str, str, str, str, str]] = []
    failures = 0
    for source_path in source_paths:
        try:
            if is_already_compressed_video(source_path, ffprobe_binary):
                logger.info("Video bereits verarbeitet; übersprungen | Datei=%s", source_path)
                continue
        except Exception:
            failures += 1
            logger.exception("Batch-ffprobe fehlgeschlagen | Datei=%s", source_path)
            continue
        destination = (
            source_path.with_name(f".jolia-video-{os.getpid()}-{len(tasks)}.mp4")
            if source_path.suffix.lower() == ".mp4"
            else source_path.with_suffix(".mp4")
        )
        if destination != source_path and destination.exists():
            failures += 1
            logger.error(
                "Video übersprungen, da Zieldatei bereits existiert | Quelle=%s | Ziel=%s",
                source_path,
                destination,
            )
            continue
        tasks.append(
            (
                str(source_path),
                str(destination),
                profile.upper(),
                ffmpeg_binary,
                ffprobe_binary,
            )
        )

    if not tasks:
        if failures:
            logger.error(
                "Videokomprimierung abgeschlossen | Erfolgreich=0 | Fehlgeschlagen=%d",
                failures,
            )
            raise RuntimeError(f"{failures} Video(s) konnten nicht verarbeitet werden.")
        logger.info("Videokomprimierung abgeschlossen | Verarbeitbare Dateien=0")
        return []

    workers = max_workers or min(max(1, (os.cpu_count() or 1) // 12), len(tasks))
    if workers < 1:
        raise ValueError("max_workers muss mindestens 1 sein.")
    results: list[VideoCompressionResult] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_encode_video_task, task): (
                Path(task[0]),
                Path(task[1]),
            )
            for task in tasks
        }
        total = len(futures)
        for completed, future in enumerate(as_completed(futures), start=1):
            source_path, encoded_path = futures[future]
            try:
                result = future.result()
                if source_path.suffix.lower() == ".mp4":
                    os.replace(result.output_path, source_path)
                    result = VideoCompressionResult(
                        source_path=source_path,
                        output_path=source_path,
                        original_size=result.original_size,
                        compressed_size=result.compressed_size,
                        processing_time=result.processing_time,
                    )
                else:
                    source_path.unlink()
                results.append(result)
                logger.info(
                    "[OK] %s | original_size_mb=%.2f | compressed_size_mb=%.2f "
                    "| saved_percentage=%.1f%% | processing_time=%.1fs",
                    source_path.name,
                    result.original_size / (1024 * 1024),
                    result.compressed_size / (1024 * 1024),
                    result.saved_percentage,
                    result.processing_time,
                )
                logger.info(
                    "Videokomprimierung-Fortschritt | %d/%d | Datei=%s",
                    completed,
                    total,
                    source_path.name,
                )
            except subprocess.CalledProcessError as exc:
                failures += 1
                if source_path.suffix.lower() == ".mp4":
                    encoded_path.unlink(missing_ok=True)
                logger.error(
                    "Batch-Videokomprimierung fehlgeschlagen | Datei=%s | Exitcode=%s "
                    "| stdout=%s | stderr=%s",
                    source_path,
                    exc.returncode,
                    (exc.stdout or "").strip() or "(leer)",
                    (exc.stderr or "").strip() or "(leer)",
                    exc_info=True,
                )
            except Exception:
                failures += 1
                if source_path.suffix.lower() == ".mp4":
                    encoded_path.unlink(missing_ok=True)
                logger.exception("Batch-Videokomprimierung fehlgeschlagen | Datei=%s", source_path)

    if failures:
        logger.error(
            "Videokomprimierung abgeschlossen | Erfolgreich=%d | Fehlgeschlagen=%d",
            len(results),
            failures,
        )
        raise RuntimeError(f"{failures} Video(s) konnten nicht verarbeitet werden.")
    else:
        logger.info(
            "Videokomprimierung abgeschlossen | Erfolgreich=%d | Fehlgeschlagen=0",
            len(results),
        )
    return results
