from app.services.file_type_service import detect_file_type, is_ignored
from pathlib import Path


def test_detect_pdf():
    mime, ctype = detect_file_type(Path("document.pdf"))
    assert mime == "application/pdf"
    assert ctype == "documents"


def test_detect_jpg():
    mime, ctype = detect_file_type(Path("photo.jpg"))
    assert mime == "image/jpeg"
    assert ctype == "images"


def test_detect_mp3():
    mime, ctype = detect_file_type(Path("song.mp3"))
    assert mime == "audio/mpeg"
    assert ctype == "audio"


def test_detect_mp4():
    mime, ctype = detect_file_type(Path("video.mp4"))
    assert mime == "video/mp4"
    assert ctype == "video"


def test_ignore_temp_files():
    assert is_ignored(Path("~$document.docx")) is True
    assert is_ignored(Path(".hidden")) is True
    assert is_ignored(Path("file.tmp")) is True
    assert is_ignored(Path("file.part")) is True


def test_dont_ignore_normal_files():
    assert is_ignored(Path("document.pdf")) is False
    assert is_ignored(Path("photo.jpg")) is False
    assert is_ignored(Path("song.mp3")) is False
