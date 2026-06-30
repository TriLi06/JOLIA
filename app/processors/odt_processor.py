from __future__ import annotations

import logging
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import split_text

logger = logging.getLogger(__name__)


class OdtProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        try:
            from odf.opendocument import load as odf_load
            from odf.text import P, H, Table, TableRow, TableCell
            from odf.teletype import extractText

            doc = odf_load(str(file_path))
        except ImportError:
            return ProcessingResult(
                success=False,
                error_message="Paket 'odfpy' nicht installiert. Bitte 'pip install odfpy' ausführen.",
            )
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"ODT-Lesefehler: {exc}")

        parts: list[str] = []
        paragraph_count = 0
        table_count = 0

        try:
            body = doc.text  # type: ignore[attr-defined]
            _collect_text_nodes(body, parts)

            # Zählen für Metadaten
            paragraph_count = sum(
                1 for el in body.getElementsByType(P) if extractText(el).strip()  # type: ignore[arg-type]
            )
            table_count = len(body.getElementsByType(Table))  # type: ignore[arg-type]
        except Exception as exc:
            logger.warning("ODT-Textextraktion teilweise fehlgeschlagen: %s", exc)

        full_text = "\n\n".join(p for p in parts if p.strip())

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Absätze": paragraph_count,
            "Tabellen": table_count,
            "Wortanzahl": len(full_text.split()),
        }

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "documents",
            "file_size": file_record.file_size,
            "processor": "OdtProcessor",
            "processor_version": self.processor_version,
            "paragraphs": paragraph_count,
            "tables": table_count,
            "word_count": len(full_text.split()),
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = sidecar_service.build_document_md(
            file_record.original_filename, "OpenDocument-Textdokument (ODT)", full_text, metadata
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


def _collect_text_nodes(element, parts: list[str]) -> None:
    """Traversiert rekursiv ODF-Elemente und sammelt Text."""
    try:
        from odf.text import P, H, TableCell
        from odf.teletype import extractText

        for child in element.childNodes:
            tag = getattr(child, "qname", ("",))[1] if hasattr(child, "qname") else ""
            if hasattr(child, "childNodes"):
                if tag in ("p", "h"):
                    text = extractText(child).strip()
                    if text:
                        parts.append(text)
                elif tag == "table-cell":
                    text = extractText(child).strip()
                    if text:
                        parts.append(text)
                else:
                    _collect_text_nodes(child, parts)
    except Exception:
        pass
