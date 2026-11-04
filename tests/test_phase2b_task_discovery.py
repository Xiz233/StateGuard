import importlib.util
import json


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def test_task_discovery_and_selection_are_deterministic(tmp_path):
    for i, app in enumerate(["calc", "writer", "chrome", "file_manager"] * 4):
        (tmp_path / f"t{i}.json").write_text(json.dumps({"id": f"t{i}",
            "instruction": "do work", "application": app, "evaluator": "state"}))
    module = load_script("prepare_osworld_poc")
    tasks = module.discover(tmp_path)
    assert module.select(tasks, 7) == module.select(tasks, 7)
    assert len(module.select(tasks, 7)) == 12
    assert {task["category"] for task in module.select(tasks, 7)} == {
        "calc", "writer", "chrome", "file"}


def test_task_discovery_excludes_auth_and_proxy(tmp_path):
    (tmp_path / "login.json").write_text(json.dumps({"id": "login",
        "instruction": "Log in to the site", "snapshot": "chrome", "evaluator": {"func": "x"}}))
    (tmp_path / "proxy.json").write_text(json.dumps({"id": "proxy",
        "instruction": "Open page", "snapshot": "chrome", "proxy": True,
        "evaluator": {"func": "x"}}))
    module = load_script("prepare_osworld_poc")
    tasks = module.discover(tmp_path)
    assert not any(task["eligible"] for task in tasks)


def test_primary_app_wins_over_related_apps():
    module = load_script("prepare_osworld_poc")
    assert module.category_for({"snapshot": "os", "related_apps": ["chrome"]}) == "file"
    assert module.category_for({"snapshot": "libreoffice_impress",
                                "related_apps": ["libreoffice_writer"]}) is None
    assert module.category_for({"snapshot": "multiapps",
                                "related_apps": ["chrome"]}) == "chrome"


def test_related_target_app_wins_over_base_snapshot():
    module = load_script("prepare_osworld_poc")
    assert module.category_for({"snapshot": "chrome", "related_apps": ["vlc"]}) is None
    assert module.category_for({"snapshot": "multiapps",
                                "related_apps": ["libreoffice_calc"]}) == "calc"
