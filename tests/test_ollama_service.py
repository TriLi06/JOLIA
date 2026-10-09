import base64
from concurrent.futures import ThreadPoolExecutor
import sys
import threading
import time
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


def test_generate_sends_requested_response_format(monkeypatch):
    captured = {}

    def post(url, *, json, **_kwargs):
        captured.update(json)
        return httpx.Response(
            200,
            json={"response": '{"description":"Text","short_summary":"Titel"}'},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    response = OllamaService("http://ollama:11434", "qwen2.5:7b").generate(
        "Erstelle Beschreibungen.",
        response_format="json",
    )

    assert captured["format"] == "json"
    assert response == '{"description":"Text","short_summary":"Titel"}'


def test_inference_requests_are_serialized_across_instances_and_endpoints(monkeypatch):
    active_requests = 0
    maximum_active_requests = 0
    state_lock = threading.Lock()

    def post(url, **_kwargs):
        nonlocal active_requests, maximum_active_requests
        with state_lock:
            active_requests += 1
            maximum_active_requests = max(maximum_active_requests, active_requests)
        try:
            time.sleep(0.03)
            payload = {"embeddings": [[0.1]]} if url.endswith("/api/embed") else {"response": "OK"}
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request("POST", url),
            )
        finally:
            with state_lock:
                active_requests -= 1

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)
    text_service = OllamaService("http://ollama:11434", "qwen2.5:1.5b")
    embedding_service = OllamaService("http://ollama:11434", "bge-m3")

    with ThreadPoolExecutor(max_workers=2) as executor:
        generation = executor.submit(text_service.generate, "Prompt")
        embedding = executor.submit(embedding_service.embed, ["Text"], "bge-m3")
        assert generation.result() == "OK"
        assert embedding.result() == [[0.1]]

    assert maximum_active_requests == 1


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
    assert captured["options"]["num_ctx"] == 8192
    assert captured["options"]["num_predict"] == 2048


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
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
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
    assert calls == ["http://ollama:11434/api/generate"]


def test_describe_image_increases_context_after_context_overflow(monkeypatch, tmp_path):
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
    context_sizes = []
    responses = iter(
        [
            httpx.Response(
                400,
                json={
                    "error": (
                        '{"error":{"code":400,"message":"request (9000 tokens) exceeds '
                        'the available context size (8192)","type":"exceed_context_size_error"}}'
                    )
                },
                request=httpx.Request("POST", "http://ollama:11434/api/generate"),
            ),
            httpx.Response(
                200,
                json={"response": "Bild erkannt"},
                request=httpx.Request("POST", "http://ollama:11434/api/generate"),
            ),
        ]
    )

    def post(url, *, json, **_kwargs):
        context_sizes.append(json["options"]["num_ctx"])
        return next(responses)

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    answer = OllamaService("http://ollama:11434", "qwen2.5vl:3b").describe_image(
        str(image_path),
        model="qwen2.5vl:3b",
    )

    assert answer == "Bild erkannt"
    assert context_sizes == [8192, 12288]


def test_describe_image_stops_after_maximum_context_overflows(monkeypatch, tmp_path):
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
    context_sizes = []

    def post(url, *, json, **_kwargs):
        context_sizes.append(json["options"]["num_ctx"])
        return httpx.Response(
            400,
            json={
                "error": (
                    '{"error":{"message":"request exceeds the available context size",'
                    '"type":"exceed_context_size_error"}}'
                )
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.services.ollama_service.httpx.post", post)

    with pytest.raises(httpx.HTTPStatusError, match="exceed_context_size_error"):
        OllamaService("http://ollama:11434", "qwen2.5vl:3b").describe_image(
            str(image_path),
            model="qwen2.5vl:3b",
        )

    assert context_sizes == [8192, 12288, 16384]
