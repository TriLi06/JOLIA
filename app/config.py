from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False
    app_name: str = "JOLIA Docs"
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
    embedding_model: str = "bge-m3"
    embedding_backend: str = "ollama"                  # "sentence-transformers" | "ollama"
    embedding_device: str = "auto"                     # "auto" | "cpu" | "cuda" | "mps"
    embedding_ollama_model: str = "bge-m3"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    # Modell für langsame Hintergrundaufgaben wie Tags und Medienzusammenfassungen.
    background_ollama_model: str = "qwen2.5:7b"
    # Separates, langsameres Modell für Hintergrund-Kategorisierung.
    categorization_ollama_model: str = "qwen2.5:7b"
    ollama_timeout: float = 300.0                       # Sekunden; bei CPU-Betrieb ggf. erhöhen
    # Wie lange Ollama ein Modell nach der letzten Anfrage im (V)RAM behält, bevor es
    # selbstständig entladen wird (Ollama-Format, z.B. "10m", "0" = sofort entladen).
    # Chat-/Vision-/Embedding-Modelle werden dadurch NICHT beim Start, sondern erst bei
    # der ersten Anfrage geladen und nach Leerlauf automatisch wieder freigegeben.
    ollama_keep_alive: str = "10m"
    # Leerlaufzeit (Minuten) bevor lokal (im JOLIA-Prozess) geladene Modelle wie
    # SentenceTransformer/OpenCLIP/CLAP wieder aus dem Speicher entladen werden.
    # 0 oder negativ = sofort nach jeder Nutzung entladen.
    model_idle_unload_minutes: float = 10.0
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
    # CLAP audio similarity (huggingface transformers, Auto-Download beim ersten Gebrauch)
    clap_model: str = "laion/larger_clap_music"  # Alternative: "laion/clap-htsat-unfused" (generisches Audio)
    # Alternativer HuggingFace-Endpunkt falls huggingface.co nicht erreichbar ist,
    # z.B. "https://hf-mirror.com" (Mirror). Leer = offizieller huggingface.co.
    hf_endpoint: str = ""


class ProcessingConfig(BaseModel):
    chunk_size: int = 1000
    chunk_overlap: int = 150
    max_file_size_mb: int = 2000
    # Begrenzt, wie viele Dateien gleichzeitig verarbeitet werden (OCR/Embeddings/LLM).
    # Verhindert, dass bei vielen parallelen Jobs (z.B. große PDFs + Watcher-Batch) der
    # SQLAlchemy-Connection-Pool erschöpft wird (jeder Job hält während der gesamten
    # Verarbeitung eine eigene DB-Session offen).
    max_concurrent_processing: int = 3
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
    # Nach dem Import per KI passende Tags (Rechnung, Arzt, Urlaubsfoto, ...) vorschlagen und zuweisen.
    enable_tag_suggestion: bool = True
    # Nach dem Import per KI einen Kategorie-Breadcrumb-Pfad ermitteln und zuweisen (z.B. Dokumente > Rechnungen > Auto).
    enable_auto_categorization: bool = True
    ocr_languages: str = "deu+eng"
    ocr_confidence_threshold: int = 60
    video_thumbnail_offset_pct: int = 10
    # Fixer Frame-Offset in Sekunden für Thumbnail-Extraktion und Bildanalyse.
    # 0 = Prozentwert aus video_thumbnail_offset_pct verwenden.
    video_frame_offset_seconds: int = 10
    # Phase B: OpenCLIP image similarity embeddings
    enable_clip_embeddings: bool = True
    # CLAP audio similarity embeddings (requires transformers + librosa)
    enable_clap_embeddings: bool = True
    # Nur die ersten N Sekunden für das CLAP-Embedding nutzen (kurze Clips reichen aus)
    clap_max_audio_seconds: int = 30
    # Phase B: Face detection (requires face_recognition package)
    enable_face_detection: bool = True
    # Duplikat-/Serienerkennung (Bilder): pHash-Hammingdistanz-Schwelle und Zeitfenster
    duplicate_hash_threshold: int = 8
    duplicate_time_window_seconds: int = 120


class WatcherConfig(BaseModel):
    enabled: bool = False
    scan_interval_seconds: int = 60
    # Mindest-Ruhezeit einer Datei (in Sekunden) bevor sie importiert wird.
    # Verhindert, dass noch laufende Kopiervorgänge unterbrochen werden.
    stability_threshold_seconds: int = 30


