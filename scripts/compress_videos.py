from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.video_compression_service import PROFILES, compress_directory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Komprimiert Videos rekursiv zu AV1/AAC und ersetzt Quellen erst nach Prüfung."
    )
    parser.add_argument("directory", type=Path, help="Zu durchsuchender Ordner")
    parser.add_argument(
        "--profile",
        type=str.upper,
        choices=sorted(PROFILES),
        default="ARCHIVE",
        help="Kompressionsprofil (Standard: ARCHIVE)",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Pfad zum ffmpeg-Programm")
    parser.add_argument("--ffprobe", default="ffprobe", help="Pfad zum ffprobe-Programm")
    parser.add_argument(
        "--workers",
        type=int,
        help="Anzahl paralleler Encoder (Standard: etwa ein Worker pro 12 logische CPU-Kerne)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    try:
        results = compress_directory(
            args.directory,
            profile=args.profile,
            ffmpeg_binary=args.ffmpeg,
            ffprobe_binary=args.ffprobe,
            max_workers=args.workers,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logging.getLogger(__name__).error("Batch-Videokomprimierung abgebrochen: %s", exc)
        return 2

    print(f"Erfolgreich komprimiert: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
