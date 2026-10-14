import sys
from types import ModuleType, SimpleNamespace

from app.processors.audio_processor import AudioProcessor
from app.services.sidecar_service import read_md_sidecar


def test_audio_tags_drive_timeline_and_are_written_to_markdown(monkeypatch, tmp_path):
    tags = {
        "title": ["Song"],
        "artist": ["Artist"],
        "originaldate": ["1979-10-26"],
        "albumartist": ["Album Artist"],
        "comment": ["Additional metadata"],
    }
    mutagen_module = ModuleType("mutagen")

    def fake_mutagen_file(path, easy):
        assert path.endswith("song.mp3")
        assert easy is True
        return SimpleNamespace(
            tags=tags,
            info=SimpleNamespace(length=123, bitrate=320000),
        )

    mutagen_module.File = fake_mutagen_file
    monkeypatch.setitem(sys.modules, "mutagen", mutagen_module)

    file_path = tmp_path / "song.mp3"
    file_path.write_bytes(b"audio")
    file_record = SimpleNamespace(
        id="file-id",
        original_filename="song.mp3",
        mime_type="audio/mpeg",
        file_size=5,
        sha256="a" * 64,
    )
    config = SimpleNamespace(
        processing=SimpleNamespace(
            enable_audio_transcription=False,
            enable_media_summarization=False,
            enable_clap_embeddings=False,
            chunk_size=1000,
            chunk_overlap=0,
        )
    )

    result = AudioProcessor().process(file_path, file_record, config)

    assert result.created_at == "1979-10-26T00:00:00"
    assert result.metadata["albumartist"] == "Album Artist"
    assert result.metadata["comment"] == "Additional metadata"
    markdown = read_md_sidecar(file_path)
    assert markdown is not None
    assert "- **comment:** Additional metadata" in markdown
    assert "- **Aufnahmedatum:** 1979-10-26T00:00:00" in markdown
    assert "- **duration:** 2:03" in markdown
    assert "- **bitrate:** 320000 kbps" in markdown
    assert "- **Dateigröße:** 5 Bytes" in markdown
