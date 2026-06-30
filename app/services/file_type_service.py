from __future__ import annotations

import mimetypes
from pathlib import Path

# Erweiterung → (mime_type, content_type)
_EXT_MAP: dict[str, tuple[str, str]] = {
    # Dokumente
    ".pdf":   ("application/pdf", "documents"),
    ".txt":   ("text/plain", "documents"),
    ".md":    ("text/markdown", "documents"),
    ".docx":  ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "documents"),
    ".xlsx":  ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "documents"),
    ".pptx":  ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "documents"),
    ".odt":   ("application/vnd.oasis.opendocument.text", "documents"),
    ".eml":   ("message/rfc822", "documents"),
    ".html":  ("text/html", "documents"),
    ".htm":   ("text/html", "documents"),
    # Bilder
    ".jpg":   ("image/jpeg", "images"),
    ".jpeg":  ("image/jpeg", "images"),
    ".png":   ("image/png", "images"),
    ".tiff":  ("image/tiff", "images"),
    ".tif":   ("image/tiff", "images"),
    ".heic":  ("image/heic", "images"),
    ".webp":  ("image/webp", "images"),
    ".bmp":   ("image/bmp", "images"),
    # Audio
    ".mp3":   ("audio/mpeg", "audio"),
    ".m4a":   ("audio/mp4", "audio"),
    ".wav":   ("audio/wav", "audio"),
    ".flac":  ("audio/flac", "audio"),
    ".ogg":   ("audio/ogg", "audio"),
    ".aac":   ("audio/aac", "audio"),
    # Video
    ".mp4":   ("video/mp4", "video"),
    ".mkv":   ("video/x-matroska", "video"),
    ".avi":   ("video/x-msvideo", "video"),
    ".mov":   ("video/quicktime", "video"),
    ".webm":  ("video/webm", "video"),
    ".m4v":   ("video/mp4", "video"),
}

# Sidecar-Endungen ignorieren
_IGNORE_EXTENSIONS = {".json", ".md"}
_IGNORE_PREFIXES = ("~$", ".")
_IGNORE_SUFFIXES = (".tmp", ".part", ".crdownload", ".download")


def is_ignored(file_path: Path) -> bool:
    name = file_path.name
    if any(name.startswith(p) for p in _IGNORE_PREFIXES):
        return True
    if any(name.endswith(s) for s in _IGNORE_SUFFIXES):
        return True
    # Sidecar-Dateien nicht importieren
    if file_path.suffix.lower() == ".json" and file_path.stem.endswith(
        (".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".odt", ".eml",
         ".html", ".htm", ".jpg", ".jpeg", ".png", ".mp3", ".m4a", ".wav",
         ".ogg", ".mp4", ".mkv")
    ):
        return True
    if file_path.suffix.lower() == ".md" and file_path.stem.endswith(
        (".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".odt", ".eml",
         ".html", ".htm", ".jpg", ".jpeg", ".png", ".mp3", ".m4a", ".wav",
         ".ogg", ".mp4", ".mkv")
    ):
        return True
    return False


def detect_file_type(file_path: Path) -> tuple[str, str]:
    """Gibt (mime_type, content_type) zurück."""
    ext = file_path.suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    # Fallback: Python mimetypes
    mime, _ = mimetypes.guess_type(str(file_path))
    if mime:
        main_type = mime.split("/")[0]
        content_type = {
            "image": "images",
            "audio": "audio",
            "video": "video",
            "text": "documents",
            "application": "documents",
        }.get(main_type, "other")
        return mime, content_type
    return "application/octet-stream", "other"
