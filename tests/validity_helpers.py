import json
from pathlib import Path

from experiments.poc.config import load_config
from experiments.poc.runner import run_experiment


def run_earlier(tmp_path, mode="stateguard"):
    config = load_config("configs/poc/fake_osworld.yaml")
    config["experiment"] = {**config["experiment"], "output_dir": str(tmp_path)}
    run_experiment(config, mode, "fake_earlier_corruption", allow_dirty=True)
    run = Path(tmp_path) / f"fake_osworld_phase2b-{mode}" / "episodes"
    episode = run / f"fake_earlier_corruption--{mode}--fake_earlier_corruption"
    return json.loads((episode / "result.json").read_text()), episode
