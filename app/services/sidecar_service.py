from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def write_json_sidecar(file_path: Path, data: dict) -> Path:
    sidecar_path = file_path.parent / (file_path.name + ".json")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return sidecar_path


def write_md_sidecar(file_path: Path, content: str) -> Path:
    sidecar_path = file_path.parent / (file_path.name + ".md")
    with open(sidecar_path, "w", encoding="utf-8") as f:
        f.write(content)
    return sidecar_path


def read_json_sidecar(file_path: Path) -> dict | None:
    sidecar_path = file_path.parent / (file_path.name + ".json")
    if not sidecar_path.exists():
        return None
    with open(sidecar_path, encoding="utf-8") as f:
        return json.load(f)


def read_md_sidecar(file_path: Path) -> str | None:
    sidecar_path = file_path.parent / (file_path.name + ".md")
    if not sidecar_path.exists():
        return None
    return sidecar_path.read_text(encoding="utf-8")


def build_document_md(
    original_filename: str,
    content_type: str,
    extracted_text: str,
    metadata: dict,
    processed_at: str | None = None,
    ai_summary: str = "",
) -> str:
    if processed_at is None:
        processed_at = datetime.now().isoformat()

    meta_lines = "\n".join(f"- **{k}:** {v}" for k, v in metadata.items())

    summary_section = ""
    if ai_summary:
        summary_section = f"\n## KI-Zusammenfassung\n\n> {ai_summary}\n"

    return f"""# Dokumentzusammenfassung

**Originaldatei:** {original_filename}  
**Typ:** {content_type}  
**Verarbeitet am:** {processed_at}  
{summary_section}
## Extrahierter Text

{extracted_text}

## Metadaten

{meta_lines}
"""


def build_image_md(
    original_filename: str,
    ocr_text: str,
    metadata: dict,
    processed_at: str | None = None,
    vision_description: str = "",
    face_count: int | None = None,
    ai_summary: str = "",
) -> str:
    if processed_at is None:
        processed_at = datetime.now().isoformat()

    meta_lines = "\n".join(f"- **{k}:** {v}" for k, v in metadata.items())

    summary_section = ""
    if ai_summary:
        summary_section = f"\n## KI-Zusammenfassung\n\n> {ai_summary}\n"

    description_section = ""
    if vision_description:
        description_section = f"\n## Bildbeschreibung (KI)\n\n{vision_description}\n"

    ocr_section = f"\n## OCR-Text\n\n{ocr_text or '(kein Text erkannt)'}\n"

    face_section = ""
    if face_count is not None:
        face_section = f"\n## Gesichtserkennung\n\n- **Erkannte Gesichter:** {face_count}\n"

    return f"""# Bildzusammenfassung

**Originaldatei:** {original_filename}  
**Verarbeitet am:** {processed_at}  
{summary_section}{description_section}{ocr_section}{face_section}
## Metadaten

{meta_lines}
"""


def build_audio_md(
    original_filename: str,
    audio_metadata: dict,
    transcript: str | None = None,
    processed_at: str | None = None,
) -> str:
    if processed_at is None:
        processed_at = datetime.now().isoformat()

    meta_lines = "\n".join(f"- **{k}:** {v}" for k, v in audio_metadata.items())
    transcript_section = f"\n## Transkript\n\n{transcript}" if transcript else ""
    return f"""# Audio-Zusammenfassung

**Originaldatei:** {original_filename}  
**Verarbeitet am:** {processed_at}  

## Metadaten

{meta_lines}
{transcript_section}
"""


def build_video_md(
    original_filename: str,
    video_metadata: dict,
    transcript: str | None = None,
    processed_at: str | None = None,
) -> str:
    if processed_at is None:
        processed_at = datetime.now().isoformat()

    meta_lines = "\n".join(f"- **{k}:** {v}" for k, v in video_metadata.items())
    transcript_section = f"\n## Transkript\n\n{transcript}" if transcript else ""
    return f"""# Video-Zusammenfassung

**Originaldatei:** {original_filename}  
**Verarbeitet am:** {processed_at}  

## Metadaten

{meta_lines}
{transcript_section}
"""
