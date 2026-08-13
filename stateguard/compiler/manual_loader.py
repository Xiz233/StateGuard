import json
from pathlib import Path

from .task_compiler import compile_from_spec


def load_manual_task(path, available_devices=None):
    return compile_from_spec(json.loads(Path(path).read_text(encoding="utf-8")), available_devices)
