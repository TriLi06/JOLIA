from __future__ import annotations

import logging
import re
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import split_text

logger = logging.getLogger(__name__)


class HtmlProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        try:
            raw = file_path.read_bytes()
            # Zeichenkodierung erkennen
            encoding = _detect_encoding(raw) or "utf-8"
            html = raw.decode(encoding, errors="replace")
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"HTML-Lesefehler: {exc}")

        title, description, headings, body_text = _parse_html(html)

        # Volltext für Chunking: Überschriften voranstellen
        text_parts = []
        if title:
            text_parts.append(f"# {title}")
        if description:
            text_parts.append(f"Beschreibung: {description}")
        if body_text:
            text_parts.append(body_text)

        full_text = "\n\n".join(text_parts)

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Titel": title or "(unbekannt)",
            "Beschreibung": description or "",
            "Zeichenanzahl": len(body_text),
            "Wortanzahl": len(body_text.split()),
            "Überschriften": str(len(headings)),
        }

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "documents",
            "file_size": file_record.file_size,
            "processor": "HtmlProcessor",
            "processor_version": self.processor_version,
            "title": title,
            "description": description,
            "headings": headings,
            "word_count": len(body_text.split()),
            "char_count": len(body_text),
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)

        headings_section = ""
        if headings:
            headings_section = "\n## Überschriften\n\n" + "\n".join(f"- {h}" for h in headings) + "\n"

        md_content = (
            f"# HTML-Zusammenfassung\n\n"
            f"**Originaldatei:** {file_record.original_filename}  \n"
            f"**Titel:** {title or '(unbekannt)'}  \n\n"
            f"{headings_section}"
            f"## Inhalt\n\n{body_text.strip()}\n\n"
            f"## Metadaten\n\n"
            + "\n".join(f"- **{k}:** {v}" for k, v in metadata.items())
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        chunks = split_text(
            full_text,
            chunk_size=config.processing.chunk_size,
            overlap=config.processing.chunk_overlap,
        )

        return ProcessingResult(
            success=True,
            chunks=chunks,
            metadata=metadata,
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
        )


def _detect_encoding(raw: bytes) -> str | None:
    """Versucht, Zeichenkodierung aus dem HTML-Header zu lesen."""
    try:
        snippet = raw[:2048].decode("ascii", errors="replace")
        m = re.search(r'charset=["\']?([a-zA-Z0-9_\-]+)', snippet, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _parse_html(html: str) -> tuple[str, str, list[str], str]:
    """Gibt (title, description, headings, body_text) zurück."""
    title = ""
    description = ""
    headings: list[str] = []
    body_text = ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Titel
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

        # Meta-Description
        meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if meta_desc and meta_desc.get("content"):  # type: ignore[union-attr]
            description = str(meta_desc["content"]).strip()  # type: ignore[index]

        # Überschriften sammeln
        for tag in soup.find_all(["h1", "h2", "h3", "h4"]):
            text = tag.get_text(strip=True)
            if text:
                headings.append(text)

        # Störende Tags entfernen
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()

        body_text = soup.get_text(separator="\n", strip=True)

    except ImportError:
        # Fallback: Regex-basiertes Strippen
        title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if title_m:
            title = re.sub(r"<[^>]+>", "", title_m.group(1)).strip()

        body_text = re.sub(r"<[^>]+>", " ", html)
        body_text = re.sub(r"\s+", " ", body_text).strip()

    return title, description, headings, body_text
