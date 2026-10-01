from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.processors.base_processor import BaseProcessor, ProcessingResult
from app.services import sidecar_service
from app.services.chunking_service import split_text

logger = logging.getLogger(__name__)


class AudioProcessor(BaseProcessor):
    processor_version = "1.0"

    def process(self, file_path: Path, file_record, config) -> ProcessingResult:
        audio_meta = self._extract_metadata(file_path)
        transcript: str | None = None
        summary: str | None = None

        if config.processing.enable_audio_transcription:
            transcript = self._transcribe(file_path, config)

        # Kurze Inhaltszusammenfassung via Ollama (bevorzugt für Clustering/Suche)
        if transcript and getattr(config.processing, "enable_media_summarization", True):
            summary = self._summarize(transcript, audio_meta, file_record.original_filename, config)

        # Suchtext aufbauen – Zusammenfassung hat Vorrang vor rohem Transkript
        search_parts = [f"Dateiname: {file_record.original_filename}"]
        for key in ("title", "artist", "album", "year", "genre"):
            if audio_meta.get(key):
                search_parts.append(f"{key.capitalize()}: {audio_meta[key]}")
        if summary:
            search_parts.append(f"Inhalt: {summary}")
        elif transcript:
            search_parts.append(f"Transkript (Ausschnitt): {transcript}")

        search_text = "\n".join(search_parts)

        metadata = {
            "Dateigröße": f"{file_record.file_size or 0:,} Bytes",
            "SHA256": file_record.sha256,
        }
        metadata.update({k: str(v) for k, v in audio_meta.items()})

        json_data = {
            "file_id": file_record.id,
            "original_filename": file_record.original_filename,
            "sha256": file_record.sha256,
            "mime_type": file_record.mime_type,
            "content_type": "audio",
            "file_size": file_record.file_size,
            "processor": "AudioProcessor",
            "processor_version": self.processor_version,
            "audio_metadata": audio_meta,
            "transcript_sample": transcript,
            "summary": summary,
        }
        json_path = sidecar_service.write_json_sidecar(file_path, json_data)
        md_content = sidecar_service.build_audio_md(
            file_record.original_filename, audio_meta, summary or transcript
        )
        md_path = sidecar_service.write_md_sidecar(file_path, md_content)

        chunks = split_text(
            search_text,
            chunk_size=config.processing.chunk_size,
            overlap=config.processing.chunk_overlap,
        )
        for c in chunks:
            c.chunk_type = "description" if summary else ("transcript" if transcript else "description")

        if getattr(config.processing, "enable_clap_embeddings", False):
            self._store_clap_embedding(file_path, file_record, config, audio_meta, search_text)

        return ProcessingResult(
            success=True,
            chunks=chunks,
            metadata=metadata,
            sidecar_json_path=str(json_path),
            sidecar_md_path=str(md_path),
        )

    def _store_clap_embedding(self, file_path: Path, file_record, config, audio_meta: dict, text_repr: str) -> None:
        """Berechnet einen CLAP-Audiovektor und speichert ihn in ChromaDB für
        Musik-Ähnlichkeitssuche und Text→Musik-Suche im Chat."""
        try:
            from app.services import chroma_service
            from app.services.clap_service import embed_audio
            clap_vec = embed_audio(
                file_path,
                model_name=config.models.clap_model,
                max_seconds=getattr(config.processing, "clap_max_audio_seconds", 30),
            )
            chroma_service.upsert_chunks(
                collection_name="audio_embeddings",
                ids=[f"clap_{file_record.id}"],
                texts=[text_repr],
                embeddings=[clap_vec],
                metadatas=[{
                    "file_id": file_record.id,
                    "source_path": file_record.archive_path,
                    "file_name": file_record.original_filename,
                    "content_type": "audio",
                    "artist": audio_meta.get("artist", ""),
                    "title": audio_meta.get("title", ""),
                    "genre": audio_meta.get("genre", ""),
                }],
            )
            logger.info("CLAP-Embedding gespeichert für %s", file_record.original_filename)
        except Exception as exc:
            logger.warning("CLAP-Embedding fehlgeschlagen für %s: %s", file_record.original_filename, exc)

    def _extract_metadata(self, file_path: Path) -> dict:
        try:
            from mutagen import File as MutagenFile

            mf = MutagenFile(str(file_path), easy=True)
            if mf is None:
                return {}

            meta: dict = {}
            tag_map = {
                "title": "title",
                "artist": "artist",
                "album": "album",
                "date": "year",
                "genre": "genre",
                "tracknumber": "track",
            }
            for mutagen_key, our_key in tag_map.items():
                val = mf.get(mutagen_key)
                if val:
                    meta[our_key] = val[0] if isinstance(val, list) else str(val)

            if hasattr(mf, "info"):
                info = mf.info
                if hasattr(info, "length"):
                    secs = int(info.length)
                    meta["duration"] = f"{secs // 60}:{secs % 60:02d}"
                if hasattr(info, "bitrate"):
                    meta["bitrate"] = f"{info.bitrate} kbps"

            return meta
        except Exception as exc:
            logger.warning("Mutagen-Fehler für %s: %s", file_path.name, exc)
            return {}

    def _transcribe(self, file_path: Path, config) -> str | None:
        # Backend 1: whisper.cpp (externes Binary)
        if config.models.whisper_cpp_binary:
            return self._transcribe_cpp(file_path, config)
        # Backend 2: openai-whisper (Python-Paket)
        try:
            import whisper as _whisper_check  # noqa: F401
            return self._transcribe_python(file_path, config)
        except ImportError:
            logger.warning(
                "Transkription übersprungen: weder whisper_cpp_binary konfiguriert "
                "noch 'openai-whisper' installiert ('pip install openai-whisper')."
            )
            return None

    def _transcribe_cpp(self, file_path: Path, config) -> str | None:
        temp_wav = file_path.parent / (file_path.stem + "_temp.wav")
        sample_secs = getattr(config.processing, "transcription_sample_seconds", 90)
        try:
            ffmpeg_cmd = [
                config.models.ffmpeg_binary,
                "-y", "-i", str(file_path),
            ]
            if sample_secs > 0:
                ffmpeg_cmd += ["-t", str(sample_secs)]
            ffmpeg_cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(temp_wav)]
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
            result = subprocess.run(
                [
                    config.models.whisper_cpp_binary,
                    "-m", config.models.whisper_model_path,
                    "-f", str(temp_wav),
                    "--language", "auto",
                    "-otxt",
                ],
                capture_output=True, text=True, timeout=600,
            )
            return result.stdout.strip() or None
        except subprocess.TimeoutExpired:
            logger.error("Whisper-Transkription Timeout für %s", file_path.name)
            return None
        except Exception as exc:
            logger.warning("Transkription fehlgeschlagen für %s: %s", file_path.name, exc)
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

    def _summarize(self, transcript: str, audio_meta: dict, filename: str, config) -> str | None:
        """Erstellt eine kurze Inhaltszusammenfassung via Ollama für besseres Clustering."""
        try:
            from app.services.ollama_service import get_background_ollama_service
            svc = get_background_ollama_service()
            meta_hints = []
            for key in ("title", "artist", "album", "genre", "duration"):
                if audio_meta.get(key):
                    meta_hints.append(f"{key}: {audio_meta[key]}")
            meta_str = ", ".join(meta_hints) if meta_hints else ""

            prompt = (
                f"Analysiere diesen Audio-Inhalt und erstelle eine prägnante Zusammenfassung auf Deutsch "
                f"in 2-3 Sätzen. Beschreibe: Thema/Inhalt, Sprache/Ton, Zweck (Musik, Podcast, Gespräch, Vortrag etc.)\n"
                f"Datei: {filename}\n"
                + (f"Metadaten: {meta_str}\n" if meta_str else "")
                + f"Transkript-Ausschnitt:\n{transcript[:1500]}"
            )
            summary = svc.generate(prompt)
            return summary.strip() or None
        except Exception as exc:
            logger.warning("Audio-Zusammenfassung fehlgeschlagen für %s: %s", filename, exc)
            return None
