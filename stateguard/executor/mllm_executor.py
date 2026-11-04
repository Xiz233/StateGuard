from __future__ import annotations

import json

from ..core.dependency_graph import DependencyGraph
from ..core.action_similarity import actions_equivalent
from ..core.schema import ActionProposal
from .base import Executor
from .parser import parse_executor_output
from .prompts import REPAIR_PROMPT
from ..training_logging import record_parse


EXECUTOR_OUTPUT_INSTRUCTIONS = """Choose exactly one atomic GUI action for the current screenshot.
Use a pending, active, executed, or failed subgoal whose dependencies satisfy dependency_policy. A subgoal may
require several atomic actions: keep the same subgoal_id and advance it one action at a time.
Return JSON only with exactly:
{
  "subgoal_id": "an existing task node id",
  "intent": "the immediate purpose of this single action",
  "expected_effect": "only the immediate visible effect expected from this single action",
  "effect_observability": "visual",
  "action": {"type": "click", "x": 0, "y": 0},
  "subgoal_done": false,
  "is_finish": false
}
Set "subgoal_done" to true ONLY when, after this single action, you believe the semantic state of
the current subgoal has been fully achieved and should be verified. Otherwise keep it false.
Set effect_observability to exactly one of visual, structured, persistence, or none. Use visual only
when this atomic action should visibly change pixels on screen. Use structured for a machine-readable
state change, persistence for save/submit durability, and none for passive inspection, reasoning,
copying, or waiting. This field describes the immediate action effect, not the whole subgoal.
The action must be exactly one of:
- {"type":"click","x":integer,"y":integer,"button":"left|right|middle","clicks":1-3}
- {"type":"type","text":"string"}
- {"type":"hotkey","keys":["key", ...]}
- {"type":"scroll","dx":integer,"dy":integer}
- {"type":"drag","x1":integer,"y1":integer,"x2":integer,"y2":integer}
- {"type":"wait"}
The type action only inserts text into the focused field. It NEVER presses Enter or submits a
terminal command. After typing a terminal command, use {"type":"hotkey","keys":["enter"]} as the
next atomic action. If the intended command is already visible but has not run, press Enter instead
of typing it again. Before replacing incorrect text on a terminal input line, clear that line with
Ctrl+U, then type the corrected command once.
Do not claim the whole subgoal as the expected_effect of a preparatory action. For example, clicking
an address bar should expect the address bar to become focused; a later type action can expect the
URL text to appear. Inspect the latest screenshot and recent history so you do not repeat an action
whose immediate effect is already visible.
If recent_history shows the same action repeatedly received judgement=unknown and the requested
verification target is still absent, do not repeat it again. Change strategy with a preparatory
action such as focusing the intended application or editable content first.
Do not combine actions or add fields. Use is_finish=true only when the whole task is visibly complete;
then return subgoal_id="", action={}, subgoal_done=true, effect_observability="none", and explain the completion evidence in
expected_effect."""


