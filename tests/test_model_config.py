import os

from stateguard.models.config import load_model_config


def test_model_config_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE", "http://model/v1")
    path = tmp_path / "models.yaml"
    path.write_text("providers:\n  p:\n    base_url: ${BASE}\n    model: m\n    api_key_env: KEY\n")
    assert load_model_config(path)["p"].base_url == "http://model/v1"


def test_model_config_preserves_provider_protocol(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("providers:\n  p:\n    type: anthropic_compatible\n"
                    "    base_url: https://example/v1\n    model: m\n    api_key_env: KEY\n")
    assert load_model_config(path)["p"].type == "anthropic_compatible"


def test_example_keeps_qwen_and_adds_luna_responses_provider():
    providers = load_model_config("configs/models.example.yaml")
    assert providers["stateguard_luna"].model == "gpt-5.6-luna"
    assert providers["stateguard_luna"].type == "openai_responses"
    assert providers["stateguard_qwen"].model == "qwen3.7-plus"
