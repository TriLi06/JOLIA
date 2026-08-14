from __future__ import annotations

import logging
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import TextChunk, split_text

logger = logging.getLogger(__name__)


class ImageProcessor(BaseProcessor):
    processor_version = "2.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        try:
            img = self._open_image(file_path)
        except Exception as exc:
            return ProcessingResult(success=False, error_message=f"Bild-Lesefehler: {exc}")

        width, height = img.size
        exif_data = self._extract_exif(img)
        sharpness_score = self._compute_sharpness(img)
        perceptual_hash = self._compute_phash(img)
        ocr_text = ""
        ocr_confidence = 100
        vision_description = ""

        vision_backend = getattr(config.models, "vision_backend", "tesseract")
        if config.processing.enable_image_ocr:
            if vision_backend == "ollama":
                vision_timeout = getattr(config.models, "vision_ollama_timeout", config.models.ollama_timeout)
                context_lines = self._build_vision_context(exif_data)
                vision_description, ocr_text, ocr_confidence = self._run_vision_ollama_structured(
                    file_path, config.models.vision_ollama_model, config.models.ollama_base_url,
                    vision_timeout, context_lines=context_lines,
                )
                # Fallback: Wenn das Vision-Modell nichts liefert (Timeout, Modell nicht
                # geladen, CPU-Limit), klassische Tesseract-OCR nutzen, damit zumindest
                # Text und ein Chunk entstehen.
                if not vision_description.strip() and not ocr_text.strip():
                    logger.info(
                        "Vision-Backend lieferte keine Daten für %s – Fallback auf Tesseract-OCR.",
                        file_path.name,
                    )
                    ocr_text, ocr_confidence = self._run_ocr(img, config.processing.ocr_languages)
            else:
                ocr_text, ocr_confidence = self._run_ocr(img, config.processing.ocr_languages)

        needs_review = ocr_confidence < config.processing.ocr_confidence_threshold

        # --- Metadaten aufbauen ---
        metadata: dict = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
            "Auflösung": f"{width} × {height}",
            "Format": img.format or "Unbekannt",
        }
        if ocr_confidence:
            metadata["OCR-Konfidenz"] = f"{ocr_confidence}%"
        if sharpness_score is not None:
            metadata["Bildschärfe"] = f"{'scharf' if sharpness_score >= 100 else 'unscharf'} ({sharpness_score:.1f})"
        metadata.update(exif_data)

        # --- Suchtext aus allen Quellen aufbauen ---
        search_parts = [f"Dateiname: {file_record.original_filename}"]

        capture_date = exif_data.get("DateTimeOriginal") or exif_data.get("DateTime") or exif_data.get("DateTimeDigitized")
        if capture_date:
            search_parts.append(f"Aufnahmedatum: {capture_date}")
        if exif_data.get("Make") or exif_data.get("Model"):
            search_parts.append(f"Kamera: {exif_data.get('Make', '')} {exif_data.get('Model', '')}".strip())
        if exif_data.get("LensModel"):
            search_parts.append(f"Objektiv: {exif_data['LensModel']}")
        if exif_data.get("GPS"):
            search_parts.append(f"GPS: {exif_data['GPS']}")
        if exif_data.get("Artist"):
            search_parts.append(f"Fotograf: {exif_data['Artist']}")
        if exif_data.get("Copyright"):
            search_parts.append(f"Copyright: {exif_data['Copyright']}")
        if exif_data.get("ImageDescription"):
            search_parts.append(f"Bildbeschreibung (EXIF): {exif_data['ImageDescription']}")
        # Kameraeinstellungen kompakt
        cam_settings = []
        if exif_data.get("FNumber"):
            cam_settings.append(f"f/{exif_data['FNumber']}")
        if exif_data.get("ExposureTime"):
            cam_settings.append(f"{exif_data['ExposureTime']}s")
        if exif_data.get("ISOSpeedRatings"):
            cam_settings.append(f"ISO {exif_data['ISOSpeedRatings']}")
        if exif_data.get("FocalLength"):
            cam_settings.append(f"{exif_data['FocalLength']}mm")
        if cam_settings:
            search_parts.append(f"Kameraeinstellungen: {' | '.join(cam_settings)}")

        if vision_description:
            search_parts.append(f"Bildbeschreibung: {vision_description}")
        if ocr_text.strip():
            search_parts.append(f"Erkannter Text: {ocr_text}")
        if sharpness_score is not None:
            quality = "scharf" if sharpness_score >= 100 else "unscharf/verwackelt"
            search_parts.append(f"Bildqualität: {quality}")

        search_text = "\n".join(search_parts)

        # Chunks: primärer Chunk aus Metadaten + Beschreibung.
        # force_single garantiert mindestens einen durchsuchbaren Chunk, auch wenn
        # nur Metadaten (ohne Beschreibung/OCR) vorhanden sind.
        chunks = split_text(
            search_text,
            chunk_size=config.processing.chunk_size,
            overlap=config.processing.chunk_overlap,
            force_single=True,
        )
        for c in chunks:
            if vision_description:
                c.chunk_type = "description"
            elif ocr_text.strip():
                c.chunk_type = "ocr"
            else:
                c.chunk_type = "metadata"

        # Separater Chunk für OCR-Text wenn Vision-Backend einen eigenen Text liefert
        if vision_backend == "ollama" and ocr_text.strip() and vision_description:
            ocr_chunks = split_text(
                ocr_text,
                chunk_size=config.processing.chunk_size,
                overlap=config.processing.chunk_overlap,
            )
            for c in ocr_chunks:
                c.chunk_type = "ocr"
            chunks.extend(ocr_chunks)

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "images",
            "file_size": file_record.file_size,
            "processor": "ImageProcessor",
            "processor_version": self.processor_version,
            "width": width,
            "height": height,
            "exif": exif_data,
            "vision_description": vision_description,
            "ocr_text": ocr_text,
            "ocr_confidence": ocr_confidence,
            "needs_review": needs_review,
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = sidecar_service.build_image_md(
            file_record.original_filename, ocr_text, metadata,
            vision_description=vision_description,
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        # Aufnahmedatum aus EXIF als inhaltliches Erstellungsdatum (Timeline)
        from app.services import document_date_service
        capture_iso = (
            document_date_service.parse_exif_datetime(exif_data.get("DateTimeOriginal"))
            or document_date_service.parse_exif_datetime(exif_data.get("DateTimeDigitized"))
            or document_date_service.parse_exif_datetime(exif_data.get("DateTime"))
        )

        # Phase B: CLIP-Embedding wenn aktiviert
        if getattr(config.processing, "enable_clip_embeddings", False):
            self._store_clip_embedding(file_path, file_record, config, vision_description)

        return ProcessingResult(
            success=True,
            chunks=chunks,
            metadata=metadata,
            needs_review=needs_review,
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
            sharpness_score=sharpness_score,
            perceptual_hash=perceptual_hash,
            created_at=capture_iso,
        )

    def _store_clip_embedding(self, file_path: Path, file_record, config, vision_description: str = "") -> None:
        """Berechnet Bildvektor und speichert ihn in ChromaDB.
        Im Ollama-Modus wird die Vision-Beschreibung als Text-Embedding genutzt.
        """
        try:
            from app.services import chroma_service
            from app.services.clip_service import embed_image
            clip_backend = getattr(config.models, "clip_backend", "ollama")
            clip_vec = embed_image(
                file_path,
                model_name=config.models.clip_model,
                pretrained=config.models.clip_pretrained,
                vision_description=vision_description,
                clip_backend=clip_backend,
            )
            # Reichhaltigere Textrepräsentation für cross-modal Suche
            text_repr = vision_description or file_record.original_filename
            chroma_service.upsert_chunks(
                collection_name="image_embeddings",
                ids=[f"clip_{file_record.id}"],
                texts=[text_repr],
                embeddings=[clip_vec],
                metadatas=[{
                    "file_id": file_record.id,
                    "source_path": file_record.archive_path,
                    "file_name": file_record.original_filename,
                    "content_type": "images",
                    "has_description": bool(vision_description),
                }],
            )
            logger.info("Bild-Embedding gespeichert für %s (backend=%s)", file_record.original_filename, clip_backend)
        except Exception as exc:
            logger.warning("Bild-Embedding fehlgeschlagen für %s: %s", file_record.original_filename, exc)


    def _open_image(self, file_path: Path):
        from PIL import Image

        # HEIC-Support via pillow-heif
        if file_path.suffix.lower() in (".heic", ".heif"):
            try:
                from pillow_heif import register_heif_opener
                register_heif_opener()
            except ImportError:
                logger.warning("pillow-heif nicht installiert, HEIC evtl. nicht lesbar.")
        return Image.open(str(file_path))

    def _compute_sharpness(self, img) -> float | None:
        """Laplacian-Varianz als Schärfemetrik (höher = schärfer), fuer Best-Aufnahme-Auswahl."""
        try:
            import cv2
            import numpy as np

            gray = np.array(img.convert("L"))
            return float(cv2.Laplacian(gray, cv2.CV_64F).var())
        except Exception as exc:
            logger.debug("Schärfeberechnung fehlgeschlagen: %s", exc)
            return None

    def _compute_phash(self, img) -> str | None:
        """Perceptual Hash fuer Duplikat-/Serienerkennung ähnlicher Aufnahmen."""
        try:
            import imagehash
            return str(imagehash.phash(img))
        except Exception as exc:
            logger.debug("Perceptual-Hash-Berechnung fehlgeschlagen: %s", exc)
            return None

    def _build_vision_context(self, exif_data: dict) -> list[str]:
        """Baut Kontextzeilen (Aufnahmedatum, Kamera, GPS) fuer den Vision-Prompt aus EXIF."""
        lines: list[str] = []
        capture_date = exif_data.get("DateTimeOriginal") or exif_data.get("DateTime")
        if capture_date:
            lines.append(f"Aufnahmedatum: {capture_date}")
        if exif_data.get("GPS"):
            lines.append(f"Aufnahmeort (GPS): {exif_data['GPS']}")
        if exif_data.get("Make") or exif_data.get("Model"):
            lines.append(f"Kamera: {exif_data.get('Make', '')} {exif_data.get('Model', '')}".strip())
        return lines

    def _extract_exif(self, img) -> dict:
        exif_data: dict = {}
        # Relevante Einzel-Tags die wir direkt als String speichern
        _SCALAR_TAGS = {
            "DateTimeOriginal", "DateTime", "DateTimeDigitized",
            "Make", "Model", "Software",
            "Artist", "Copyright", "ImageDescription",
            "LensModel", "LensMake",
            "Orientation", "ColorSpace",
            "WhiteBalance", "Flash",
            "SceneCaptureType", "MeteringMode", "ExposureMode",
            "ExposureProgram", "SensingMethod",
        }
        # Numerische Tags die wir formatiert ausgeben
        _NUMERIC_TAGS = {
            "FNumber", "ExposureTime", "ISOSpeedRatings",
            "FocalLength", "FocalLengthIn35mmFilm",
            "BrightnessValue", "ExposureBiasValue",
            "MaxApertureValue", "SubjectDistance",
            "XResolution", "YResolution",
        }
        try:
            from PIL.ExifTags import TAGS, GPSTAGS

            raw = img._getexif()
            if not raw:
                return exif_data

            for tag_id, value in raw.items():
                tag = TAGS.get(tag_id, str(tag_id))
                if tag == "GPSInfo":
                    gps = {}
                    for gps_tag_id, gps_val in value.items():
                        gps_tag = GPSTAGS.get(gps_tag_id, str(gps_tag_id))
                        gps[gps_tag] = str(gps_val)
                    lat = self._convert_gps(
                        gps.get("GPSLatitude"), gps.get("GPSLatitudeRef")
                    )
                    lon = self._convert_gps(
                        gps.get("GPSLongitude"), gps.get("GPSLongitudeRef")
                    )
                    if lat and lon:
                        exif_data["GPS"] = f"{lat:.6f}, {lon:.6f}"
                        exif_data["GPS_Maps"] = (
                            f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}"
                        )
                    if gps.get("GPSAltitude"):
                        exif_data["GPS_Altitude"] = gps["GPSAltitude"]
                    if gps.get("GPSImgDirection"):
                        exif_data["GPS_Direction"] = gps["GPSImgDirection"]
                elif tag in _SCALAR_TAGS:
                    exif_data[tag] = str(value)
                elif tag in _NUMERIC_TAGS:
                    formatted = self._format_numeric_exif(tag, value)
                    if formatted:
                        exif_data[tag] = formatted
        except Exception as exc:
            logger.debug("EXIF-Extraktion fehlgeschlagen: %s", exc)

        # XMP/IPTC-Daten (falls vorhanden)
        try:
            xmp_data = self._extract_xmp(img)
            exif_data.update(xmp_data)
        except Exception:
            pass

        return exif_data

    def _format_numeric_exif(self, tag: str, value) -> str:
        """Formatiert numerische EXIF-Werte lesbar."""
        try:
            if tag == "ExposureTime":
                if hasattr(value, "numerator") and hasattr(value, "denominator"):
                    num, den = value.numerator, value.denominator
                    if den == 0:
                        return ""
                    if num == 1 or den > num:
                        return f"1/{den // num}s" if num == 1 else f"{num}/{den}s"
                    return f"{num / den:.4g}s"
                return str(value)
            if tag == "FNumber":
                v = float(value) if not isinstance(value, float) else value
                return f"{v:.1f}"
            if tag in ("FocalLength", "FocalLengthIn35mmFilm"):
                v = float(value) if not isinstance(value, float) else value
                return f"{v:.0f}"
            if tag == "ISOSpeedRatings":
                return str(int(value))
            return str(value)
        except Exception:
            return str(value)

    def _extract_xmp(self, img) -> dict:
        """Extrahiert XMP/IPTC-Metadaten (Stichwörter, Beschreibung, Bewertung)."""
        result: dict = {}
        try:
            from PIL import Image
            # Piexif oder direkte XMP-Suche
            if hasattr(img, "info") and "xmp" in img.info:
                xmp_raw = img.info["xmp"]
                if isinstance(xmp_raw, bytes):
                    xmp_raw = xmp_raw.decode("utf-8", errors="ignore")
                import re
                # Stichwörter / Keywords
                kw_match = re.search(r"<dc:subject[^>]*>(.*?)</dc:subject>", xmp_raw, re.DOTALL)
                if kw_match:
                    keywords = re.findall(r"<rdf:li[^>]*>(.*?)</rdf:li>", kw_match.group(1))
                    if keywords:
                        result["Keywords"] = ", ".join(keywords)
                # Beschreibung
                desc_match = re.search(r"<dc:description[^>]*>.*?<rdf:Alt[^>]*>.*?<rdf:li[^>]*>(.*?)</rdf:li>",
                                        xmp_raw, re.DOTALL)
                if desc_match:
                    result["XMP_Description"] = desc_match.group(1).strip()
                # Rating
                rating_match = re.search(r'xmp:Rating[>=\s"]+(\d)', xmp_raw)
                if rating_match:
                    result["Rating"] = rating_match.group(1)
        except Exception:
            pass
        return result

    def _convert_gps(self, coords_str: str | None, ref: str | None) -> float | None:
        if not coords_str or not ref:
            return None
        try:
            # Coords als String wie "((47, 1), (30, 1), (0, 1))" parsen
            import ast
            coords = ast.literal_eval(coords_str)
            degrees = float(coords[0][0]) / float(coords[0][1])
            minutes = float(coords[1][0]) / float(coords[1][1])
            seconds = float(coords[2][0]) / float(coords[2][1])
            value = degrees + minutes / 60 + seconds / 3600
            if ref in ("S", "W"):
                value = -value
            return value
        except Exception:
            return None

    def _run_ocr(self, img, languages: str) -> tuple[str, int]:
        try:
            import pytesseract

            data = pytesseract.image_to_data(
                img,
                lang=languages,
                output_type=pytesseract.Output.DICT,
            )
            words = [
                w for w, c in zip(data["text"], data["conf"])
                if w.strip() and int(c) > 0
            ]
            confidences = [int(c) for c in data["conf"] if int(c) > 0]
            text = " ".join(words)
            avg_conf = int(sum(confidences) / len(confidences)) if confidences else 0
            return text, avg_conf
        except Exception as exc:
            logger.warning("OCR fehlgeschlagen: %s", exc)
            return "", 0

    # _run_vision_ollama_structured ist in BaseProcessor definiert und wird geerbt.

    def _run_vision_ollama(self, file_path: Path, model: str, base_url: str) -> tuple[str, int]:
        """Legacy-Wrapper – liefert kombinierten Text zurück."""
        from app.config import get_config
        cfg = get_config()
        desc, ocr, conf = self._run_vision_ollama_structured(
            file_path, model, base_url, cfg.models.ollama_timeout
        )
        combined = "\n".join(filter(None, [desc, ocr]))
        return combined, conf
