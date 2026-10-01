from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services import model_lifecycle

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model: "SentenceTransformer | None" = None
_model_name: str = ""

_LIFECYCLE_NAME = "embedding_model"


def _unload_embedding_model() -> None:
    global _model, _model_name
    _model = None
    _model_name = ""
    model_lifecycle.gc_cleanup()


model_lifecycle.register(_LIFECYCLE_NAME, _unload_embedding_model)


def _idle_unload_minutes() -> float:
    try:
        from app.config import get_config
        return get_config().models.model_idle_unload_minutes
    except Exception:
        return 10.0


def init_embedding_model(model_name: str, device: str = "auto") -> None:
    global _model, _model_name
    if _model is None or _model_name != model_name:
        resolved_device = _resolve_device(device)
        logger.info("Lade Embedding-Modell: %s (device=%s)", model_name, resolved_device)
        from sentence_transformers import SentenceTransformer
        # local_files_only=True: kein HF-Download – Modell muss im Cache vorliegen.
        # Erstmaliger Download: 'huggingface-cli download <model>' oder temporär auf False setzen.
        _model = SentenceTransformer(model_name, device=resolved_device, local_files_only=True)
        _model_name = model_name
        logger.info("Embedding-Modell geladen (device=%s).", resolved_device)


def _resolve_device(device: str) -> str:
    """Löst 'auto' zu 'cuda', 'mps' oder 'cpu' auf."""
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():  # type: ignore[attr-defined]
            return "mps"
    except Exception:
        pass
    return "cpu"


def embed_texts(texts: list[str]) -> list[list[float]]:
    from app.config import get_config
    cfg = get_config()

    if cfg.models.embedding_backend == "ollama":
        return _embed_via_ollama(texts, cfg.models.embedding_ollama_model)

    # sentence-transformers Backend
    global _model
    if _model is None:
        init_embedding_model(cfg.models.embedding_model, cfg.models.embedding_device)
    assert _model is not None
    vectors = _model.encode(texts, batch_size=32, show_progress_bar=False)
    model_lifecycle.touch(_LIFECYCLE_NAME, _idle_unload_minutes())
    return [v.tolist() for v in vectors]


def _embed_via_ollama(texts: list[str], model: str) -> list[list[float]]:
    from app.services.ollama_service import get_ollama_service
    svc = get_ollama_service()
    return svc.embed(texts, model)


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]