class ScanConfig(BaseModel):
    """Mehrseitige Scans: Einzelbilder werden zu einem durchsuchbaren PDF gebündelt."""

    # Bündelung aktiv? Bei false werden Scan-Seiten wie normale Einzelbilder importiert.
    bundle_enabled: bool = True
    # Ohne Manifest: Wartezeit nach der letzten empfangenen Seite, bevor gebündelt wird.
    bundle_idle_seconds: int = 45
    bundle_max_pages: int = 100
    # Tesseract-Textlayer ins PDF einbetten (macht den Text markierbar/durchsuchbar).
    pdf_ocr: bool = True
    # DPI für die PDF-Seitengröße. 0 = automatisch aus der Bildgröße (Seite ≈ A4).
    pdf_dpi: int = 0
    pdf_jpeg_quality: int = 85
    # Pro Seite zusätzlich eine Ollama-Vision-Analyse (Bildinhalte, Handschrift) ausführen.
    vision_per_page: bool = True
    # Vision-OCR auch bei Scan-PDFs ausführen, deren temporäre Bundle-Bilder bereits gelöscht wurden.
    vision_ocr_scanned_pdfs: bool = True
    # Deckel für die Vision-Analyse; 0 = alle Seiten (auf CPU sehr langsam).
    vision_max_pages: int = 0
    # >0: Seitenbilder nach der Verarbeitung noch N Sekunden im temp_dir aufheben (Debug).
    keep_page_images_seconds: int = 0
    default_title_prefix: str = "Scan"


class ScheduledJobConfig(BaseModel):
    enabled: bool = True
    interval_seconds: int = 3600


class ScheduledJobsConfig(BaseModel):
    # Gesichter-/Standort-Clustering und Duplikaterkennung laufen als ein kombinierter Job
    # (siehe scheduler_service._run_rebuild_clustering), da alle drei ohnehin ueber den
    # kompletten Datenbestand neu rechnen.
    clustering: ScheduledJobConfig = ScheduledJobConfig(enabled=True, interval_seconds=3600)
    backup: ScheduledJobConfig = ScheduledJobConfig(enabled=True, interval_seconds=86400)


class Config(BaseModel):
    app: AppConfig = AppConfig()
    paths: PathsConfig
    models: ModelsConfig = ModelsConfig()
    processing: ProcessingConfig = ProcessingConfig()
    watcher: WatcherConfig = WatcherConfig()
    scan: ScanConfig = ScanConfig()
    scheduled_jobs: ScheduledJobsConfig = ScheduledJobsConfig()


_config: Optional[Config] = None


# ---------------------------------------------------------------------------
# Notfall-Schalter über Umgebungsvariablen
#
# Jede Variable überschreibt genau einen Wert aus der config.yaml. Damit lassen
# sich einzelne Features abschalten oder Grenzwerte anpassen, ohne die
# config.yaml zu ändern – im Docker-Betrieb also ohne Neubau des Images
# (Variable in .env setzen, danach `docker compose up -d`).
# Leere Werte gelten als "nicht gesetzt". Siehe README, Abschnitt
# "Notfall-Schalter".
# ---------------------------------------------------------------------------

def _env_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError("erwartet true oder false")


def _env_int(raw: str) -> int:
    return int(raw.strip())


def _env_float(raw: str) -> float:
    return float(raw.strip())


def _env_str(raw: str) -> str:
    return raw.strip()


