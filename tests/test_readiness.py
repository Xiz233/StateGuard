import importlib.util


def test_readiness_reports_optional_dependencies(monkeypatch):
    spec = importlib.util.spec_from_file_location("readiness", "scripts/check_readiness.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    result = module.readiness("missing.yaml")
    assert result["Core StateGuard"][0] == "READY"
    assert result["OSWorld"][0] in {"READY", "NOT AVAILABLE"}
