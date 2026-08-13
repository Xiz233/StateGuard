"""Spec-driven executor for the synthetic tasks (runtime loop 指引.txt §18).

`hints` model buggy agent behavior for fault injection:
  skip             -> node treated as satisfied without ever executing it
  ignore_unknown   -> EXECUTED (unverified) parents treated as satisfied
  premature_finish -> FINISH proposed when only the last node is incomplete
Hints are dropped at the first repair: the agent "fixes its behavior".
"""

from __future__ import annotations

from stateguard.core.schema import ActionProposal
from stateguard.core.task_state import VerifiedTaskState
from stateguard.core.dependency_graph import DependencyGraph
from stateguard.interfaces.action import Action
from stateguard.interfaces.observation import Observation


class SpecExecutor:
    def __init__(self, spec: dict, hints: dict | None = None):
        self.spec = spec
        self.hints = hints or {}
        self._fault_dropped = False

    def act(self, observation: Observation, task_state: VerifiedTaskState,
            repair_context) -> ActionProposal | None:
        graph = DependencyGraph.from_state(task_state)
        if repair_context is not None and not self._fault_dropped:
            self._fault_dropped = True  # repair = agent fixes its behavior

        if repair_context is not None:
            # steer by the repair target while any reverify node is incomplete
            for nid in graph.topological_order():
                if nid in repair_context.reverify_nodes \
                        and task_state.get(nid).status != _VERIFIED():
                    if task_state.get(nid).status == _EXECUTED() \
                            and self._verify_action(nid):
                        return self._propose(nid, observation, reopen=True)
                    return self._propose(nid, observation)

        if self._premature_finish(task_state, graph):
            return ActionProposal(subgoal_id="", action=Action("__finish__", {}),
                                  is_finish=True)

        # normal loop: next incomplete node whose prerequisites are satisfied
        for nid in graph.topological_order():
            node = task_state.get(nid)
            if node.status == _VERIFIED():
                continue
            if node.status == _EXECUTED():
                if nid in self.hints.get("ignore_unknown", []):
                    continue  # fault: unverified subgoal treated as done
                if self._verify_action(nid):
                    return self._propose(nid, observation, reopen=True)
                # ponytail: EXECUTED without a verify_action re-executes to
                # obtain fresh evidence (can happen when a sweep-contradiction
                # at a sibling's step left this node mid-flight)
                return self._propose(nid, observation)
            if not self._parents_ok(nid, task_state, graph):
                continue
            if nid in self.hints.get("skip", []):
                continue
            return self._propose(nid, observation)

        if self._premature_finish(task_state, graph):
            return ActionProposal(subgoal_id="", action=Action("__finish__", {}),
                                  is_finish=True)
        if task_state.can_finish():
            return ActionProposal(subgoal_id="", action=Action("__finish__", {}),
                                  is_finish=True)
        return None
    def fix(self, fixes: dict) -> None:
        """Restore original action_params on the faulted spec (repair step)."""
        for nid, params in fixes.get("params", {}).items():
            for n in self.spec["nodes"]:
                if n["node_id"] == nid:
                    n["action_params"] = params

    # -- internals ---------------------------------------------------------
    def _propose(self, nid: str, observation: Observation, reopen: bool = False) -> ActionProposal:
        spec_node = next(n for n in self.spec["nodes"] if n["node_id"] == nid)
        params = {}
        for p, source in spec_node.get("action_params", {}).items():
            if source.get("from"):
                params[p] = observation.get(source["from"])
            else:
                params[p] = source["lit"]
        if reopen:
            # reopen must re-check the intended value, so it carries the same
            # params as the original action (ponytail: symbolic env ignores them)
            action = Action(spec_node["verify_action"], params)
        else:
            action = Action(spec_node["action"], params)
        return ActionProposal(subgoal_id=nid, action=action,
                              intent=spec_node["description"])

    def _parents_ok(self, nid: str, task_state: VerifiedTaskState,
                    graph: DependencyGraph) -> bool:
        skip = self.hints.get("skip", [])
        for p in graph.parents(nid):
            st = task_state.get(p).status
            if st == _VERIFIED():
                continue
            if p in skip:
                continue  # fault: skipped subgoal treated as done
            if st == _EXECUTED() and p in self.hints.get("ignore_unknown", []):
                continue  # fault: unverified parent treated as done
            return False
        return True

    def _verify_action(self, nid: str) -> str | None:
        spec_node = next(n for n in self.spec["nodes"] if n["node_id"] == nid)
        return spec_node.get("verify_action")

    def _premature_finish(self, task_state: VerifiedTaskState,
                          graph: DependencyGraph) -> bool:
        if not self.hints.get("premature_finish") or self._fault_dropped:
            return False
        order = graph.topological_order()
        incomplete = task_state.incomplete_required_nodes()
        return len(incomplete) == 1 and incomplete[0] == order[-1]


def _VERIFIED():
    from stateguard.core.schema import NodeStatus
    return NodeStatus.VERIFIED


def _EXECUTED():
    from stateguard.core.schema import NodeStatus
    return NodeStatus.EXECUTED
