from __future__ import annotations

import json

from .base import Executor
from .parser import parse_executor_output
from .prompts import REPAIR_PROMPT


class MLLMExecutor(Executor):
    def __init__(self, model_client, instruction: str, history=None, bounds=None,
                 max_parse_retries: int = 1):
        self.model_client, self.instruction = model_client, instruction
        self.history = history
        self.bounds, self.max_parse_retries = bounds, max_parse_retries
        self.calls = self.tokens = 0
        self.latency = 0.0

    def act(self, observation, task_state, repair_context=None):
        repair = ""
        if isinstance(repair_context, str):
            repair = repair_context
        elif repair_context and hasattr(repair_context, "fault_root"):
            repair = REPAIR_PROMPT.format(
                fault_root=repair_context.fault_root, repair_goal=repair_context.goal,
                preserve_nodes=repair_context.preserve_nodes, stale_nodes=repair_context.stale_nodes,
                reverify_nodes=repair_context.reverify_nodes)
        elif repair_context:
            repair = f"Verification required: {repair_context.target}"
        prompt = json.dumps({"instruction": self.instruction,
                             "task_state": task_state.serialize(), "repair": repair,
                             "history": self.history.recent() if self.history else []}, default=str)
        messages = [{"role": "user", "content": prompt}]
        error = None
        for attempt in range(self.max_parse_retries + 1):
            response = self.model_client.generate(messages,
                [observation.screenshot] if observation.screenshot else None,
                response_schema={"type": "object"})
            self.calls += 1
            self.latency += response.latency_seconds
            self.tokens += sum((response.usage or {}).get(k, 0)
                               for k in ("prompt_tokens", "completion_tokens"))
            try:
                return parse_executor_output(response.parsed, self.bounds)
            except ValueError as exc:
                error = exc
                messages.append({"role": "user", "content":
                    f"Invalid action JSON: {exc}. Return one valid schema object only."})
        raise ValueError(f"executor_parse_failed: {error}")
