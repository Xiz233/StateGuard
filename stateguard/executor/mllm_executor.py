from __future__ import annotations

import json

from .base import Executor
from .parser import parse_executor_output
from .prompts import REPAIR_PROMPT


class MLLMExecutor(Executor):
    def __init__(self, model_client, instruction: str, history=None):
        self.model_client, self.instruction = model_client, instruction
        self.history = history

    def act(self, observation, task_state, repair_context=None):
        repair = ""
        if repair_context:
            repair = REPAIR_PROMPT.format(
                fault_root=repair_context.fault_root, repair_goal=repair_context.goal,
                preserve_nodes=repair_context.preserve_nodes, stale_nodes=repair_context.stale_nodes,
                reverify_nodes=repair_context.reverify_nodes)
        prompt = json.dumps({"instruction": self.instruction,
                             "task_state": task_state.serialize(), "repair": repair,
                             "history": self.history.recent() if self.history else []}, default=str)
        response = self.model_client.generate([{"role": "user", "content": prompt}],
                                              [observation.screenshot] if observation.screenshot else None,
                                              response_schema={"type": "object"})
        return parse_executor_output(response.parsed)
