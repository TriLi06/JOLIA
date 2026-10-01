from __future__ import annotations

from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import TextChunk


class GenericProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        search_text = f"Dateiname: {file_record.original_filename}\nDateiformat: {file_record.mime_type or 'unbekannt'}"

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": file_record.content_type,
            "file_size": file_record.file_size,
            "processor": "GenericProcessor",
            "processor_version": self.processor_version,
            "note": "Unbekanntes Dateiformat – nur Metadaten gespeichert.",
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = (
            f"# Datei-Zusammenfassung\n\n"
            f"**Originaldatei:** {file_record.original_filename}  \n"
            f"**Format:** {file_record.mime_type or 'unbekannt'}  \n"
            f"**Größe:** {file_record.file_size or 0:,} Bytes  \n"
            f"**SHA256:** {file_record.sha256}  \n\n"
            f"*Dieses Dateiformat wird nicht vollständig verarbeitet.*\n"
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        chunk = TextChunk(chunk_index=0, text=search_text, chunk_type="description")

        return ProcessingResult(
            success=True,
            chunks=[chunk],
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
        )
