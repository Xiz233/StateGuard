from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from stateguard.models import OpenAICompatibleModelClient, load_model_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="configs/poc/selected_tasks.yaml")
    parser.add_argument("--models", default="configs/models.yaml")
    parser.add_argument("--provider", default="stateguard_api")
    args = parser.parse_args()
    tasks = yaml.safe_load(Path(args.manifest).read_text())["tasks"]
    client = OpenAICompatibleModelClient(load_model_config(args.models)[args.provider])
    for task in tasks:
        response = client.generate([{"role": "user", "content":
            "Draft a concise task DAG as JSON with nodes: node_id, description, dependencies, "
            "expected_result_semantic, evidence_mode, required. Instruction: " + task["instruction"]}],
            response_schema={"type": "object"})
        draft = response.parsed; draft["graph"] = {"approved": False}
        path = Path(task["graph_file"]); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(draft, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
