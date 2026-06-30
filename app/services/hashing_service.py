from __future__ import annotations

import hashlib
from pathlib import Path


def compute_sha256(file_path: Path, chunk_bytes: int = 65536) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while block := f.read(chunk_bytes):
            h.update(block)
    return h.hexdigest()
