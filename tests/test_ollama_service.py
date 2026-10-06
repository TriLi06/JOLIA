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
