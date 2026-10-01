import json
import tempfile
from pathlib import Path

from app.services.sidecar_service import (
    write_json_sidecar,
    write_md_sidecar,
    read_json_sidecar,
    read_md_sidecar,
)


def test_json_sidecar_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        fake_file = Path(td) / "test.pdf"
        fake_file.write_bytes(b"dummy")

        data = {"file_id": "abc", "pages": 3, "word_count": 500}
        sidecar_path = write_json_sidecar(fake_file, data)

        assert sidecar_path.exists()
        assert sidecar_path.name == "test.pdf.json"

        loaded = read_json_sidecar(fake_file)
        assert loaded == data


def test_md_sidecar_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        fake_file = Path(td) / "document.docx"
        fake_file.write_bytes(b"dummy")

        content = "# Test\n\nHallo Welt."
        sidecar_path = write_md_sidecar(fake_file, content)

        assert sidecar_path.exists()
        assert sidecar_path.name == "document.docx.md"

        loaded = read_md_sidecar(fake_file)
        assert loaded == content


def test_missing_sidecar_returns_none():
    with tempfile.TemporaryDirectory() as td:
        fake_file = Path(td) / "ghost.pdf"
        fake_file.write_bytes(b"dummy")

        assert read_json_sidecar(fake_file) is None
        assert read_md_sidecar(fake_file) is None
