from __future__ import annotations

import logging
import time
from io import BytesIO

import httpx

from app.services.ai_inference_lock import inference_lock

logger = logging.getLogger(__name__)

_POST_ATTEMPTS = 3
_RETRY_DELAYS = (0.5, 1.0)
_VISION_CONTEXT_SIZES = (8192, 12288, 16384)


class OllamaService:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0, keep_alive: str = "10m"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # Wie lange Ollama das Modell nach dieser Anfrage im (V)RAM hält, bevor es selbst
        # entlädt (Ollama-natives Feature) - so bleibt der Chat/Vision-LLM nicht dauerhaft
        # geladen, sondern nur waehrend tatsaechlicher Nutzung plus kurzer Nachlaufzeit.
        self.keep_alive = keep_alive

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def _post(self, url: str, payload: dict, timeout: float | None = None) -> httpx.Response:
        request_timeout = self.timeout if timeout is None else timeout
        for attempt in range(_POST_ATTEMPTS):
            try:
                response = httpx.post(url, json=payload, timeout=request_timeout)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt == _POST_ATTEMPTS - 1:
                    raise
                delay = _RETRY_DELAYS[attempt]
                logger.warning(
                    "Ollama unter %s nicht erreichbar; neuer Versuch in %.1fs (%d/%d).",
                    self.base_url,
                    delay,
                    attempt + 1,
                    _POST_ATTEMPTS,
                )
                time.sleep(delay)
                continue

            if response.status_code not in (502, 503, 504) or attempt == _POST_ATTEMPTS - 1:
                return response

            delay = _RETRY_DELAYS[attempt]
            logger.warning(
                "Ollama antwortet mit HTTP %s; neuer Versuch in %.1fs (%d/%d).",
                response.status_code,
                delay,
                attempt + 1,
                _POST_ATTEMPTS,
            )
            time.sleep(delay)

        raise RuntimeError("Ollama-Anfrage endete unerwartet ohne Antwort.")

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            if detail:
                detail = detail[:1000]
                logger.error("Ollama HTTP-Fehler %s: %s", response.status_code, detail)
                raise httpx.HTTPStatusError(
                    f"{exc} — Ollama: {detail}",
                    request=exc.request,
                    response=response,
                ) from exc
            raise

    @staticmethod
    def _is_context_overflow(response: httpx.Response) -> bool:
        if response.status_code != 400:
            return False
        error_text = response.text.lower()
        return any(
            marker in error_text
            for marker in (
                "exceed_context_size_error",
                "exceeds the available context size",
                "context length exceeded",
                "input length exceeds",
            )
        )

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        response_format: str | dict | None = None,
    ) -> str:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        if system:
            payload["system"] = system
        if response_format:
            payload["format"] = response_format

        url = f"{self.base_url}/api/generate"
        logger.debug(
            "Ollama generate() → URL: %s | Modell: %s | Timeout: %ss | "
            "Prompt-Länge: %d Zeichen | System-Prompt: %s",
            url,
            self.model,
            self.timeout,
            len(prompt),
            "ja" if system else "nein",
        )

        try:
            with inference_lock:
                r = self._post(url, payload)
            logger.debug(
                "Ollama Antwort erhalten → HTTP %s | Antwort-Länge: %d Zeichen",
                r.status_code,
                len(r.text),
            )
            self._raise_for_status(r)
            return r.json().get("response", "")
        except httpx.TimeoutException:
            logger.error(
                "Ollama-Timeout nach %ss – Modell: %s, URL: %s",
                self.timeout, self.model, url,
            )
            raise

    def list_models(self) -> list[str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=10.0)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        """Erzeugt Embeddings via Ollama /api/embed (Batch)."""
        with inference_lock:
            try:
                r = self._post(
                    f"{self.base_url}/api/embed",
                    {"model": model, "input": texts, "keep_alive": self.keep_alive},
                )
                self._raise_for_status(r)
                return r.json()["embeddings"]
            except httpx.HTTPStatusError as exc:
                # Fallback: einzeln über /api/embeddings (ältere Ollama-Versionen)
                unsupported_endpoint = exc.response.status_code == 405 or (
                    exc.response.status_code == 404
                    and "page not found" in exc.response.text.lower()
                )
                if not unsupported_endpoint:
                    raise
                results = []
                for text in texts:
                    r = self._post(
                        f"{self.base_url}/api/embeddings",
                        {"model": model, "prompt": text, "keep_alive": self.keep_alive},
                    )
                    self._raise_for_status(r)
                    results.append(r.json()["embedding"])
                return results

    def describe_image(self, image_path: str, model: str, prompt: str | None = None) -> str:
        """Analysiert ein Bild mit einem Multimodal-Modell (z.B. llava, moondream).
        Gibt eine Beschreibung inkl. erkanntem Text zurück."""
        import base64

        from PIL import Image, ImageOps

        if image_path.lower().endswith((".heic", ".heif")):
            from pillow_heif import register_heif_opener

            register_heif_opener()

        image_buffer = BytesIO()
        with Image.open(image_path) as source_image:
            image = ImageOps.exif_transpose(source_image)
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                image = Image.alpha_composite(background, rgba)
            image.convert("RGB").save(image_buffer, format="JPEG", quality=95)
        image_b64 = base64.b64encode(image_buffer.getvalue()).decode("ascii")

        if prompt is None:
            prompt = (
                "Analysiere dieses Bild detailliert auf Deutsch. "
                "1. Beschreibe den Inhalt des Bildes. "
                "2. Extrahiere und transkribiere ALLEN sichtbaren Text exakt so wie er im Bild steht. "
                "Trenne Beschreibung und extrahierten Text mit '--- TEXT ---'."
            )

        options: dict[str, float | int] = {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": 2048,
            "num_ctx": _VISION_CONTEXT_SIZES[0],
        }
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "options": options,
            "keep_alive": self.keep_alive,
        }
        url = f"{self.base_url}/api/generate"
        with inference_lock:
            for index, context_size in enumerate(_VISION_CONTEXT_SIZES):
                options["num_ctx"] = context_size
                r = self._post(url, payload, timeout=self.timeout)
                if self._is_context_overflow(r) and index < len(_VISION_CONTEXT_SIZES) - 1:
                    next_context_size = _VISION_CONTEXT_SIZES[index + 1]
                    logger.warning(
                        "Ollama-Vision-Kontext zu klein (Modell %s, num_ctx=%d); "
                        "wiederhole mit num_ctx=%d.",
                        model,
                        context_size,
                        next_context_size,
                    )
                    continue
                self._raise_for_status(r)
                return r.json().get("response", "")

        raise RuntimeError("Ollama-Vision-Anfrage endete unerwartet ohne Antwort.")


_service: OllamaService | None = None


def get_ollama_service() -> OllamaService:
    global _service
    if _service is None:
        from app.config import get_config
        cfg = get_config()
        _service = OllamaService(
            base_url=cfg.models.ollama_base_url,
            model=cfg.models.ollama_model,
            timeout=cfg.models.ollama_timeout,
            keep_alive=cfg.models.ollama_keep_alive,
        )
    return _service


def get_background_ollama_service() -> OllamaService:
    """Erzeugt den separaten Ollama-Service für langsame Import-Aufgaben."""
    from app.config import get_config

    cfg = get_config()
    return OllamaService(
        base_url=cfg.models.ollama_base_url,
        model=getattr(cfg.models, "background_ollama_model", "qwen2.5:7b"),
        timeout=cfg.models.ollama_timeout,
        keep_alive=cfg.models.ollama_keep_alive,
    )
