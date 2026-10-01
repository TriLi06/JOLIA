import sys
from types import SimpleNamespace

from app.services import clap_service


def test_init_clap_model_forwards_local_files_only(monkeypatch):
    calls = []

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("model", model_name, kwargs))
            return cls()

        def eval(self):
            return None

    class FakeProcessor:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls.append(("processor", model_name, kwargs))
            return cls()

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(ClapModel=FakeModel, ClapProcessor=FakeProcessor),
    )
    monkeypatch.setattr(clap_service, "_clap_model", None)
    monkeypatch.setattr(clap_service, "_clap_processor", None)
    monkeypatch.setattr(clap_service, "_clap_model_name", "")

    clap_service._init_clap_model("test/clap", local_files_only=True)

    assert calls == [
        ("model", "test/clap", {"local_files_only": True}),
        ("processor", "test/clap", {"local_files_only": True}),
    ]