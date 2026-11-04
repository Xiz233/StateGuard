from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from stateguard.compiler.validator import ValidationError, validate_spec
from stateguard.models import create_model_client, load_model_config


NODE_FIELDS = (
    "node_id, description, dependencies, expected_result_semantic, evidence_mode, required"
)


def draft_graph(client, task: dict, max_attempts: int = 2) -> dict:
    instruction = (
        "Return one JSON object whose only top-level key is nodes. Do not wrap it in task_dag, "
        "graph, result, or markdown. nodes must be a non-empty array. Each node must contain "
        f"exactly these semantic fields: {NODE_FIELDS}. Use node IDs S1, S2, ...; dependencies "
        "must reference earlier node IDs; evidence_mode must be visual, persistence, hybrid, or "
        "structured; required must be true. Prefer 4-8 meaningful subgoals for multi-step tasks, "
        "without inventing unnecessary GUI actions. Do not infer or reproduce a hidden benchmark "
        "evaluator, gold state, private verifier, screen coordinates, or concrete GUI action "
        f"sequence. User instruction: {task['instruction']}"
    )
    messages = [{"role": "user", "content": instruction}]
    last_draft, last_error = None, None
    for attempt in range(max_attempts):
        response = client.generate(messages, response_schema={"type": "object"})
        last_draft = response.parsed
        try:
            validate_spec(last_draft)
            return last_draft
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            last_error = exc
            if attempt + 1 < max_attempts:
                messages.extend([
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content": (
                        f"Invalid DAG JSON: {exc}. Correct the previous object. The top-level "
                        f"object must be {{\"nodes\": [...]}} and each node requires {NODE_FIELDS}. "
                        "Return JSON only."
                    )},
                ])
    raise ValueError(
        f"task {task['task_id']} invalid DAG after {max_attempts} attempts: "
        f"{last_error}; output={last_draft!r}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="configs/poc/selected_tasks.yaml")
    parser.add_argument("--models", default="configs/models.yaml")
    parser.add_argument("--provider", default="stateguard_api")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    tasks = yaml.safe_load(Path(args.manifest).read_text())["tasks"]
    client = create_model_client(load_model_config(args.models)[args.provider])
    for task in tasks:
        path = Path(task["graph_file"])
        if args.skip_existing and path.exists():
            validate_spec(json.loads(path.read_text(encoding="utf-8")))
            print(f"{task['task_id']}: valid existing graph -> {path}", flush=True)
            continue
        draft = draft_graph(client, task)
        draft["graph"] = {"approved": False, "source": "semantic_draft",
                          "contains_hidden_evaluator": False}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
        print(f"{task['task_id']}: {len(draft['nodes'])} nodes -> {path}", flush=True)


if __name__ == "__main__": main()
