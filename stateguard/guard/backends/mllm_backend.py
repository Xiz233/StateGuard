from __future__ import annotations

import json

from .base import GuardBackend
from ..parser import parse_guard_output


class MLLMBackend(GuardBackend):
    def __init__(self, model_client, history=None, max_parse_retries: int = 1):
        self.model_client = model_client
        self.history, self.max_parse_retries = history, max_parse_retries
        self.calls = self.tokens = 0
        self.latency = 0.0

    def verify(self, task_state, before, proposal, after, repair_context=None):
        prompt = json.dumps({
            "task_dag": task_state.serialize(), "proposal": proposal.to_dict(),
            "before": before.to_dict(), "after": after.to_dict(),
            "repair_context": repair_context.to_dict() if repair_context else None,
            "recent_history": self.history.recent() if self.history else [],
            "instruction": ("Judge this transition once. Return JSON with judgement, "
                            "progress_updates, fault_root, fault_type, verification_target, reason. "
                            "Do not return affected nodes."),
        }, default=str)
        images = [x for x in (before.screenshot, after.screenshot) if x]
        messages = [{"role": "user", "content": prompt}]
        error = None
        for _ in range(self.max_parse_retries + 1):
            response = self.model_client.generate(messages, images, response_schema={"type": "object"})
            self.calls += 1
            self.latency += response.latency_seconds
            self.tokens += sum((response.usage or {}).get(k, 0)
                               for k in ("prompt_tokens", "completion_tokens"))
            try:
                result = parse_guard_output(response.parsed)
                if result.fault_root and result.fault_root not in task_state:
                    raise ValueError(f"unknown fault_root {result.fault_root}")
                for update in result.progress_updates:
                    if update.get("node_id") not in task_state:
                        raise ValueError(f"unknown progress node {update.get('node_id')}")
                    if update.get("status") != "verified" or not update.get("evidence"):
                        raise ValueError("progress update must be verified with evidence")
                return result
            except ValueError as exc:
                error = exc
                messages.append({"role": "user", "content":
                    f"Invalid Guard JSON: {exc}. Return a valid JSON object only."})
        raise ValueError(f"guard_parse_failed: {error}")
