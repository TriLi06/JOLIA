from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    app_name: str = "DocStoreAI"
    # Phase E: Authentifizierung
    auth_enabled: bool = False
    auth_username: str = "admin"
    # SHA256-Hash des Passworts (echo -n 'password' | sha256sum)
    # Leer = kein Passwort-Check (nur Benutzername)
    auth_password_hash: str = ""
    auth_session_secret: str = "change-me-in-production"


class PathsConfig(BaseModel):
    inbox: Path
    archive_root: Path
    data_dir: Path
    temp_dir: Path
    backup_target: Path


class ModelsConfig(BaseModel):
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_backend: str = "sentence-transformers"   # "sentence-transformers" | "ollama"
    embedding_device: str = "auto"                     # "auto" | "cpu" | "cuda" | "mps"
    embedding_ollama_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: float = 300.0                       # Sekunden; bei CPU-Betrieb ggf. erhöhen
    vision_backend: str = "tesseract"               # "tesseract" | "ollama"
    vision_ollama_model: str = "minicpm-v"  # CPU-Empfehlung: "minicpm-v" (starke OCR/Beschreibung). Alt.: "llava:7b", "qwen2.5vl:7b", "llama3.2-vision:11b"
    vision_ollama_timeout: float = 900.0             # Sekunden pro Bild; auf reiner CPU großzügig wählen
    whisper_cpp_binary: str = ""
    whisper_model_path: str = ""
    whisper_python_model: str = "base"            # openai-whisper Modellgröße: tiny | base | small | medium | large
    ffmpeg_binary: str = "ffmpeg"
    # Phase B: OpenCLIP image similarity
    clip_backend: str = "ollama"   # "ollama" (kein HF-Download) | "openclip" (lokal gecachtes Modell)
    clip_model: str = "ViT-B-32"
    clip_pretrained: str = "openai"


class ProcessingConfig(BaseModel):
    chunk_size: int = 1000
    chunk_overlap: int = 150
    max_file_size_mb: int = 2000
    enable_ocr: bool = True
    enable_audio_transcription: bool = True
    enable_video_transcription: bool = True
    # Nur die ersten N Sekunden transkribieren (0 = gesamte Datei).
    # 60-90s reichen für eine aussagekräftige Zusammenfassung und sind deutlich schneller.
    transcription_sample_seconds: int = 90
    # Nach der Transkription eine kurze Inhaltszusammenfassung via Ollama erstellen.
    # Diese wird für den Suchindex genutzt – besser für Clustering als rohes Transkript.
    enable_media_summarization: bool = True
    enable_image_ocr: bool = True
    ocr_languages: str = "deu+eng"
    ocr_confidence_threshold: int = 60
    video_thumbnail_offset_pct: int = 10
    # Fixer Frame-Offset in Sekunden für Thumbnail-Extraktion und Bildanalyse.
    # 0 = Prozentwert aus video_thumbnail_offset_pct verwenden.
    video_frame_offset_seconds: int = 10
    # Phase B: OpenCLIP image similarity embeddings
    enable_clip_embeddings: bool = True
    # Phase B: Face detection (requires face_recognition package)
    enable_face_detection: bool = True


class WatcherConfig(BaseModel):
    enabled: bool = False
    scan_interval_seconds: int = 60
    # Mindest-Ruhezeit einer Datei (in Sekunden) bevor sie importiert wird.
    # Verhindert, dass noch laufende Kopiervorgänge unterbrochen werden.
    stability_threshold_seconds: int = 30


class Config(BaseModel):
    app: AppConfig = AppConfig()
    paths: PathsConfig
    models: ModelsConfig = ModelsConfig()
    processing: ProcessingConfig = ProcessingConfig()
    watcher: WatcherConfig = WatcherConfig()


_config: Optional[Config] = None


def load_config(config_path: Path = Path("config.yaml")) -> Config:
    global _config

    if not config_path.exists():
        raise FileNotFoundError(
            f"Konfigurationsdatei nicht gefunden: {config_path}. "
            "Bitte config.example.yaml nach config.yaml kopieren und anpassen."
        )

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # .env-Werte überschreiben yaml-Werte
    _apply_env_overrides(data)

    _config = Config(**data)
    return _config


def _apply_env_overrides(data: dict) -> None:
    env_map = {
        ("paths", "inbox"): "INBOX_PATH",
        ("paths", "archive_root"): "ARCHIVE_ROOT",
        ("paths", "data_dir"): "DATA_DIR",
        ("paths", "temp_dir"): "TEMP_DIR",
        ("paths", "backup_target"): "BACKUP_TARGET",
        ("models", "ollama_base_url"): "OLLAMA_BASE_URL",
        ("models", "ollama_model"): "OLLAMA_MODEL",
    }
    for (section, key), env_var in env_map.items():
        value = os.getenv(env_var)
        if value:
            data.setdefault(section, {})[key] = value

    debug_val = os.getenv("DEBUG")
    if debug_val is not None:
        data.setdefault("app", {})["debug"] = debug_val.lower() == "true"


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
