from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def git(root: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def main():
    parser = argparse.ArgumentParser(description="Audit an OSWorld checkout for Verified PoC reuse")
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", default="artifacts/server2_audit/osworld_audit.md")
    args = parser.parse_args()
    root, output = Path(args.root).resolve(), Path(args.output)
    if not (root / ".git").exists():
        raise SystemExit(f"not a Git checkout: {root}")

    _, remotes = git(root, "remote", "-v")
    _, commit = git(root, "rev-parse", "HEAD")
    _, status = git(root, "status", "--short", "--branch")
    _, recent = git(root, "log", "-5", "--oneline")
    _, modified = git(root, "diff", "--name-only")
    modified_paths = [line for line in modified.splitlines() if line]
    sensitive = [path for path in modified_paths if
                 path.startswith("evaluation_examples/") or
                 path.startswith("desktop_env/evaluators/")]
    readme = (root / "README.md").read_text(encoding="utf-8", errors="replace")
    task_files = list((root / "evaluation_examples" / "examples").rglob("*.json"))
    official = "github.com/xlang-ai/OSWorld" in remotes
    verified = "OSWorld-Verified" in readme and bool(task_files)
    decision = "REUSE" if official and verified and not sensitive else "REDEPLOY"
    checks = {
        "Official xlang-ai/OSWorld origin": official,
        "OSWorld-Verified release marker and task definitions": verified,
        "Task/evaluator files unmodified": not sensitive,
        "Task definitions present": bool(task_files),
    }
    lines = [
        "# OSWorld audit", "", f"**Decision: {decision}**", "",
        f"- Path: `{root}`", f"- Commit: `{commit}`", f"- Task files: {len(task_files)}",
        "", "## Reuse checks", "",
        *[f"- [{'x' if ok else ' '}] {name}" for name, ok in checks.items()],
        "", "## Remotes", "", "```text", remotes, "```",
        "", "## Working tree", "", "```text", status or "clean", "```",
        "", "## Sensitive local changes", "",
        *([f"- `{path}`" for path in sensitive] or ["- None"]),
        "", "## Recent commits", "", "```text", recent, "```", "",
        "Runtime start/reset/screenshot/action/evaluator acceptance is recorded separately in ",
        "`artifacts/osworld_smoke/report.md` and remains mandatory before a formal run.",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(decision)


if __name__ == "__main__":
    main()
