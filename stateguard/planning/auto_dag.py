"""Auto-DAG generator (planning/phase-1).

Input is strictly the user instruction + the initial observation/screenshot.
Manual DAGs, evaluators, gold states, and fault specs are never used here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parser import AutoDAGError, parse_auto_dag, validate_auto_dag
from .prompts import AUTO_DAG_PROMPT


@dataclass
class AutoDAGResult:
    nodes: list[dict] = field(default_factory=list)
    valid: bool = False
    attempts: int = 0
    raw_responses: list[str] = field(default_factory=list)
    error: str | None = None
    validation: dict | None = None

    def to_dict(self) -> dict:
        return {"nodes": self.nodes, "valid": self.valid, "attempts": self.attempts,
                "raw_responses": self.raw_responses, "error": self.error,
                "validation": self.validation}


class AutoDAGGenerator:
    def __init__(self, model_client, max_attempts: int = 2):
        self.model_client = model_client
        self.max_attempts = max_attempts
        self.calls = self.tokens = 0
        self.latency = 0.0

    def generate(self, instruction: str, observation) -> AutoDAGResult:
        """Generate a semantic task-state DAG from the instruction and the
        initial observation only. At most `max_attempts` model calls."""
        prompt = AUTO_DAG_PROMPT.format(instruction=instruction)
        messages = [{"role": "user", "content": prompt}]
        raw_responses: list[str] = []
        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            response = self.model_client.generate(
                messages,
                [observation.screenshot] if observation and observation.screenshot else None,
                response_schema={"type": "object"})
            self.calls += 1
            self.latency += getattr(response, "latency_seconds", 0.0)
            self.tokens += sum((response.usage or {}).get(k, 0)
                               for k in ("prompt_tokens", "completion_tokens"))
            raw_responses.append(response.text)
            try:
                nodes = parse_auto_dag(response.parsed)
                report = validate_auto_dag(nodes)
            except AutoDAGError as exc:
                last_error = str(exc)
                messages.extend([
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content":
                        f"Invalid DAG: {exc}. Return JSON only with a valid nodes list."},
                ])
                continue
            return AutoDAGResult(nodes=nodes, valid=True, attempts=attempt,
                                 raw_responses=raw_responses, validation=report)
        return AutoDAGResult(valid=False, attempts=self.max_attempts,
                             raw_responses=raw_responses, error=last_error)