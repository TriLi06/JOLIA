"""
Audio-Embedding-Service via CLAP (Contrastive Language-Audio Pretraining).

Nutzt HuggingFace `transformers` (ClapModel/ClapProcessor). Das Modell wird
beim ersten Gebrauch automatisch von HuggingFace Hub heruntergeladen und
danach lokal gecacht (kein manuelles Setup-Skript nötig, analog zu Ollama).

Ermöglicht:
  - Musik-/Audio-Ähnlichkeitssuche (Audio → Audio)
  - Text→Audio-Suche im Chat ("rock song with female vocals")
  - Clustering-Basis (gleicher Vektorraum für Audio und Text)

Konfiguration in config.yaml:
    models:
      clap_model: "laion/larger_clap_music"   # musikoptimiert; Alternative: "laion/clap-htsat-unfused"
    processing:
      enable_clap_embeddings: true
      clap_max_audio_seconds: 30
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.services import model_lifecycle

logger = logging.getLogger(__name__)

CLAP_SAMPLE_RATE = 48000  # von CLAP fest vorgegeben

_clap_model = None
_clap_processor = None
_clap_model_name: str = ""

_LIFECYCLE_NAME = "clap_model"


def _unload_clap_model() -> None:
    global _clap_model, _clap_processor, _clap_model_name
    _clap_model = None
    _clap_processor = None
    _clap_model_name = ""
    model_lifecycle.gc_cleanup()


model_lifecycle.register(_LIFECYCLE_NAME, _unload_clap_model)


def _idle_unload_minutes() -> float:
    try:
        from app.config import get_config
        return get_config().models.model_idle_unload_minutes
    except Exception:
        return 10.0


def _get_clap_model_name() -> str:
    try:
        from app.config import get_config
        return get_config().models.clap_model
    except Exception:
        return "laion/larger_clap_music"


def is_available() -> bool:
    """Gibt True zurück wenn Audio-Embeddings via CLAP möglich sind."""
    try:
        import transformers  # noqa: F401
        import librosa  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _init_clap_model(model_name: str) -> None:
    global _clap_model, _clap_processor, _clap_model_name
    if _clap_model is not None and _clap_model_name == model_name:
        return
    try:
        from transformers import ClapModel, ClapProcessor
        logger.info("Lade CLAP-Modell: %s (Download beim ersten Aufruf, danach gecacht) ...", model_name)
        model = ClapModel.from_pretrained(model_name)
        processor = ClapProcessor.from_pretrained(model_name)
        model.eval()
        _clap_model = model
        _clap_processor = processor
        _clap_model_name = model_name
        logger.info("CLAP-Modell geladen.")
    except Exception as exc:
        raise RuntimeError(
            f"CLAP-Modell '{model_name}' konnte nicht geladen werden: {exc}. "
            "Tipp: 'pip install transformers librosa' installieren."
        ) from exc


def embed_audio(
    audio_path: Path,
    model_name: str | None = None,
    max_seconds: int | None = None,
) -> list[float]:
    """Gibt einen Audiovektor für die gegebene Datei zurück."""
    import torch
    import librosa

    mn = model_name or _get_clap_model_name()
    _init_clap_model(mn)

    duration = max_seconds if max_seconds and max_seconds > 0 else None
    audio_data, _ = librosa.load(str(audio_path), sr=CLAP_SAMPLE_RATE, mono=True, duration=duration)

    inputs = _clap_processor(audios=audio_data, sampling_rate=CLAP_SAMPLE_RATE, return_tensors="pt")
    with torch.no_grad():
        features = _clap_model.get_audio_features(**inputs)  # type: ignore[union-attr]
        features = features / features.norm(dim=-1, keepdim=True)
    model_lifecycle.touch(_LIFECYCLE_NAME, _idle_unload_minutes())
    return features[0].tolist()


def embed_text_clap(text: str, model_name: str | None = None) -> list[float]:
    """Gibt einen Textvektor im selben Vektorraum wie embed_audio() zurück."""
    import torch

    mn = model_name or _get_clap_model_name()
    _init_clap_model(mn)

    inputs = _clap_processor(text=[text], return_tensors="pt", padding=True)  # type: ignore[union-attr]
    with torch.no_grad():
        features = _clap_model.get_text_features(**inputs)  # type: ignore[union-attr]
        features = features / features.norm(dim=-1, keepdim=True)
    model_lifecycle.touch(_LIFECYCLE_NAME, _idle_unload_minutes())
    return features[0].tolist()
