from app import config


def test_vision_ollama_timeout_defaults_to_thirty_minutes():
    assert config.ModelsConfig().vision_ollama_timeout == 1800.0


def test_vision_ollama_timeout_can_be_overridden_from_environment(monkeypatch):
    monkeypatch.setenv("JOLIA_VISION_OLLAMA_TIMEOUT", "3600")
    data = {"models": {"vision_ollama_timeout": 1800.0}}

    config._apply_env_overrides(data)

    assert data["models"]["vision_ollama_timeout"] == 3600.0
