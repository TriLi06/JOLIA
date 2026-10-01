from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )

    # Drittpakete weniger gesprächig machen
    for noisy in ("httpx", "httpcore", "chromadb", "sentence_transformers",
                  "PIL", "watchdog", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
