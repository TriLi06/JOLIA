from __future__ import annotations

import logging
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import TextChunk, split_pages, split_text

logger = logging.getLogger(__name__)


class PdfProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        try:
            pages = self._extract_text_pages(file_path)
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"PDF-Lesefehler: {exc}")

        # Prüfen ob OCR nötig ist (weniger als 50 Zeichen pro Seite im Schnitt)
        total_chars = sum(len(t) for _, t in pages)
        avg_chars = total_chars / max(len(pages), 1)
        is_scan = avg_chars < 50 and config.processing.enable_ocr

        if is_scan:
            logger.info("PDF scheint gescannt zu sein, starte OCR: %s", file_path.name)
            try:
                pages = self._ocr_pages(file_path, config)
            except Exception as exc:
                logger.warning("OCR fehlgeschlagen für %s: %s", file_path.name, exc)

        full_text = "\n\n".join(f"[Seite {p}]\n{t}" for p, t in pages if t.strip())

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Seitenanzahl": len(pages),
            "Wortanzahl": len(full_text.split()),
            "OCR verwendet": "Ja" if is_scan else "Nein",
        }

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": "application/pdf",
            "content_type": "documents",
            "file_size": file_record.file_size,
            "processor": "PdfProcessor",
            "processor_version": self.processor_version,
            "pages": len(pages),
            "word_count": len(full_text.split()),
            "ocr_used": is_scan,
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = sidecar_service.build_document_md(
            file_record.original_filename, "PDF-Dokument", full_text, metadata
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        chunks = split_pages(
            pages,
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

    def _extract_text_pages(self, file_path: Path) -> list[tuple[int, str]]:
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text))
        return pages

    def _ocr_pages(self, file_path: Path, config) -> list[tuple[int, str]]:
        from pdf2image import convert_from_path
        import pytesseract

        images = convert_from_path(str(file_path), dpi=200)
        pages = []
        for i, img in enumerate(images, start=1):
            text = pytesseract.image_to_string(img, lang=config.processing.ocr_languages)
            pages.append((i, text))
        return pages
