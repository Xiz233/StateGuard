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
