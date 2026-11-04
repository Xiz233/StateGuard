from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


TARGETS = {"calc": 4, "writer": 3, "chrome": 3, "file": 2}
AUTH_TERMS = ("log in", "login", "sign in", "oauth", "google account", "captcha",
              "verification code", "2fa", "two-factor")
TARGET_APP_TERMS = {
    "calc": ("calc",),
    "writer": ("writer",),
    "chrome": ("chrome",),
    "file": ("file", "os", "desktop", "nautilus"),
}
OUTSIDE_APP_TERMS = ("impress", "gimp", "vlc", "thunderbird")


def _category_from_text(text: str) -> str | None:
    for category, terms in TARGET_APP_TERMS.items():
        if any(term in text for term in terms):
            return category
    return None


def category_for(raw: dict) -> str | None:
    explicit = " ".join(str(raw.get(key) or "").lower() for key in ("application", "app"))
    category = _category_from_text(explicit)
    if category:
        return category
    if any(term in explicit for term in OUTSIDE_APP_TERMS):
        return None

    related = " ".join(str(value).lower() for value in raw.get("related_apps") or [])
    if any(term in related for term in OUTSIDE_APP_TERMS):
        return None

    snapshot = str(raw.get("snapshot") or "").lower()
    category = _category_from_text(snapshot)
    if category:
        return category
    if any(term in snapshot for term in OUTSIDE_APP_TERMS):
        return None
    return _category_from_text(related)


def eligibility(raw: dict) -> tuple[bool, list[str]]:
    reasons = []
    instruction = str(raw.get("instruction") or raw.get("task") or "").lower()
    if not raw.get("evaluator"):
        reasons.append("missing evaluator")
    if any(term in instruction for term in AUTH_TERMS):
        reasons.append("requires account/authentication or captcha")
    if raw.get("proxy"):
        reasons.append("requires proxy-dependent web access")
    if category_for(raw) is None:
        reasons.append("outside target app categories")
    return not reasons, reasons


def discover(root: Path):
    tasks = []
    for path in sorted(root.rglob("*.json")):
        try: raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError): continue
        if not isinstance(raw, dict) or not (raw.get("instruction") or raw.get("task")): continue
        task_id = str(raw.get("id") or raw.get("task_id") or path.stem)
        app = str(raw.get("application") or raw.get("app") or raw.get("snapshot") or
                  "unknown").lower()
        eligible, reasons = eligibility(raw)
        tasks.append({"task_id": task_id, "instruction": raw.get("instruction", raw.get("task")),
                      "application": app, "category": category_for(raw),
                      "evaluator": raw.get("evaluator"),
                      "setup_requirements": raw.get("setup", raw.get("config", [])),
                      "source": str(path.resolve()), "task_config_path": str(path.resolve()),
                      "proxy": bool(raw.get("proxy")), "eligible": eligible,
                      "ineligible_reasons": reasons})
    return tasks


def select(tasks, seed=20260814):
    rng, groups = random.Random(seed), defaultdict(list)
    for task in tasks:
        if not task["eligible"]: continue
        key = task.get("category")
        if key: groups[key].append(task)
    chosen = []
    for key, count in TARGETS.items():
        pool = sorted(groups[key], key=lambda t: t["task_id"])
        rng.shuffle(pool)
        primary_terms = {"calc": ("calc",), "writer": ("writer",),
                         "chrome": ("chrome",),
                         "file": ("file", "os", "desktop", "nautilus")}[key]
        pool.sort(key=lambda task: (
            not any(term in task.get("application", "") for term in primary_terms),
            not bool(task.get("setup_requirements")),
            len(str(task.get("instruction", "")).split()) < 8,
        ))
        chosen += pool[:count]
    return sorted(chosen, key=lambda t: t["task_id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--output", default="configs/tasks/osworld")
    parser.add_argument("--artifacts", default="artifacts/task_discovery")
    parser.add_argument("--seed", type=int, default=20260814)
    args = parser.parse_args()
    root, output = Path(args.benchmark_root), Path(args.output)
    if not root.exists(): raise ValueError(f"benchmark root does not exist: {root}")
    artifacts = Path(args.artifacts); artifacts.mkdir(parents=True, exist_ok=True)
    all_tasks = discover(root); eligible = [t for t in all_tasks if t["eligible"]]
    selected = select(all_tasks, args.seed)
    selected_counts = {key: sum(task["category"] == key for task in selected) for key in TARGETS}
    missing = {key: TARGETS[key] - selected_counts[key] for key in TARGETS
               if selected_counts[key] != TARGETS[key]}
    if missing:
        raise ValueError(f"cannot construct required 12-task subset; category deficits: {missing}")
    for name, value in (("all_tasks.json", all_tasks), ("eligible_tasks.json", eligible)):
        (artifacts / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    report = ["# OSWorld-Verified task selection", "", f"Discovered: {len(all_tasks)}",
              f"Eligible: {len(eligible)}", f"Selected: {len(selected)}", "",
              "## Category counts", ""]
    report += [f"- {key}: {selected_counts[key]}/{count}" for key, count in TARGETS.items()]
    report += ["", "## Selected tasks", ""]
    report += [f"- {t['task_id']}: {t['category']} (`{t['application']}`)" for t in selected]
    excluded = [task for task in all_tasks if task["ineligible_reasons"]]
    report += ["", "## Exclusion summary", "",
               f"Excluded tasks: {len(excluded)}. Reasons are preserved in `all_tasks.json`."]
    (artifacts / "selection_report.md").write_text("\n".join(report), encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    import yaml
    manifest = {"seed": args.seed, "tasks": [{**t, "graph_file":
        str(output / f"{t['task_id']}.json")} for t in selected]}
    Path("configs/poc/selected_tasks.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))


if __name__ == "__main__": main()
