from __future__ import annotations

import json

from .base import GuardBackend
from ..parser import parse_guard_output


class MLLMBackend(GuardBackend):
    def __init__(self, model_client):
        self.model_client = model_client

    def verify(self, task_state, before, proposal, after, repair_context=None):
        prompt = json.dumps({
            "task_dag": task_state.serialize(), "proposal": proposal.to_dict(),
            "before": before.to_dict(), "after": after.to_dict(),
            "repair_context": repair_context.to_dict() if repair_context else None,
            "instruction": ("Judge this transition once. Return JSON with judgement, "
                            "progress_updates, fault_root, fault_type, verification_target, reason. "
                            "Do not return affected nodes."),
        }, default=str)
        images = [x for x in (before.screenshot, after.screenshot) if x]
        response = self.model_client.generate([{"role": "user", "content": prompt}], images,
                                              response_schema={"type": "object"})
        return parse_guard_output(response.parsed)
