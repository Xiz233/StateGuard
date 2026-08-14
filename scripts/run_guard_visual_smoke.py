from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stateguard.models import OpenAICompatibleModelClient, load_model_config


def main():
    parser = argparse.ArgumentParser(description="Run configured visual Guard fixtures")
    parser.add_argument("--config", default="configs/models.yaml")
    args = parser.parse_args()
    required = ("STATEGUARD_API_KEY", "STATEGUARD_BASE_URL", "STATEGUARD_MODEL")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        sys.exit("BLOCKED_BY_CREDENTIAL: " + ", ".join(missing))
    fixtures = Path("tests/assets/transitions")
    cases = {
        "correct": "verified",
        "wrong_target": "contradicted",
        "ambiguous_save": "unknown",
    }
    absent = [name for name in cases if not (fixtures / name / "before.png").exists()
              or not (fixtures / name / "after.png").exists()]
    if absent:
        sys.exit("BLOCKED_BY_ASSET: " + ", ".join(absent))
    client = OpenAICompatibleModelClient(load_model_config(args.config)["stateguard_api"])
    for name, expected in cases.items():
        response = client.generate([{"role": "user", "content":
            "Judge the before/after transition. Return JSON with judgement and fault_root."}],
            [str(fixtures / name / "before.png"), str(fixtures / name / "after.png")],
            response_schema={"type": "object"})
        actual = response.parsed.get("judgement", "").lower()
        print(f"{name}: {actual}")
        if actual != expected:
            sys.exit(f"expected {expected}, got {actual}")


if __name__ == "__main__":
    main()
