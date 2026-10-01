from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import split_text

logger = logging.getLogger(__name__)


class VideoProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        video_meta = self._extract_metadata(file_path)
        thumbnail_path: Path | None = None
        transcript: str | None = None
        summary: str | None = None
        frame_description: str | None = None
        frame_ocr: str | None = None

        # Frame extrahieren (dient als Thumbnail UND Basis für Bildanalyse)
        try:
            thumbnail_path = self._extract_thumbnail(file_path, config)
        except Exception as exc:
            logger.warning("Thumbnail-Extraktion fehlgeschlagen für %s: %s", file_path.name, exc)

        # Bildanalyse des extrahierten Frames via Vision-Modell
        if thumbnail_path and thumbnail_path.exists() and getattr(config.processing, "enable_image_ocr", True):
            vision_backend = getattr(config.models, "vision_backend", "tesseract")
            if vision_backend == "ollama":
                vision_timeout = getattr(config.models, "vision_ollama_timeout", config.models.ollama_timeout)
                frame_description, frame_ocr, _ = self._run_vision_ollama_structured(
                    thumbnail_path, config.models.vision_ollama_model,
                    config.models.ollama_base_url, vision_timeout,
                )
                if frame_description:
                    logger.info("Video-Frame analysiert für %s", file_path.name)

        # Audio-Transkription (optional)
        if config.processing.enable_video_transcription:
            transcript = self._transcribe_audio(file_path, config)

        # Kurze Inhaltszusammenfassung via Ollama (bevorzugt für Clustering/Suche)
        if transcript and getattr(config.processing, "enable_media_summarization", True):
            summary = self._summarize(transcript, video_meta, file_record.original_filename, config)

        # Suchtext: Metadaten + Audio-Inhalt
        search_parts = [f"Dateiname: {file_record.original_filename}"]
        for key in ("duration", "resolution", "codec", "fps"):
            if video_meta.get(key):
                search_parts.append(f"{key.capitalize()}: {video_meta[key]}")
        if summary:
            search_parts.append(f"Inhalt: {summary}")
        elif transcript:
            search_parts.append(f"Transkript (Ausschnitt): {transcript}")

        search_text = "\n".join(search_parts)

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
        }
        metadata.update({k: str(v) for k, v in video_meta.items()})
        if thumbnail_path:
            metadata["Thumbnail"] = str(thumbnail_path)
        if frame_description:
            metadata["Frame-Beschreibung"] = frame_description[:200] + "…" if len(frame_description) > 200 else frame_description

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "video",
            "file_size": file_record.file_size,
            "processor": "VideoProcessor",
            "processor_version": self.processor_version,
            "video_metadata": video_meta,
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            "frame_description": frame_description,
            "frame_ocr": frame_ocr,
            "transcript_sample": transcript,
            "summary": summary,
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = sidecar_service.build_video_md(
            file_record.original_filename, video_meta, summary or transcript
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        # Haupt-Chunk: Metadaten + Audio-Inhalt
        chunks = split_text(
            search_text,
            chunk_size=config.processing.chunk_size,
            overlap=config.processing.chunk_overlap,
        )
        for c in chunks:
            c.chunk_type = "description" if summary else ("transcript" if transcript else "description")

        # Zusatz-Chunk: Frame-Bildbeschreibung (eigener semantischer Vektor)
        if frame_description:
            frame_search_parts = [f"Dateiname: {file_record.original_filename}", f"Video-Frame: {frame_description}"]
            if frame_ocr:
                frame_search_parts.append(f"Sichtbarer Text im Frame: {frame_ocr}")
            frame_chunks = split_text(
                "\n".join(frame_search_parts),
                chunk_size=config.processing.chunk_size,
                overlap=config.processing.chunk_overlap,
            )
            for c in frame_chunks:
                c.chunk_type = "description"
            chunks.extend(frame_chunks)

        return ProcessingResult(
            success=True,
            chunks=chunks,
            metadata=metadata,
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
        )

    def _extract_metadata(self, file_path: Path) -> dict:
        meta: dict = {}
        try:
            from pymediainfo import MediaInfo

            info = MediaInfo.parse(str(file_path))
            for track in info.tracks:
                if track.track_type == "Video":
                    if track.duration:
                        secs = int(float(track.duration) / 1000)
                        meta["duration"] = f"{secs // 60}:{secs % 60:02d}"
                    if track.width and track.height:
                        meta["resolution"] = f"{track.width}×{track.height}"
                    if track.codec_id:
                        meta["codec"] = track.codec_id
                    if track.frame_rate:
                        meta["fps"] = f"{float(track.frame_rate):.2f}"
                elif track.track_type == "Audio":
                    if track.channel_s:
                        meta["audio_channels"] = track.channel_s
                    if track.sampling_rate:
                        meta["audio_sample_rate"] = f"{track.sampling_rate} Hz"
        except Exception as exc:
            logger.warning("pymediainfo-Fehler für %s: %s", file_path.name, exc)
        return meta

    def _extract_thumbnail(self, file_path: Path, config) -> Path | None:
        # Fixer Sekundenoffset hat Vorrang vor dem Prozentwert
        fixed_offset = getattr(config.processing, "video_frame_offset_seconds", 0)
        if fixed_offset > 0:
            offset_secs = fixed_offset
        else:
            video_meta = self._extract_metadata(file_path)
            duration_str = video_meta.get("duration", "0:10")
            try:
                parts = duration_str.split(":")
                total_secs = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else 10
            except (ValueError, IndexError):
                total_secs = 10
            offset_secs = max(1, int(total_secs * config.processing.video_thumbnail_offset_pct / 100))

        thumbnail_path = file_path.parent / (file_path.stem + "_thumb.jpg")

        subprocess.run(
            [
                config.models.ffmpeg_binary,
                "-y",
                "-ss", str(offset_secs),
                "-i", str(file_path),
                "-vframes", "1",
                "-q:v", "2",
                str(thumbnail_path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return thumbnail_path if thumbnail_path.exists() else None

    def _transcribe_audio(self, file_path: Path, config) -> str | None:
        # Backend 1: whisper.cpp (externes Binary)
        if config.models.whisper_cpp_binary:
            return self._transcribe_cpp(file_path, config)
        # Backend 2: openai-whisper (Python-Paket)
        try:
            import whisper as _whisper_check  # noqa: F401
            return self._transcribe_python(file_path, config)
        except ImportError:
            logger.warning(
                "Video-Transkription übersprungen: weder whisper_cpp_binary konfiguriert "
                "noch 'openai-whisper' installiert ('pip install openai-whisper')."
            )
            return None

    def _transcribe_cpp(self, file_path: Path, config) -> str | None:
        temp_wav = file_path.parent / (file_path.stem + "_temp_audio.wav")
        sample_secs = getattr(config.processing, "transcription_sample_seconds", 90)
        try:
            ffmpeg_cmd = [
                config.models.ffmpeg_binary,
                "-y", "-i", str(file_path), "-vn",
            ]
            if sample_secs > 0:
                ffmpeg_cmd += ["-t", str(sample_secs)]
            ffmpeg_cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(temp_wav)]
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True, timeout=300)
            result = subprocess.run(
                [
                    config.models.whisper_cpp_binary,
                    "-m", config.models.whisper_model_path,
                    "-f", str(temp_wav),
                    "--language", "auto", "-otxt",
                ],
                capture_output=True, text=True, timeout=1800,
            )
            return result.stdout.strip() or None
        except Exception as exc:
            logger.warning("Video-Transkription fehlgeschlagen für %s: %s", file_path.name, exc)
            return None
        finally:
            if temp_wav.exists():
                temp_wav.unlink()

    def _transcribe_python(self, file_path: Path, config) -> str | None:
        """Transkription via openai-whisper Python-Paket (kein externes Binary nötig)."""
        try:
            import whisper
            sample_secs = getattr(config.processing, "transcription_sample_seconds", 90)
            model_name = getattr(config.models, "whisper_python_model", "base")
            logger.info("Lade openai-whisper Modell '%s' (Sample: %ds) ...", model_name, sample_secs)
            model = whisper.load_model(model_name)
            kwargs: dict = {"language": None, "verbose": False}
            if sample_secs > 0:
                kwargs["clip_timestamps"] = f"0,{sample_secs}"
            result = model.transcribe(str(file_path), **kwargs)
            segments = result.get("segments", [])
            if sample_secs > 0:
                segments = [s for s in segments if s.get("start", 0) < sample_secs]
            text = " ".join(s["text"] for s in segments).strip() if segments else result.get("text", "").strip()
            return text or None
        except Exception as exc:
            logger.warning("Python-Whisper-Transkription fehlgeschlagen für %s: %s", file_path.name, exc)
            return None

    def _summarize(self, transcript: str, video_meta: dict, filename: str, config) -> str | None:
        """Erstellt eine kurze Inhaltszusammenfassung via Ollama für besseres Clustering."""
        try:
            from app.services.ollama_service import get_background_ollama_service
            svc = get_background_ollama_service()
            meta_hints = []
            for key in ("duration", "resolution", "fps"):
                if video_meta.get(key):
                    meta_hints.append(f"{key}: {video_meta[key]}")
            meta_str = ", ".join(meta_hints) if meta_hints else ""

            prompt = (
                f"Analysiere diesen Video-Inhalt und erstelle eine prägnante Zusammenfassung auf Deutsch "
                f"in 2-3 Sätzen. Beschreibe: Thema/Inhalt, Sprache/Ton, Zweck (Tutorial, Vortrag, Film, Meeting etc.)\n"
                f"Datei: {filename}\n"
                + (f"Metadaten: {meta_str}\n" if meta_str else "")
                + f"Transkript-Ausschnitt:\n{transcript[:1500]}"
            )
            summary = svc.generate(prompt)
            return summary.strip() or None
        except Exception as exc:
            logger.warning("Video-Zusammenfassung fehlgeschlagen für %s: %s", filename, exc)
            return None
