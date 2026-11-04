from __future__ import annotations

import argparse
import hashlib
import io
import json
import time
from pathlib import Path

from PIL import Image, ImageChops

from integrations.osworld.adapter import DesktopEnvBackend, OSWorldAdapter


def save_screenshot(observation, path: Path):
    if not isinstance(observation.screenshot, bytes):
        raise ValueError("OSWorld did not return screenshot bytes")
    path.write_bytes(observation.screenshot)


def screenshot_digest(observation) -> str:
    if not isinstance(observation.screenshot, bytes):
        raise ValueError("OSWorld did not return screenshot bytes")
    return hashlib.sha256(observation.screenshot).hexdigest()


def changed_pixels(before: bytes, after: bytes) -> int:
    first = Image.open(io.BytesIO(before)).convert("RGB")
    second = Image.open(io.BytesIO(after)).convert("RGB")
    if first.size != second.size:
        raise ValueError(f"screenshot dimensions changed from {first.size} to {second.size}")
    histogram = ImageChops.difference(first, second).convert("L").histogram()
    return sum(histogram[1:])


def main():
    parser = argparse.ArgumentParser(description="Run a standalone real OSWorld contract smoke")
    parser.add_argument("--task-config", required=True)
    parser.add_argument("--actions", required=True,
                        help="JSON list of generic atomic actions in execution order")
    parser.add_argument("--provider", default="docker")
    parser.add_argument("--osworld-root")
    parser.add_argument("--vm-path")
    parser.add_argument("--cache-dir", default="cache")
    parser.add_argument("--output", default="artifacts/osworld_smoke")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--settle-seconds", type=float, default=1.0,
                        help="Wait before recapturing each post-action screenshot")
    parser.add_argument("--min-type-changed-pixels", type=int, default=100,
                        help="Reject caret-only changes as successful visible typing")
    parser.add_argument("--require-full-action-set", action="store_true",
                        help="Require click/type/hotkey/scroll/drag/wait coverage")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    actions = json.loads(Path(args.actions).read_text(encoding="utf-8"))
    if not isinstance(actions, list) or not actions:
        raise ValueError("actions must be a non-empty JSON list")

    backend = DesktopEnvBackend(provider_name=args.provider, headless=args.headless,
                                osworld_root=args.osworld_root, path_to_vm=args.vm_path,
                                cache_dir=args.cache_dir, require_a11y_tree=False,
                                client_password="password")
    adapter = OSWorldAdapter(backend)
    checks, labels, trace = {}, {"click": "after_click.png", "type": "after_type.png"}, []
    try:
        before = adapter.reset({"task_config_path": str(Path(args.task_config).resolve())})
        save_screenshot(before, output / "before.png")
        previous_digest = screenshot_digest(before)
        previous_screenshot = before.screenshot
        checks["reset"] = checks["screenshot"] = True
        for index, action in enumerate(actions, 1):
            step_observation = adapter.step(action)
            time.sleep(args.settle_seconds)
            observation = adapter.observe()
            label = labels.get(action.get("type"), f"after_{index:02d}_{action.get('type')}.png")
            save_screenshot(observation, output / label)
            kind = action.get("type", f"action_{index}")
            digest = screenshot_digest(observation)
            changed = digest != previous_digest
            pixel_changes = changed_pixels(previous_screenshot, observation.screenshot)
            checks[kind] = True
            if kind == "type":
                checks["type_visible_change"] = pixel_changes >= args.min_type_changed_pixels
            trace.append({"index": index, "action": action, "screenshot": label,
                          "sha256": digest, "changed_from_previous": changed,
                          "changed_pixels": pixel_changes,
                          "step_metadata": step_observation.metadata})
            previous_digest = digest
            previous_screenshot = observation.screenshot
        evaluation = adapter.evaluate()
        (output / "evaluator.json").write_text(
            json.dumps({"success": evaluation.success, "score": evaluation.score,
                        "details": evaluation.details}, indent=2), encoding="utf-8")
        checks["evaluator"] = True
        reset_again = adapter.reset({"task_config_path": str(Path(args.task_config).resolve())})
        save_screenshot(reset_again, output / "after_reset.png")
        checks["reset_same_task"] = True
    finally:
        adapter.close()

    (output / "action_trace.json").write_text(
        json.dumps(trace, indent=2, default=str), encoding="utf-8")
    required = {"reset", "screenshot", "click", "type", "type_visible_change",
                "evaluator", "reset_same_task"}
    if args.require_full_action_set:
        required |= {"hotkey", "scroll", "drag", "wait"}
    passed = required <= {key for key, value in checks.items() if value}
    report = ["# OSWorld standalone smoke", "", f"**OSWorld standalone: {'PASS' if passed else 'FAIL'}**",
              "", f"- Provider: `{args.provider}`", f"- Task: `{args.task_config}`", "",
              "## Checks", "", *[f"- [{'x' if checks.get(key) else ' '}] {key}"
                                   for key in sorted(required | set(checks))]]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
