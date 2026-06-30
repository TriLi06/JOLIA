from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class OllamaService:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

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
            r = httpx.post(url, json=payload, timeout=self.timeout)
            logger.debug(
                "Ollama Antwort erhalten → HTTP %s | Antwort-Länge: %d Zeichen",
                r.status_code,
                len(r.text),
            )
            r.raise_for_status()
            return r.json().get("response", "")
        except httpx.TimeoutException:
            logger.error(
                "Ollama-Timeout nach %ss – Modell: %s, URL: %s",
                self.timeout, self.model, url,
            )
            raise
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP-Fehler: %s", exc)
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
        try:
            r = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": texts},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()["embeddings"]
        except Exception:
            # Fallback: einzeln über /api/embeddings (ältere Ollama-Versionen)
            results = []
            for text in texts:
                r = httpx.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model, "prompt": text},
                    timeout=self.timeout,
                )
                r.raise_for_status()
                results.append(r.json()["embedding"])
            return results

    def describe_image(self, image_path: str, model: str, prompt: str | None = None) -> str:
        """Analysiert ein Bild mit einem Multimodal-Modell (z.B. llava, moondream).
        Gibt eine Beschreibung inkl. erkanntem Text zurück."""
        import base64

        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        if prompt is None:
            prompt = (
                "Analysiere dieses Bild detailliert auf Deutsch. "
                "1. Beschreibe den Inhalt des Bildes. "
                "2. Extrahiere und transkribiere ALLEN sichtbaren Text exakt so wie er im Bild steht. "
                "Trenne Beschreibung und extrahierten Text mit '--- TEXT ---'."
            )

        r = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {
                    # Niedrige Temperatur für faktentreue, reproduzierbare Analyse
                    "temperature": 0.1,
                    "top_p": 0.9,
                    # Genug Tokens, damit auch lange Texte vollständig transkribiert werden
                    "num_predict": 2048,
                    # Großes Kontextfenster für detaillierte, vollständige Antworten
                    "num_ctx": 4096,
                },
            },
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("response", "")


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
        )
    return _service
