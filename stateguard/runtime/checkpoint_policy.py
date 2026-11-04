"""Unified verification scheduler (planning/phase-2/5).

All Guard calls must go through a single entry point `evaluate()`. Three
policies share it:

  dense  - verify after every environment action (baseline, high overhead)
  sparse - verify only at semantic checkpoints (round-2)
  hybrid - sparse + causal-risk proactive checkpoints (round-2.5)

Checkpoint reasons (kinds):
  subgoal_done        (completion)  executor believes a semantic state is done
  finish              (finish)      global verification at task end
  repair_revalidation (repair)      subgoal_done on a repair target
  stagnation          (consistency) repeated actions / long same-subgoal wander
  causal_risk         (consistency) proactive check on high-leverage states

Fault exposure timing is deliberately NOT a trigger: the runtime must not
learn "an error happened here" from the fault scheduler.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from ..core.action_similarity import actions_equivalent


class NodeRisk(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def compute_node_risk(node, graph) -> NodeRisk:
    """Deterministic causal-leverage risk: how much downstream progress would
    be polluted if this state were wrong.

    persistence semantics -> HIGH (a saved/sent result is hard to undo)
    >=2 descendants      -> HIGH (broad downstream closure)
    1 descendant         -> MEDIUM
    leaf                 -> LOW
    """
    if node.evidence_mode == "persistence":
        return NodeRisk.HIGH
    n_desc = len(graph.descendants(node.node_id))
    if n_desc >= 2:
        return NodeRisk.HIGH
    if n_desc == 1:
        return NodeRisk.MEDIUM
    return NodeRisk.LOW


@dataclass
class CheckpointDecision:
    should_verify: bool
    reason: str | None = None
    target_node: str | None = None
    checkpoint_kind: str | None = None  # completion | consistency | finish | repair


@dataclass
class CompletionClaimState:
    contract_id: str | None
    evidence_signature: str | None
    strategy_id: str | None
    repeated_done_claims: int = 0


class CompletionClaimTracker:
    """Suppress repeated done claims until evidence, contract or strategy changes."""

    def __init__(self):
        self._claims: dict[str, CompletionClaimState] = {}
        self.overclaim_count = 0

    def should_verify(self, node_id: str, contract_id: str | None,
                      evidence_signature: str | None,
                      strategy_id: str | None = None) -> bool:
        current = (contract_id, evidence_signature, strategy_id)
        previous = self._claims.get(node_id)
        if previous is None or current != (
                previous.contract_id, previous.evidence_signature, previous.strategy_id):
            self._claims[node_id] = CompletionClaimState(*current)
            return True
        previous.repeated_done_claims += 1
        self.overclaim_count += 1
        return False

    def reset(self, node_id: str) -> None:
        self._claims.pop(node_id, None)

    def discard_nodes(self, node_ids) -> None:
        for node_id in node_ids:
            self.reset(node_id)


class CheckpointPolicy:
    def __init__(self, policy: str = "sparse",
                 repeated_action_threshold: int = 3,
                 same_subgoal_step_threshold: int = 10,
                 high_risk_interval: int = 2,
                 medium_risk_interval: int = 5,
                 checkpoint_cooldown: int = 2):
        if policy not in {"dense", "sparse", "hybrid"}:
            raise ValueError(f"unsupported verification policy {policy!r}")
        self.policy = policy
        self.repeated_action_threshold = max(2, int(repeated_action_threshold))
        self.same_subgoal_step_threshold = max(3, int(same_subgoal_step_threshold))
        self.high_risk_interval = max(1, int(high_risk_interval))
        self.medium_risk_interval = max(1, int(medium_risk_interval))
        self.checkpoint_cooldown = max(0, int(checkpoint_cooldown))
        self._action_counts: dict[str, tuple[dict | None, int]] = {}
        self._last_subgoal: str | None = None
        self._subgoal_steps = 0
        self._node_actions: dict[str, int] = {}
        self._last_checkpoint_step: dict[str, int] = {}
        self._step = 0

    # -- deterministic stagnation helpers ---------------------------------
    @staticmethod
    def _same_action(first, second) -> bool:
        return actions_equivalent(first, second)

    def _detect_repeated_action(self, subgoal_id: str, action: dict) -> bool:
        last, count = self._action_counts.get(subgoal_id, (None, 0))
        count = count + 1 if (last is not None and self._same_action(last, action)) else 1
        self._action_counts[subgoal_id] = (dict(action), count)
        if count >= self.repeated_action_threshold:
            self._action_counts.pop(subgoal_id, None)
            return True
        return False

    def _detect_long_subgoal(self, subgoal_id: str) -> bool:
        if subgoal_id != self._last_subgoal:
            self._last_subgoal = subgoal_id
            self._subgoal_steps = 1
        else:
            self._subgoal_steps += 1
        if self._subgoal_steps >= self.same_subgoal_step_threshold:
            self._subgoal_steps = 0
            return True
        return False

    # -- causal-risk helpers ---------------------------------------------
    def _risk_interval(self, risk: NodeRisk) -> int | None:
        if risk == NodeRisk.HIGH:
            return self.high_risk_interval
        if risk == NodeRisk.MEDIUM:
            return self.medium_risk_interval
        return None

    def _cooldown_ok(self, node_id: str) -> bool:
        last = self._last_checkpoint_step.get(node_id, -10**9)
        return (self._step - last) >= self.checkpoint_cooldown

    # -- unified entry ----------------------------------------------------
    def evaluate(self, proposal, task_state, graph, current_obs=None, previous_obs=None,
                 history=None, in_repair: bool = False,
                 repair_targets: set[str] | None = None) -> CheckpointDecision:
        self._step += 1
        repair_targets = repair_targets or set()
        node_id = proposal.subgoal_id

        # Layer A-2: final finish (always a checkpoint; rule-based verify_finish)
        if proposal.is_finish:
            return CheckpointDecision(True, "finish", node_id or None, "finish")

        # Layer A-1: subgoal completion / repair revalidation
        if proposal.subgoal_done:
            if node_id in repair_targets:
                return CheckpointDecision(True, "repair_revalidation", node_id, "repair")
            return CheckpointDecision(True, "subgoal_done", node_id, "completion")

        # dense: verify every action
        if self.policy == "dense":
            return CheckpointDecision(True, "dense", node_id, "completion")

        # Layer A-4: stagnation (repeated action / long same-subgoal wander)
        if self._detect_repeated_action(node_id, proposal.action) \
                or self._detect_long_subgoal(node_id):
            return CheckpointDecision(True, "stagnation", node_id, "consistency")

        # Layer B: causal-risk proactive checkpoints (hybrid only)
        if self.policy == "hybrid" and node_id:
            risk = compute_node_risk(task_state.get(node_id), graph)
            interval = self._risk_interval(risk)
            if interval is not None:
                actions = self._node_actions.get(node_id, 0) + 1
                self._node_actions[node_id] = actions
                if actions >= interval and self._cooldown_ok(node_id):
                    self._node_actions[node_id] = 0
                    self._last_checkpoint_step[node_id] = self._step
                    return CheckpointDecision(True, "causal_risk", node_id, "consistency")

        return CheckpointDecision(False, None, node_id, None)

    def mark_checkpoint(self, node_id: str) -> None:
        """Record a checkpoint so the cooldown applies to the next periodic
        hybrid check on this node (semantic-boundary checkpoints bypass the
        cooldown via evaluate())."""
        self._last_checkpoint_step[node_id] = self._step

    def discard_nodes(self, node_ids) -> None:
        """Drop scheduler memory for nodes removed by an accepted PlanPatch."""
        removed = set(node_ids)
        for values in (self._action_counts, self._node_actions,
                       self._last_checkpoint_step):
            for node_id in removed:
                values.pop(node_id, None)
        if self._last_subgoal in removed:
            self._last_subgoal = None
            self._subgoal_steps = 0

    def reset(self) -> None:
        self._action_counts.clear()
        self._subgoal_steps = 0
        self._node_actions.clear()
        self._last_checkpoint_step.clear()
        self._step = 0
