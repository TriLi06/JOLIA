from __future__ import annotations

import email
import email.policy
import logging
from email.message import EmailMessage
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import split_text

logger = logging.getLogger(__name__)


class EmlProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        try:
            raw = file_path.read_bytes()
            msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[assignment]
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"EML-Lesefehler: {exc}")

        subject = str(msg.get("Subject", ""))
        sender = str(msg.get("From", ""))
        recipients = str(msg.get("To", ""))
        cc = str(msg.get("Cc", ""))
        date_str = str(msg.get("Date", ""))
        message_id = str(msg.get("Message-ID", ""))

        # Text-Body extrahieren (plain text bevorzugt, sonst HTML-Fallback)
        body_plain = ""
        body_html = ""
        attachments: list[dict] = []

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = str(part.get_content_disposition() or "")
                if disp == "attachment" or part.get_filename():
                    attachments.append({
                        "filename": part.get_filename() or "unbekannt",
                        "content_type": ctype,
                        "size": len(part.get_payload(decode=True) or b""),
                    })
                elif ctype == "text/plain" and not body_plain:
                    try:
                        body_plain = part.get_payload(decode=True).decode(
                            part.get_content_charset("utf-8"), errors="replace"
                        )
                    except Exception:
                        body_plain = ""
                elif ctype == "text/html" and not body_html:
                    try:
                        html_bytes = part.get_payload(decode=True)
                        body_html = _strip_html(html_bytes.decode(
                            part.get_content_charset("utf-8"), errors="replace"
                        ))
                    except Exception:
                        body_html = ""
        else:
            ctype = msg.get_content_type()
            payload_bytes = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset("utf-8") or "utf-8"
            if ctype == "text/plain":
                body_plain = payload_bytes.decode(charset, errors="replace")
            elif ctype == "text/html":
                body_html = _strip_html(payload_bytes.decode(charset, errors="replace"))

        body_text = body_plain or body_html

        # Volltext für Suche / Chunking
        full_text_parts = []
        if subject:
            full_text_parts.append(f"Betreff: {subject}")
        if sender:
            full_text_parts.append(f"Von: {sender}")
        if recipients:
            full_text_parts.append(f"An: {recipients}")
        if date_str:
            full_text_parts.append(f"Datum: {date_str}")
        if body_text:
            full_text_parts.append(body_text.strip())
        if attachments:
            att_names = ", ".join(a["filename"] for a in attachments)
            full_text_parts.append(f"Anhänge: {att_names}")

        full_text = "\n\n".join(full_text_parts)

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Betreff": subject,
            "Von": sender,
            "An": recipients,
            "Datum": date_str,
            "Anhänge": str(len(attachments)),
        }

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "documents",
            "file_size": file_record.file_size,
            "processor": "EmlProcessor",
            "processor_version": self.processor_version,
            "subject": subject,
            "sender": sender,
            "recipients": recipients,
            "cc": cc,
            "date": date_str,
            "message_id": message_id,
            "attachments": attachments,
            "word_count": len(body_text.split()),
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)

        # Markdown-Sidecar
        att_section = ""
        if attachments:
            att_lines = "\n".join(
                f"- {a['filename']} ({a['content_type']}, {a['size']:,} Bytes)"
                for a in attachments
            )
            att_section = f"\n## Anhänge\n\n{att_lines}\n"

        md_content = (
            f"# E-Mail-Zusammenfassung\n\n"
            f"**Originaldatei:** {file_record.original_filename}  \n"
            f"**Betreff:** {subject}  \n"
            f"**Von:** {sender}  \n"
            f"**An:** {recipients}  \n"
            f"**Datum:** {date_str}  \n\n"
            f"## Inhalt\n\n{body_text.strip()}\n"
            f"{att_section}"
            f"\n## Metadaten\n\n"
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


def _strip_html(html: str) -> str:
    """Entfernt HTML-Tags und gibt reinen Text zurück."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Skripte und Styles entfernen
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        # Fallback ohne BeautifulSoup: einfaches Tag-Strippen
        import re
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()
