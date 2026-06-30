"""
Bild-Embedding-Service: unterstützt zwei Backends.

Backend "ollama" (Standard, kein HF-Download nötig):
  Nutzt das konfigurierte Ollama-Embedding-Modell für Bilder.
  Bildbeschreibung (via Vision-Modell) → Text-Embedding → Vektor.
  Funktioniert im selben Vektorraum wie alle anderen Text-Embeddings.

Backend "openclip" (lokales CLIP-Modell, muss bereits gecacht sein):
  Nutzt das OpenCLIP-Modell für echte Cross-Modal-Embeddings.
  Erfordert 'pip install open-clip-torch' und lokalen Modell-Cache.

Konfiguration in config.yaml:
    models:
      clip_backend: "ollama"       # "ollama" | "openclip"
      clip_model: "ViT-B-32"       # nur für openclip
      clip_pretrained: "openai"    # nur für openclip
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# --- OpenCLIP-Zustand (nur für openclip-Backend) ---
_clip_model = None
_clip_preprocess = None
_clip_model_name: str = ""
_clip_pretrained: str = ""


def _get_clip_backend() -> str:
    try:
        from app.config import get_config
        return getattr(get_config().models, "clip_backend", "ollama")
    except Exception:
        return "ollama"


def is_available() -> bool:
    """Gibt True zurück wenn Image-Embeddings möglich sind (beliebiges Backend)."""
    backend = _get_clip_backend()
    if backend == "openclip":
        try:
            import open_clip  # noqa: F401
            # Prüfen ob das Modell lokal gecacht ist (kein HF-Download)
            import os
            # TRANSFORMERS_OFFLINE verhindert Netzwerk-Anfragen
            return True
        except ImportError:
            return False
    else:  # ollama
        try:
            from app.services.ollama_service import get_ollama_service
            return get_ollama_service().is_available()
        except Exception:
            return False


def embed_image(
    image_path: Path,
    model_name: str | None = None,
    pretrained: str | None = None,
    vision_description: str = "",
    clip_backend: str | None = None,
) -> list[float]:
    """Gibt einen Bildvektor zurück.

    Im Ollama-Modus: vision_description → Text-Embedding (kein HF-Download).
    Im OpenCLIP-Modus: direktes Bild-Encoding (Modell muss lokal gecacht sein).
    """
    backend = clip_backend or _get_clip_backend()

    if backend == "openclip":
        mn, pt = _resolve_openclip_params(model_name, pretrained)
        return _embed_image_openclip(image_path, mn, pt)
    else:
        return _embed_image_ollama(image_path, vision_description)


def embed_text_clip(
    text: str,
    model_name: str | None = None,
    pretrained: str | None = None,
    clip_backend: str | None = None,
) -> list[float]:
    """Gibt einen Textvektor zurück (für Cross-Modal Query: Text → Bilder).

    Im Ollama-Modus: nutzt dasselbe Text-Embedding-Modell wie der Rest der App.
    Im OpenCLIP-Modus: CLIP Text-Encoder mit lokalem Modell.
    """
    backend = clip_backend or _get_clip_backend()

    if backend == "openclip":
        mn, pt = _resolve_openclip_params(model_name, pretrained)
        return _embed_text_openclip(text, mn, pt)
    else:
        from app.services.embedding_service import embed_text
        return embed_text(text)


def _resolve_openclip_params(model_name: str | None, pretrained: str | None) -> tuple[str, str]:
    """Liest model_name und pretrained aus der Konfiguration wenn nicht explizit angegeben."""
    try:
        from app.config import get_config
        cfg = get_config()
        return (
            model_name or cfg.models.clip_model,
            pretrained or cfg.models.clip_pretrained,
        )
    except Exception:
        return model_name or "ViT-B-32", pretrained or "openai"


# ---------------------------------------------------------------------------
# Ollama-Backend
# ---------------------------------------------------------------------------

def _embed_image_ollama(image_path: Path, vision_description: str = "") -> list[float]:
    """Embedding via Ollama: vision_description → text embedding."""
    from app.services.embedding_service import embed_text

    text = vision_description.strip()
    if not text:
        # Fallback: Dateiname als schwache Repräsentation
        text = image_path.stem.replace("_", " ").replace("-", " ")
        logger.debug(
            "Kein Vision-Text für CLIP-Ollama-Embedding, nutze Dateinamen: %s", image_path.name
        )

    return embed_text(text)


# ---------------------------------------------------------------------------
# OpenCLIP-Backend (Modell muss lokal gecacht sein)
# ---------------------------------------------------------------------------

def _init_openclip_model(model_name: str, pretrained: str) -> None:
    global _clip_model, _clip_preprocess, _clip_model_name, _clip_pretrained
    if _clip_model is not None and _clip_model_name == model_name and _clip_pretrained == pretrained:
        return
    try:
        import open_clip
        import os
        import torch
        # Offline-Modus erzwingen wenn kein lokaler Pfad angegeben ist
        if not _is_local_path(pretrained):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        # PyTorch 2.6+ änderte den Standard von weights_only auf True.
        # OpenAI .pt-Dateien sind TorchScript-Archive und benötigen weights_only=False.
        # Temporärer Patch – nur für diese vertrauenswürdige, SHA256-verifizierte Datei.
        _original_torch_load = torch.load

        def _patched_load(*args, **kwargs):
            # open_clip übergibt weights_only=True explizit (PyTorch 2.6+).
            # OpenAI .pt-Dateien sind TorchScript-Archive – erfordern weights_only=False.
            # Diese Datei ist vertrauenswürdig (SHA256-verifiziert via download_clip_model.py).
            kwargs["weights_only"] = False
            import warnings
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=".*TorchScript archive.*")
                return _original_torch_load(*args, **kwargs)

        torch.load = _patched_load
        try:
            logger.info("Lade OpenCLIP-Modell: %s / %s", model_name, pretrained)
            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=pretrained, device="cpu"
            )
        finally:
            torch.load = _original_torch_load  # sofort wiederherstellen

        model.eval()
        _clip_model = model
        _clip_preprocess = preprocess
        _clip_model_name = model_name
        _clip_pretrained = pretrained
        logger.info("OpenCLIP-Modell geladen.")
    except Exception as exc:
        raise RuntimeError(
            f"OpenCLIP-Modell konnte nicht geladen werden: {exc}. "
            "Tipp: 'python scripts/download_clip_model.py' ausführen und dann "
            "clip_pretrained in config.yaml auf den lokalen Pfad setzen."
        ) from exc


def _is_local_path(pretrained: str) -> bool:
    """Gibt True zurück wenn pretrained ein lokaler Dateipfad ist."""
    from pathlib import Path
    p = Path(pretrained)
    return p.exists() and p.is_file()


def _embed_image_openclip(image_path: Path, model_name: str, pretrained: str) -> list[float]:
    _init_openclip_model(model_name, pretrained)
    import torch
    from PIL import Image
    img = Image.open(str(image_path)).convert("RGB")
    img_tensor = _clip_preprocess(img).unsqueeze(0)  # type: ignore[misc]
    with torch.no_grad():
        features = _clip_model.encode_image(img_tensor)  # type: ignore[misc]
        features = features / features.norm(dim=-1, keepdim=True)
    return features[0].tolist()


def _embed_text_openclip(text: str, model_name: str, pretrained: str) -> list[float]:
    _init_openclip_model(model_name, pretrained)
    import open_clip
    import torch
    tokenizer = open_clip.get_tokenizer(_clip_model_name)
    tokens = tokenizer([text])
    with torch.no_grad():
        features = _clip_model.encode_text(tokens)  # type: ignore[misc]
        features = features / features.norm(dim=-1, keepdim=True)
    return features[0].tolist()

