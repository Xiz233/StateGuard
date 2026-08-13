import os

from stateguard.models.config import load_model_config


def test_model_config_expands_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE", "http://model/v1")
    path = tmp_path / "models.yaml"
    path.write_text("providers:\n  p:\n    base_url: ${BASE}\n    model: m\n    api_key_env: KEY\n")
    assert load_model_config(path)["p"].base_url == "http://model/v1"
