"""StateGuard: the single intelligent module (指引.txt §4/5/18/19/20).

verify_transition() / verify_finish() return GuardResult with:
  - §19 JSON schema (judgement, progress_updates, fault_root, fault_type, repair)
  - state_updates for task_state.apply()
  - requires_repair flag driving the runtime loop

Localization runs on a projected clone (updates applied) so the observed
node's status is already EXECUTED when classifying.
"""

from __future__ import annotations

from ..core.schema import (NodeStatus, GuardResult, FaultType, ActionProposal)
from ..core.task_state import VerifiedTaskState
from ..core.dependency_graph import DependencyGraph
from ..interfaces.observation import Observation
from .verifier import verify_transition as _verify
from .localization import causal_root
from .parser import check_effect, resolve_effect, predicate_violated
from .repair import propagate_failure, build_repair_request


class StateGuard:
    def __init__(self, backend=None):
        # ponytail: rule-based only in Phase I; swap per prompts.py when
        # learned versions land.
        self.localize = causal_root
        self.backend = backend

    def verify_transition(self, task_state: VerifiedTaskState,
                          before: Observation, proposal: ActionProposal,
                          after: Observation) -> GuardResult:
        if proposal.is_finish:
            return self.verify_finish(task_state, after)

        if proposal.subgoal_id not in task_state:
            return GuardResult(
                judgement="unknown",
                verification_target=f"register unknown subgoal {proposal.subgoal_id}",
            )

        node = task_state.get(proposal.subgoal_id)
        graph = DependencyGraph.from_state(task_state)

        # dependency guard: never act on unverified prerequisites (§25)
        for p in graph.parents(node.node_id):
            if task_state.get(p).status != NodeStatus.VERIFIED:
                updates = self._start_updates(node)
                ftype = FaultType.MISSING_SUBGOAL.value \
                    if task_state.get(p).status == NodeStatus.PENDING \
                    else FaultType.DEPENDENCY_VIOLATION.value
                projected = self._project(task_state, updates)
                return self._contradicted(projected,
                                          DependencyGraph.from_state(projected),
                                          p, updates, ftype)

        updates = self._start_updates(node)

        verdict = (self.backend.verify(task_state, before, proposal, after)
                   if self.backend else _verify(node, proposal, before, after))

        model_verdict = hasattr(verdict, "progress_updates")
        if model_verdict and verdict.judgement == "contradicted":
            root = verdict.fault_root or node.node_id
            projected = self._project(task_state, updates)
            return self._contradicted(projected, DependencyGraph.from_state(projected),
                                      root, updates, verdict.fault_type or FaultType.NO_EFFECT.value)
        if model_verdict and verdict.judgement == "verified":
            evidence_text = next((u.get("evidence") for u in verdict.progress_updates
                                  if u.get("node_id") == node.node_id), verdict.reason)
            from ..core.schema import Evidence
            evidence = Evidence(after.step, "guard_model", evidence_text or node.description,
                                0.8, after.ref)
            updates.append({"op": "verify", "node_id": node.node_id,
                            "evidence": evidence.to_dict()})
            return GuardResult("verified", progress_updates=verdict.progress_updates,
                               state_updates=updates, reason=verdict.reason)

        if verdict.judgement == "unknown":
            hit = self._sweep(self._project(task_state, updates), after)
            if hit is None:
                return GuardResult("unknown", state_updates=updates,
                                   verification_target=verdict.verification_target)
            return self._contradict_via(hit, task_state, updates, after)

        if verdict.judgement == "contradicted":
            check_result = check_effect(
                resolve_effect(node.expected_effect,
                               proposal.action.get("params", proposal.action)
                               if isinstance(proposal.action, dict) else proposal.action.params),
                after.snapshot,
            )
            return self._contradict_via(node.node_id, task_state, updates, after,
                                        check_result)

        # verified: consistency sweep (on the projected state *including* the
        # verify op) enforces the node's own expected_result before it is
        # allowed to become VERIFIED (§5.2 example)
        verify_op = {"op": "verify", "node_id": node.node_id,
                     "evidence": verdict.evidence.to_dict()}
        hit = self._sweep(self._project(task_state, updates + [verify_op]), after)
        if hit is not None:
            return self._contradict_via(hit, task_state, updates, after)
        updates.append(verify_op)
        return GuardResult("verified", state_updates=updates)

    def verify_finish(self, task_state: VerifiedTaskState,
                      observation: Observation) -> GuardResult:
        if task_state.can_finish():
            return GuardResult("verified", approved=True)

        # FINISH rejected (指引.txt §17): localize first incomplete node.
        # No status changes: PENDING nodes are simply still missing.
        graph = DependencyGraph.from_state(task_state)
        order = graph.topological_order()
        incomplete = [nid for nid in order if nid in task_state.incomplete_required_nodes()]
        root = incomplete[0]
        affected = graph.affected_set(root)
        preserve = sorted(n for n in order
                          if task_state.get(n).status == NodeStatus.VERIFIED
                          and n not in affected)
        reverify = [nid for nid in affected
                    if task_state.get(nid).status != NodeStatus.VERIFIED]
        stale = [nid for nid in affected
                 if task_state.get(nid).status == NodeStatus.STALE]
        goal = (f"Task is not complete: {root} still requires "
                f"{task_state.get(root).description}.")
        repair = build_repair_request(task_state, graph, root,
                                      FaultType.PREMATURE_FINISH.value, 0.9)
        repair.goal = goal
        repair.preserve_nodes = preserve
        repair.stale_nodes = stale
        repair.reverify_nodes = reverify
        return GuardResult("contradicted", fault_root=root,
                           fault_type=FaultType.PREMATURE_FINISH.value,
                           repair=repair)

    # -- internals --------------------------------------------------------
    @staticmethod
    def _start_updates(node) -> list[dict]:
        """PENDING/FAILED/STALE nodes reactivate via ACTIVE before EXECUTED
        (repair loop re-executes FAILED/STALE targets). An already-EXECUTED
        node (UNKNOWN -> reopen) emits nothing."""
        updates = []
        if node.status in (NodeStatus.PENDING, NodeStatus.FAILED,
                           NodeStatus.STALE):
            updates.append({"op": "active", "node_id": node.node_id})
        if node.status != NodeStatus.EXECUTED:
            updates.append({"op": "execute", "node_id": node.node_id})
        return updates

    def _contradict_via(self, hit: str, task_state: VerifiedTaskState,
                        updates: list[dict], after: Observation,
                        check_result: str | None = None) -> GuardResult:
        projected = self._project(task_state, updates)
        graph = DependencyGraph.from_state(projected)
        root, ftype, conf = causal_root(projected, graph, hit, after, check_result)
        return self._contradicted(projected, graph, root, updates, ftype, conf)

    def _contradicted(self, state: VerifiedTaskState, graph: DependencyGraph,
                      root: str, updates: list[dict], ftype: str,
                      confidence: float = 0.7) -> GuardResult:
        # propagation runs on the projected clone to compute stale set and
        # repair scope; the real state applies `updates` afterwards.
        stale = propagate_failure(state, graph, root)
        if state.get(root).status != NodeStatus.PENDING:
            updates.append({"op": "fail", "node_id": root})
        updates.append({"op": "stale", "node_ids": stale})
        repair = build_repair_request(state, graph, root, ftype, confidence)
        return GuardResult("contradicted", fault_root=root, fault_type=ftype,
                           repair=repair, state_updates=updates)

    @staticmethod
    def _project(task_state: VerifiedTaskState, updates: list[dict]) -> VerifiedTaskState:
        clone = VerifiedTaskState.deserialize(task_state.serialize())
        clone.apply(updates)
        return clone

    @staticmethod
    def _sweep(state: VerifiedTaskState, obs: Observation) -> str | None:
        """Earliest VERIFIED node whose expected_result is contradicted by
        the current observation (detects faults at their true source)."""
        for nid in DependencyGraph.from_state(state).topological_order():
            node = state.get(nid)
            if node.status == NodeStatus.VERIFIED \
                    and predicate_violated(node.expected_result, obs.snapshot):
                return nid
        return None
