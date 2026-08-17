from __future__ import annotations

import logging
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import TextChunk, split_pages, split_text

logger = logging.getLogger(__name__)


class PdfProcessor(BaseProcessor):
    processor_version = "1.1"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        from app.services import scan_bundle_service

        try:
            pages = self._extract_text_pages(file_path)
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"PDF-Lesefehler: {exc}")

        bundle_id = scan_bundle_service.bundle_id_from_pdf_name(file_record.original_filename or "")
        bundle_meta = scan_bundle_service.load_bundle_meta(bundle_id, config) if bundle_id else None

        # Prüfen ob OCR nötig ist (weniger als 50 Zeichen pro Seite im Schnitt).
        # Bei gebündelten Scans hat Tesseract den Textlayer bereits erzeugt – ein
        # zweiter OCR-Lauf über das PDF würde nur Zeit kosten.
        total_chars = sum(len(t) for _, t in pages)
        avg_chars = total_chars / max(len(pages), 1)
        is_scan = avg_chars < 50 and config.processing.enable_ocr and bundle_meta is None

        if is_scan:
            logger.info("PDF scheint gescannt zu sein, starte OCR: %s", file_path.name)
            try:
                pages = self._ocr_pages(file_path, config)
            except Exception as exc:
                logger.warning("OCR fehlgeschlagen für %s: %s", file_path.name, exc)

        page_visions: list[tuple[int, str, str]] = []
        if bundle_meta:
            page_visions = self._analyze_bundle_pages(bundle_id, config)

        full_text = "\n\n".join(f"[Seite {p}]\n{t}" for p, t in pages if t.strip())
        vision_text = "\n\n".join(
            f"[Seite {p}] {desc}" + (f"\nErkannter Text (KI): {txt}" if txt else "")
            for p, desc, txt in page_visions
            if desc or txt
        )

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Seitenanzahl": len(pages),
            "Wortanzahl": len(full_text.split()),
            "OCR verwendet": "Ja" if is_scan else "Nein",
        }
        if bundle_meta:
            metadata["Quelle"] = f"Scan ({bundle_meta.get('source', 'unbekannt')})"
            metadata["Durchsuchbarer Textlayer"] = "Ja" if bundle_meta.get("has_text_layer") else "Nein"
            metadata["KI-Bildanalyse"] = f"{len(page_visions)} Seite(n)" if page_visions else "Nein"

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
        if bundle_meta:
            json_data["scan_bundle"] = {
                "bundle_id": bundle_id,
                "title": bundle_meta.get("title"),
                "source": bundle_meta.get("source"),
                "has_text_layer": bundle_meta.get("has_text_layer"),
                "vision_pages": len(page_visions),
            }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_body = full_text if not vision_text else f"{full_text}\n\n## KI-Bildanalyse\n\n{vision_text}"
        md_content = sidecar_service.build_document_md(
            file_record.original_filename, "PDF-Dokument", md_body, metadata
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        chunks = split_pages(
            pages,
            chunk_size=config.processing.chunk_size,
            overlap=config.processing.chunk_overlap,
        )
        chunks.extend(
            self._build_vision_chunks(page_visions, pages, config, next_index=len(chunks))
        )

        if bundle_id:
            scan_bundle_service.cleanup_bundle(bundle_id, config)

        return ProcessingResult(
            success=True,
            chunks=chunks,
            metadata=metadata,
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
        )

    def _analyze_bundle_pages(self, bundle_id: str, config) -> list[tuple[int, str, str]]:
        """Ollama-Vision je Seitenbild: erkennt Bildinhalte und handschriftliche Notizen."""
        from app.services import scan_bundle_service

        if not config.scan.vision_per_page:
            return []
        if getattr(config.models, "vision_backend", "tesseract") != "ollama":
            return []

        images = scan_bundle_service.bundle_page_images(bundle_id, config)
        if not images:
            return []
        if config.scan.vision_max_pages > 0:
            images = images[: config.scan.vision_max_pages]

        timeout = getattr(config.models, "vision_ollama_timeout", config.models.ollama_timeout)
        results: list[tuple[int, str, str]] = []
        for page_no, image_path in enumerate(images, start=1):
            try:
                description, ocr_text, _ = self._run_vision_ollama_structured(
                    image_path,
                    config.models.vision_ollama_model,
                    config.models.ollama_base_url,
                    timeout,
                    context_lines=[f"Seite {page_no} eines gescannten Dokuments"],
                )
            except Exception as exc:
                logger.warning("Vision-Analyse für Seite %d fehlgeschlagen: %s", page_no, exc)
                continue
            if description.strip() or ocr_text.strip():
                results.append((page_no, description.strip(), ocr_text.strip()))
        return results

    def _build_vision_chunks(
        self,
        page_visions: list[tuple[int, str, str]],
        pages: list[tuple[int, str]],
        config,
        next_index: int,
    ) -> list[TextChunk]:
        """Beschreibungs- und Handschrift-Chunks aus der Vision-Analyse."""
        page_text = {p: (t or "").strip() for p, t in pages}
        chunks: list[TextChunk] = []

        for page_no, description, vision_text in page_visions:
            if description:
                for part in split_text(
                    description,
                    chunk_size=config.processing.chunk_size,
                    overlap=config.processing.chunk_overlap,
                    force_single=True,
                ):
                    chunks.append(
                        TextChunk(
                            chunk_index=next_index,
                            text=f"[Seite {page_no}] {part.text}",
                            page=page_no,
                            chunk_type="description",
                        )
                    )
                    next_index += 1

            # Nur speichern, wenn die KI mehr erkannt hat als der Textlayer (z.B. Handschrift).
            if vision_text and not self._is_covered_by(vision_text, page_text.get(page_no, "")):
                for part in split_text(
                    vision_text,
                    chunk_size=config.processing.chunk_size,
                    overlap=config.processing.chunk_overlap,
                    force_single=True,
                ):
                    chunks.append(
                        TextChunk(
                            chunk_index=next_index,
                            text=f"[Seite {page_no}] {part.text}",
                            page=page_no,
                            chunk_type="ocr",
                        )
                    )
                    next_index += 1

        return chunks

    @staticmethod
    def _is_covered_by(candidate: str, existing: str) -> bool:
        """True, wenn der Vision-Text kaum Wörter enthält, die nicht schon im PDF stehen."""
        if not existing:
            return False
        existing_words = {w.lower() for w in existing.split() if len(w) > 3}
        candidate_words = [w.lower() for w in candidate.split() if len(w) > 3]
        if not candidate_words:
            return True
        new_words = sum(1 for w in candidate_words if w not in existing_words)
        return new_words / len(candidate_words) < 0.15

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