_ENV_OVERRIDES: tuple[tuple[str, tuple[str, ...], Callable[[str], Any]], ...] = (
    # --- Pfade -------------------------------------------------------------
    ("INBOX_PATH", ("paths", "inbox"), _env_str),
    ("ARCHIVE_ROOT", ("paths", "archive_root"), _env_str),
    ("DATA_DIR", ("paths", "data_dir"), _env_str),
    ("TEMP_DIR", ("paths", "temp_dir"), _env_str),
    ("BACKUP_TARGET", ("paths", "backup_target"), _env_str),

    # --- Modelle -----------------------------------------------------------
    ("OLLAMA_BASE_URL", ("models", "ollama_base_url"), _env_str),
    ("OLLAMA_MODEL", ("models", "ollama_model"), _env_str),
    ("JOLIA_OLLAMA_TIMEOUT", ("models", "ollama_timeout"), _env_float),
    ("JOLIA_OLLAMA_KEEP_ALIVE", ("models", "ollama_keep_alive"), _env_str),
    ("JOLIA_MODEL_IDLE_UNLOAD_MINUTES", ("models", "model_idle_unload_minutes"), _env_float),
    # tiny | base | small | medium | large – kleiner = schneller auf der CPU
    ("JOLIA_WHISPER_MODEL", ("models", "whisper_python_model"), _env_str),
    # Mirror, falls huggingface.co nicht erreichbar ist (z.B. Firmennetz)
    ("JOLIA_HF_ENDPOINT", ("models", "hf_endpoint"), _env_str),

    # --- Feature-Schalter --------------------------------------------------
    ("JOLIA_ENABLE_OCR", ("processing", "enable_ocr"), _env_bool),
    ("JOLIA_ENABLE_IMAGE_OCR", ("processing", "enable_image_ocr"), _env_bool),
    ("JOLIA_ENABLE_AUDIO_TRANSCRIPTION", ("processing", "enable_audio_transcription"), _env_bool),
    ("JOLIA_ENABLE_VIDEO_TRANSCRIPTION", ("processing", "enable_video_transcription"), _env_bool),
    ("JOLIA_ENABLE_MEDIA_SUMMARIZATION", ("processing", "enable_media_summarization"), _env_bool),
    ("JOLIA_ENABLE_TAG_SUGGESTION", ("processing", "enable_tag_suggestion"), _env_bool),
    ("JOLIA_ENABLE_AUTO_CATEGORIZATION", ("processing", "enable_auto_categorization"), _env_bool),
    ("JOLIA_ENABLE_CLIP_EMBEDDINGS", ("processing", "enable_clip_embeddings"), _env_bool),
    ("JOLIA_ENABLE_CLAP_EMBEDDINGS", ("processing", "enable_clap_embeddings"), _env_bool),
    ("JOLIA_ENABLE_FACE_DETECTION", ("processing", "enable_face_detection"), _env_bool),

    # --- Leistung / Grenzwerte ---------------------------------------------
    ("JOLIA_MAX_CONCURRENT_PROCESSING", ("processing", "max_concurrent_processing"), _env_int),
    ("JOLIA_MAX_FILE_SIZE_MB", ("processing", "max_file_size_mb"), _env_int),
    ("JOLIA_TRANSCRIPTION_SAMPLE_SECONDS", ("processing", "transcription_sample_seconds"), _env_int),
    ("JOLIA_OCR_LANGUAGES", ("processing", "ocr_languages"), _env_str),

    # --- Automatischer Import ----------------------------------------------
    ("JOLIA_WATCHER_ENABLED", ("watcher", "enabled"), _env_bool),
    ("JOLIA_WATCHER_INTERVAL_SECONDS", ("watcher", "scan_interval_seconds"), _env_int),

    # --- Mehrseitige Scans -------------------------------------------------
    ("JOLIA_SCAN_BUNDLE_ENABLED", ("scan", "bundle_enabled"), _env_bool),
    ("JOLIA_SCAN_BUNDLE_IDLE_SECONDS", ("scan", "bundle_idle_seconds"), _env_int),
    ("JOLIA_SCAN_PDF_OCR", ("scan", "pdf_ocr"), _env_bool),
    ("JOLIA_SCAN_VISION_PER_PAGE", ("scan", "vision_per_page"), _env_bool),
    ("JOLIA_SCAN_VISION_MAX_PAGES", ("scan", "vision_max_pages"), _env_int),

    # --- Geplante Hintergrundjobs ------------------------------------------
    ("JOLIA_CLUSTERING_ENABLED", ("scheduled_jobs", "clustering", "enabled"), _env_bool),
    ("JOLIA_BACKUP_ENABLED", ("scheduled_jobs", "backup", "enabled"), _env_bool),
    ("JOLIA_BACKUP_INTERVAL_SECONDS", ("scheduled_jobs", "backup", "interval_seconds"), _env_int),

    # --- Zugriffsschutz ----------------------------------------------------
    ("JOLIA_AUTH_ENABLED", ("app", "auth_enabled"), _env_bool),
    ("JOLIA_AUTH_USERNAME", ("app", "auth_username"), _env_str),
    ("JOLIA_AUTH_PASSWORD_HASH", ("app", "auth_password_hash"), _env_str),
    ("JOLIA_AUTH_SESSION_SECRET", ("app", "auth_session_secret"), _env_str),

    # --- Diagnose ----------------------------------------------------------
    ("DEBUG", ("app", "debug"), _env_bool),
)


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

    # HF_ENDPOINT so früh wie möglich setzen – bevor irgendein huggingface_hub/
    # transformers/sentence-transformers-Import stattfindet, da die Ziel-URL beim
    # Import als Konstante eingefroren wird.
    if _config.models.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", _config.models.hf_endpoint)

    return _config


def _apply_env_overrides(data: dict) -> None:
    """Wendet die in _ENV_OVERRIDES definierten Umgebungsvariablen an."""
    for env_var, keys, parse in _ENV_OVERRIDES:
        raw = os.getenv(env_var)
        if raw is None or not raw.strip():
            continue
        try:
            value = parse(raw)
        except ValueError as exc:
            # Nicht abbrechen: ein Tippfehler in .env darf den Start nicht verhindern.
            logger.warning(
                "Umgebungsvariable %s=%r wird ignoriert (%s).", env_var, raw, exc
            )
            continue

        section = data
        for key in keys[:-1]:
            child = section.get(key)
            if not isinstance(child, dict):
                child = {}
                section[key] = child
            section = child
        section[keys[-1]] = value


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config
