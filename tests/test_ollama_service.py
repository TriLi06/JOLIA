import base64
import sys
from types import ModuleType

import httpx
import pytest

from app.services.ollama_service import OllamaService


def test_generate_retries_connection_failure(monkeypatch):
    service = OllamaService("http://ollama:11434", "qwen2.5:7b")
    responses = iter(
        [
            httpx.ConnectError("connection refused"),
            httpx.Response(
                200,
                json={"response": "OK"},
                request=httpx.Request("POST", "http://ollama:11434/api/generate"),
            ),
        ]
    )
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(
        "app.services.ollama_service.httpx.post",
        post,
    )
    monkeypatch.setattr("app.services.ollama_service.time.sleep", lambda _delay: None)

    assert service.generate("Antworte mit OK.") == "OK"
    assert calls == ["http://ollama:11434/api/generate"] * 2


def test_generate_retries_temporary_server_errors(monkeypatch):
    service = OllamaService("http://ollama:11434", "qwen2.5:7b")
    responses = iter(
        [
            httpx.Response(503, request=httpx.Request("POST", "http://ollama:11434/api/generate")),
            httpx.Response(
                200,
                json={"response": "OK"},
                request=httpx.Request("POST", "http://ollama:11434/api/generate"),
            ),
        ]
    )
    calls = []
    monkeypatch.setattr(
        "app.services.ollama_service.httpx.post",
        lambda *args, **kwargs: calls.append(args[0]) or next(responses),
    )
    monkeypatch.setattr("app.services.ollama_service.time.sleep", lambda _delay: None)

    assert service.generate("Antworte mit OK.") == "OK"
    assert len(calls) == 2


def test_embed_does_not_hide_model_errors_as_old_api_fallback(monkeypatch):
    service = OllamaService("http://ollama:11434", "qwen2.5:7b")
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        return httpx.Response(
            404,
            text="model 'missing' not found",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    with pytest.raises(httpx.HTTPStatusError):
        service.embed(["text"], "missing")

    assert calls == ["http://ollama:11434/api/embed"]


def test_document_summary_calls_model_without_availability_preflight(monkeypatch):
    class Service:
        def is_available(self):
            return False

        def generate(self, _prompt):
            return "Von Ollama zusammengefasst."

    monkeypatch.setattr(
        "app.services.ollama_service.get_background_ollama_service",
        lambda: Service(),
    )

    from app.services.summarization_service import generate_document_summary

    assert generate_document_summary("Ein Text, der zusammengefasst werden soll.") == (
        "Von Ollama zusammengefasst."
    )


def test_describe_image_sends_normalized_jpeg(monkeypatch, tmp_path):
    class FakeImage:
        mode = "RGB"
        info = {}
        size = (64, 64)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def thumbnail(self, *_args):
            pass

        def convert(self, _mode):
            return self

        def save(self, target, **_kwargs):
            target.write(b"normalized-jpeg")

    pil_module = ModuleType("PIL")
    image_module = ModuleType("PIL.Image")
    image_module.open = lambda _path: FakeImage()
    image_module.new = lambda *_args, **_kwargs: FakeImage()
    image_module.Resampling = type("Resampling", (), {"LANCZOS": 1})
    image_ops_module = ModuleType("PIL.ImageOps")
    image_ops_module.exif_transpose = lambda image: image
    pil_module.Image = image_module
    pil_module.ImageOps = image_ops_module
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageOps", image_ops_module)

    image_path = tmp_path / "unsupported-source.tif"
    image_path.write_bytes(b"original-tiff")
    captured = {}

    def post(url, *, json, **_kwargs):
        captured.update(json)
        return httpx.Response(
            200,
            json={"response": "Bild"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    result = OllamaService("http://ollama:11434", "qwen2.5vl:3b").describe_image(
        str(image_path),
        model="qwen2.5vl:3b",
        prompt="Beschreibe das Bild.",
    )

    assert result == "Bild"
    assert base64.b64decode(captured["images"][0]) == b"normalized-jpeg"


def test_describe_image_includes_ollama_error_detail(monkeypatch, tmp_path):
    class FakeImage:
        mode = "RGB"
        info = {}
        size = (64, 64)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def thumbnail(self, *_args):
            pass

        def convert(self, _mode):
            return self

        def save(self, target, **_kwargs):
            target.write(b"normalized-jpeg")

    pil_module = ModuleType("PIL")
    image_module = ModuleType("PIL.Image")
    image_module.open = lambda _path: FakeImage()
    image_module.new = lambda *_args, **_kwargs: FakeImage()
    image_module.Resampling = type("Resampling", (), {"LANCZOS": 1})
    image_ops_module = ModuleType("PIL.ImageOps")
    image_ops_module.exif_transpose = lambda image: image
    pil_module.Image = image_module
    pil_module.ImageOps = image_ops_module
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageOps", image_ops_module)

    image_path = tmp_path / "test.jpg"
    image_path.write_bytes(b"image")
    detail = '{"error":"image decode failed"}'

    def post(url, **_kwargs):
        return httpx.Response(
            400,
            text=detail,
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    with pytest.raises(httpx.HTTPStatusError, match="image decode failed"):
        OllamaService("http://ollama:11434", "qwen2.5vl:3b").describe_image(
            str(image_path),
            model="qwen2.5vl:3b",
        )
