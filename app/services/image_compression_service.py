from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
MAX_IMAGE_EDGE = 4096
_ENCODER_WARNING_MARKERS = (
    "warning",
    "error",
    "failed",
    "unsupported",
    "not found",
    "ignored",
    "cannot",
    "unable",
)


@dataclass(frozen=True)
class CompressionResult:
    source_path: Path
    output_path: Path
    original_size: int
    compressed_size: int

    @property
    def reduction_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.original_size - self.compressed_size) * 100 / self.original_size


def compress_image(
    source_path: Path,
    output_path: Path,
    avifenc_binary: str = "avifenc",
) -> CompressionResult:
    source_path = Path(source_path)
    output_path = Path(output_path)
    logger.info("Bildkomprimierung gestartet | Datei=%s", source_path)
    try:
        result = _compress_image(source_path, output_path, avifenc_binary)
    except subprocess.CalledProcessError as exc:
        logger.error(
            "Bildkomprimierung fehlgeschlagen | Datei=%s | Schritt=AVIF-Encoder "
            "| Exitcode=%s | stdout=%s | stderr=%s",
            source_path,
            exc.returncode,
            (exc.stdout or "").strip() or "(leer)",
            (exc.stderr or "").strip() or "(leer)",
            exc_info=True,
        )
        raise
    except Exception:
        logger.exception("Bildkomprimierung fehlgeschlagen | Datei=%s", source_path)
        raise

    logger.info(
        "Bildkomprimierung abgeschlossen | Datei=%s | Original=%d Bytes "
        "| AVIF=%d Bytes | Reduktion=%.1f%%",
        source_path,
        result.original_size,
        result.compressed_size,
        result.reduction_percent,
    )
    return result


def _compress_image(
    source_path: Path,
    output_path: Path,
    avifenc_binary: str,
) -> CompressionResult:
    """Denoise and encode one JPEG, PNG, TIFF or WebP image as AVIF."""
    if source_path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError(f"Nicht unterstütztes Bildformat: {source_path.suffix}")
    if source_path.resolve() == output_path.resolve():
        raise ValueError("Eingabe- und Ausgabedatei dürfen nicht identisch sein.")

    import cv2
    import numpy as np
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)
    original_size = source_path.stat().st_size

    with tempfile.TemporaryDirectory(prefix=".jolia-avif-", dir=output_path.parent) as temp_dir:
        temp_path = Path(temp_dir)
        png_path = temp_path / "input.png"
        command = [
            avifenc_binary,
            "--codec", "svt",
            "--speed", "0",
            "--jobs", str(os.cpu_count() or 1),
            "--yuv", "420",
            "--advanced", "crf=28",
        ]

        with Image.open(source_path) as image:
            exif_payload = image.info.get("exif")
            if not exif_payload:
                exif = image.getexif()
                exif_payload = exif.tobytes() if exif else None
            icc_profile = image.info.get("icc_profile")
            xmp_payload = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
            if isinstance(xmp_payload, str):
                xmp_payload = xmp_payload.encode("utf-8")

            rgb_image = image.convert("RGB")
            pixels_bgr = cv2.cvtColor(np.asarray(rgb_image), cv2.COLOR_RGB2BGR)
            denoised_bgr = cv2.fastNlMeansDenoisingColored(
                pixels_bgr,
                None,
                h=3,
                hColor=3,
                templateWindowSize=7,
                searchWindowSize=21,
            )
            pixels_rgb = cv2.cvtColor(denoised_bgr, cv2.COLOR_BGR2RGB)
            processed_image = Image.fromarray(pixels_rgb)

            longest_edge = max(processed_image.size)
            if longest_edge > MAX_IMAGE_EDGE:
                scale = MAX_IMAGE_EDGE / longest_edge
                resized = (
                    max(1, round(processed_image.width * scale)),
                    max(1, round(processed_image.height * scale)),
                )
                processed_image = processed_image.resize(
                    resized,
                    Image.Resampling.LANCZOS,
                )

            processed_image.save(png_path, format="PNG", icc_profile=icc_profile)

        if exif_payload:
            exif_path = temp_path / "metadata.exif"
            exif_path.write_bytes(exif_payload)
            command.extend(["--exif", str(exif_path)])
        if icc_profile:
            icc_path = temp_path / "metadata.icc"
            icc_path.write_bytes(icc_profile)
            command.extend(["--icc", str(icc_path)])
        if xmp_payload:
            xmp_path = temp_path / "metadata.xmp"
            xmp_path.write_bytes(xmp_payload)
            command.extend(["--xmp", str(xmp_path)])

        command.extend([str(png_path), str(output_path)])
        encoder_result = subprocess.run(command, check=True, capture_output=True, text=True)
        for stream_name, stream_output in (
            ("stdout", encoder_result.stdout),
            ("stderr", encoder_result.stderr),
        ):
            for line in (stream_output or "").splitlines():
                if any(marker in line.lower() for marker in _ENCODER_WARNING_MARKERS):
                    logger.warning(
                        "AVIF-Encoder-Diagnose | Datei=%s | Stream=%s | %s",
                        source_path,
                        stream_name,
                        line.strip(),
                    )
                else:
                    logger.debug(
                        "AVIF-Encoder-Ausgabe | Datei=%s | Stream=%s | %s",
                        source_path,
                        stream_name,
                        line.strip(),
                    )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"avifenc hat keine gültige Ausgabedatei erstellt: {output_path}")

    compressed_size = output_path.stat().st_size
    return CompressionResult(source_path, output_path, original_size, compressed_size)


def _compress_task(arguments: tuple[str, str, str]) -> CompressionResult:
    source_path, output_path, avifenc_binary = arguments
    return compress_image(Path(source_path), Path(output_path), avifenc_binary)


def compress_directory(
    directory: Path,
    avifenc_binary: str = "avifenc",
    max_workers: int | None = None,
) -> list[CompressionResult]:
    """Recursively encode supported images, writing sibling .avif files in parallel."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(directory)

    source_paths = sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES
    )
    if not source_paths:
        return []

    worker_count = max_workers or min(os.cpu_count() or 1, len(source_paths))
    tasks = [
        (
            str(source_path),
            str(source_path.with_suffix(".avif")),
            avifenc_binary,
        )
        for source_path in source_paths
    ]
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(_compress_task, tasks))