class MLLMExecutor(Executor):
    def __init__(self, model_client, instruction: str, history=None, bounds=None,
                 max_parse_retries: int = 1, coordinate_scale: int | None = None,
                 require_verified_deps: bool = True, guidance: str = "dense"):
        self.model_client, self.instruction = model_client, instruction
        self.history = history
        self.bounds, self.max_parse_retries = bounds, max_parse_retries
        self.coordinate_scale = coordinate_scale
        self.require_verified_deps = require_verified_deps
        self.guidance = guidance
        self.calls = self.tokens = 0
        self.latency = 0.0
        self.finish_reconciliation_count = 0

    def _recent_history(self):
        return self.history.recent() if self.history else []

    def _blocked_actions(self):
        getter = getattr(self.history, "blocked_actions", None)
        return getter() if getter else []

    def _dependency_statuses(self) -> set[str]:
        return {"verified"} if self.require_verified_deps else {"executed", "verified"}

    def _frontier_from_serialized(self, nodes: dict) -> list[str]:
        spec = [{"node_id": nid, "dependencies": n.get("dependencies", [])}
                for nid, n in nodes.items()]
        graph = DependencyGraph.from_spec(spec)
        status = {nid: n.get("status") for nid, n in nodes.items()}
        satisfied = self._dependency_statuses()
        return [nid for nid in graph.topological_order()
                if status.get(nid) != "verified"
                and all(status.get(parent) in satisfied
                        for parent in graph.parents(nid))]

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
        serialized = task_state.serialize()
        nodes = serialized.get("nodes", {})
        incomplete_required = [
            node_id for node_id, node in nodes.items()
            if node.get("required", True) and node.get("status") != "verified"
        ]
        finish_allowed = not self.require_verified_deps or not incomplete_required
        payload = {
            "task_instruction": self.instruction,
            "task_state": serialized,
            "repair": repair,
            "recent_history": self._recent_history(),
            "blocked_actions": self._blocked_actions(),
            "screen_bounds": ({"width": self.bounds.width, "height": self.bounds.height}
                              if self.bounds else None),
            "coordinate_contract": (
                f"For click and drag coordinates, use integers from 0 to "
                f"{self.coordinate_scale} on each axis, where 0 is the left/top edge and "
                f"{self.coordinate_scale} is the right/bottom edge. Coordinates will be scaled "
                "to the screen; do not output pixel coordinates."
                if self.coordinate_scale else
                "Use absolute pixel coordinates within screen_bounds for click and drag actions."
            ),
            "dependency_policy": (
                "A dependency is satisfied only when its status is verified."
                if self.require_verified_deps else
                "A dependency is satisfied when its status is executed or verified. "
                "This is an Executor-only control run without Guard verification."
            ),
            "finish_allowed": finish_allowed,
            "incomplete_required_nodes": incomplete_required,
            "finish_policy": (
                "is_finish=true is allowed."
                if finish_allowed else
                "is_finish=true is forbidden until incomplete_required_nodes is empty. "
                "Choose an executable frontier node and acquire evidence for it."),
            "output_contract": EXECUTOR_OUTPUT_INSTRUCTIONS,
        }
        if self.guidance == "frontier":
            frontier = self._frontier_from_serialized(nodes)
            payload["frontier"] = [
                {"node_id": nid, "description": nodes[nid].get("description", "")}
                for nid in frontier
            ]
        prompt = json.dumps(payload, default=str)
        messages = [{"role": "user", "content": prompt}]
        error = None
        blocked_fallback = None
        frontier_fallback = None
        finish_fallback = None
        finish_rejections = 0
        for attempt in range(self.max_parse_retries + 1):
            response = self.model_client.generate(messages,
                [observation.screenshot] if observation.screenshot else None,
                response_schema={
                    "type": "object",
                    "required": ["subgoal_id", "intent", "expected_effect",
                                 "action", "is_finish"],
                    "properties": {
                        "subgoal_id": {"type": "string"},
                        "intent": {"type": "string"},
                        "expected_effect": {"type": "string"},
                        "action": {"type": "object"},
                        "subgoal_done": {"type": "boolean"},
                        "is_finish": {"type": "boolean"},
                    },
                })
            self.calls += 1
            self.latency += response.latency_seconds
            self.tokens += sum((response.usage or {}).get(k, 0)
                               for k in ("prompt_tokens", "completion_tokens"))
            try:
                parsed = self._scale_coordinates(response.parsed)
                proposal = parse_executor_output(parsed, self.bounds)
                if proposal.is_finish and not finish_allowed:
                    finish_rejections += 1
                    frontier = self._frontier_from_serialized(nodes)
                    if frontier:
                        target = frontier[0]
                        finish_fallback = ActionProposal(
                            target, {"type": "wait"},
                            "Reconcile a premature completion claim with the task state.",
                            "The Guard checks the current UI for evidence of the next "
                            "unverified frontier state.",
                            True, False, "none")
                    raise ValueError(
                        "is_finish=true is premature; required nodes remain unverified: "
                        f"{incomplete_required}")
                if not proposal.is_finish:
                    nodes = task_state.serialize().get("nodes", {})
                    if self.guidance == "frontier":
                        frontier = self._frontier_from_serialized(nodes)
                        if proposal.subgoal_id not in frontier:
                            graph = DependencyGraph.from_spec([
                                {"node_id": nid,
                                 "dependencies": value.get("dependencies", [])}
                                for nid, value in nodes.items()
                            ])
                            eligible_ancestors = [
                                node_id for node_id in frontier
                                if node_id in graph.ancestors(proposal.subgoal_id)
                            ] if proposal.subgoal_id in nodes else []
                            if len(eligible_ancestors) == 1:
                                target = eligible_ancestors[0]
                                frontier_fallback = ActionProposal(
                                    target, {"type": "wait"},
                                    "Reconcile the current UI with the executable frontier.",
                                    "The Guard checks whether the UI already demonstrates "
                                    "completion of this transient prerequisite.",
                                    True, False, "none")
                            raise ValueError(
                                f"subgoal {proposal.subgoal_id} is outside the executable "
                                f"frontier {sorted(frontier)}; choose a frontier subgoal")
                    selected = nodes.get(proposal.subgoal_id, {})
                    status = selected.get("status")
                    if status == "verified":
                        raise ValueError(
                            f"subgoal {proposal.subgoal_id} is already verified; "
                            "choose an incomplete subgoal")
                    satisfied = self._dependency_statuses()
                    blocked = [node_id for node_id in selected.get("dependencies", [])
                               if nodes.get(node_id, {}).get("status") not in satisfied]
                    if blocked:
                        raise ValueError(
                            f"subgoal {proposal.subgoal_id} has unverified dependencies "
                            f"{blocked}; continue an eligible predecessor")
                    blocked_actions = self._blocked_actions()
                    if any(
                        item.get("subgoal_id") == proposal.subgoal_id
                        and actions_equivalent(item.get("action"), proposal.action)
                        for item in blocked_actions
                    ):
                        fallback_action = self._blocked_fallback_action(proposal.action)
                        blocked_fallback = ActionProposal(
                            proposal.subgoal_id, fallback_action,
                            "Pause after a blocked no-effect action and reassess the UI.",
                            "Focus changes so the next action can use a different strategy.",
                            False, False)
                        raise ValueError(
                            "this action or nearby target is blocked after repeated no-effect "
                            "evidence; choose a different action type or UI region")
                record_parse(self.model_client, "completed", proposal.to_dict())
                return proposal
            except ValueError as exc:
                policy_rejection = any(fragment in str(exc) for fragment in (
                    "blocked after repeated", "outside the executable frontier",
                    "already verified", "unverified dependencies", "premature"))
                record_parse(
                    self.model_client,
                    "rejected" if policy_rejection else "failed",
                    response.parsed, exc)
                error = exc
                if (blocked_fallback is not None or frontier_fallback is not None) \
                        and attempt >= self.max_parse_retries:
                    break
                correction = {
                    "role": "user", "content":
                    f"Invalid action JSON: {exc}. Return one corrected JSON object only. "
                    "Use a currently executable frontier node and a different action."}
                prompt_echo = (isinstance(response.parsed, dict)
                               and "task_instruction" in response.parsed
                               and "output_contract" in response.parsed)
                if prompt_echo or len(response.text or "") > 8000:
                    messages = [messages[0], correction]
                else:
                    messages.extend([
                        {"role": "assistant", "content": response.text}, correction])
                if finish_rejections >= 2:
                    break
        if blocked_fallback is not None:
            return blocked_fallback
        if frontier_fallback is not None:
            return frontier_fallback
        if finish_fallback is not None:
            self.finish_reconciliation_count += 1
            return finish_fallback
        raise ValueError(f"executor_parse_failed: {error}")

    @staticmethod
    def _blocked_fallback_action(action):
        kind = action.get("type") if isinstance(action, dict) else None
        if kind == "click":
            return {"type": "hotkey", "keys": ["tab"]}
        if kind == "type":
            return {"type": "hotkey", "keys": ["esc"]}
        return {"type": "wait"}

    def _scale_coordinates(self, data):
        if not self.coordinate_scale or not isinstance(data, dict) or data.get("is_finish"):
            return data
        action = data.get("action")
        if not isinstance(action, dict) or action.get("type") not in {"click", "drag"}:
            return data
        if not self.bounds:
            raise ValueError("normalized coordinates require screen bounds")
        scaled = dict(data)
        scaled_action = dict(action)
        axes = {"x": self.bounds.width, "x1": self.bounds.width, "x2": self.bounds.width,
                "y": self.bounds.height, "y1": self.bounds.height, "y2": self.bounds.height}
        for key, size in axes.items():
            if key not in scaled_action:
                continue
            value = scaled_action[key]
            if not isinstance(value, (int, float)) or not 0 <= value <= self.coordinate_scale:
                raise ValueError(f"{key} outside normalized coordinate range")
            scaled_action[key] = round(value / self.coordinate_scale * (size - 1))
        scaled["action"] = scaled_action
        return scaled
