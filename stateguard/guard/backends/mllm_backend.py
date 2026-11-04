from __future__ import annotations

import json

from .base import GuardBackend
from ...core.dependency_graph import DependencyGraph
from ...training_logging import record_parse
from ..parser import parse_guard_output


def _observation_payload(observation):
    payload = dict(observation.to_dict())
    screenshot = payload.pop("screenshot", getattr(observation, "screenshot", None))
    payload["screenshot_ref"] = getattr(
        observation, "ref", f"obs@{payload.get('step', 'unknown')}")
    payload["has_screenshot"] = screenshot is not None
    return payload


def _causal_chain(task_state, active_node, candidate_nodes):
    """Compact state summary for the relevant causal chain (ancestors + active),
    in topological order. Works on the serialized state so any task_state-like
    object (VerifiedTaskState or test doubles) is supported."""
    nodes = task_state.serialize().get("nodes", {})
    if candidate_nodes is None:
        spec = [{"node_id": nid, "dependencies": n.get("dependencies", [])}
                for nid, n in nodes.items()]
        graph = DependencyGraph.from_spec(spec)
        candidate_nodes = graph.ancestors(active_node) + [active_node]
    chain = []
    for nid in candidate_nodes:
        n = nodes.get(nid, {})
        chain.append({
            "node_id": nid,
            "status": n.get("status", "pending"),
            "description": n.get("description", ""),
            "expected_state": n.get("expected_result_semantic") or n.get("expected_result", ""),
            "evidence": [e.get("description", "") for e in n.get("evidence", [])][-2:],
        })
    return chain


def _direct_successors(task_state, active_node):
    nodes = task_state.serialize().get("nodes", {})
    return [{
        "node_id": node_id,
        "status": node.get("status", "pending"),
        "description": node.get("description", ""),
        "expected_state": (
            node.get("expected_result_semantic") or node.get("expected_result", "")),
    } for node_id, node in nodes.items()
      if active_node in node.get("dependencies", [])]


def _execution_divergence_nodes(trace_window) -> set[str]:
    """Return nodes where the recorded action differs from executor intent."""
    diverged = set()
    for item in trace_window or []:
        value = item.to_dict() if hasattr(item, "to_dict") else item
        proposed = value.get("proposed_action")
        executed = value.get("action")
        if proposed is not None and executed is not None and proposed != executed:
            node_id = value.get("active_node_id")
            if node_id:
                diverged.add(node_id)
    return diverged


class GuardCallBudgetExceeded(RuntimeError):
    pass


class MLLMBackend(GuardBackend):
    def __init__(self, model_client, history=None, max_parse_retries: int = 1,
                 max_total_calls: int | None = None):
        self.model_client = model_client
        self.history, self.max_parse_retries = history, max_parse_retries
        self.calls = self.tokens = 0
        self.latency = 0.0
        self.parse_fail_open_count = 0
        self.strategy_normalization_count = 0
        self.progress_update_drop_count = 0
        self.max_total_calls = max_total_calls

    def _generate(self, messages, images=None, response_schema=None):
        if self.max_total_calls is not None and self.calls >= self.max_total_calls:
            raise GuardCallBudgetExceeded(
                f"Guard model call budget exhausted at {self.max_total_calls}")
        response = self.model_client.generate(messages, images, response_schema)
        self.calls += 1
        self.latency += response.latency_seconds
        self.tokens += sum((response.usage or {}).get(k, 0)
                           for k in ("prompt_tokens", "completion_tokens"))
        return response

    def verify(self, task_state, before, proposal, after, repair_context=None,
               checkpoint_kind: str = "completion", candidate_nodes=None):
        consistency = checkpoint_kind == "consistency"
        serialized_state = task_state.serialize()
        active_contract = serialized_state.get("nodes", {}).get(
            proposal.subgoal_id, {}).get("evidence_contract")
        causal_chain = _causal_chain(task_state, proposal.subgoal_id, candidate_nodes)
        successor_states = _direct_successors(task_state, proposal.subgoal_id)
        consistency_policy = (
            "This is a CONSISTENCY checkpoint: the active subgoal does NOT need to be "
            "completed yet; partial progress is normal. Return CONTRADICTED only when the "
            "observation provides positive evidence that the current task state or one of "
            "its causal prerequisites is no longer trustworthy. Otherwise return UNKNOWN."
            if consistency else
            "The proposal is one atomic action and a DAG node may require multiple actions. "
            "Judge the proposal's immediate expected_effect against the before/after images. "
            "Return verified only when the DAG node's expected result is visibly achieved. "
            "Return unknown, with a concrete verification_target, when the action is valid "
            "partial progress but the node is not complete yet. Return contradicted only when "
            "visible evidence shows a wrong target/value, no effect, dependency violation, or "
            "other state that requires rollback or repair. Never call incomplete but valid "
            "partial progress contradicted.")
        prompt = json.dumps({
            "task_dag": serialized_state, "proposal": proposal.to_dict(),
            "before": _observation_payload(before), "after": _observation_payload(after),
            "repair_context": repair_context.to_dict() if repair_context else None,
            "checkpoint_kind": checkpoint_kind,
            "causal_chain": causal_chain,
            "direct_successor_states": successor_states,
            "recent_history": self.history.recent() if self.history else [],
            "active_contract": active_contract,
            "instruction": ("Judge this transition once. Return JSON with judgement, "
                            "progress_updates, fault_root, fault_type, verification_target, reason, "
                            "unknown_reason, unknown_type, evidence_gap, and active_contract_id. "
                            "Do not return affected nodes. If contradicted, fault_root must be an "
                            "existing task node and fault_type must be one of missing_subgoal, "
                            "wrong_target, wrong_value, wrong_format, not_persisted, no_effect, "
                            "dependency_violation, premature_finish. Otherwise fault_root and "
                            "fault_type must be null. A progress update requires node_id, "
                            "status=verified, and visible evidence."),
            "unknown_policy": (
                "For UNKNOWN, unknown_reason must be exactly one of need_more_evidence, "
                "contract_stale, source_unavailable, verifier_inconclusive, node_unverifiable. "
                "Return evidence_gap with missing_evidence, available_evidence, "
                "unavailable_evidence, attempted_strategy, recommended_strategy, "
                "requires_new_source, and same_contract. Strategies are state-level only: "
                "acquire_visual_evidence, acquire_accessibility_evidence, "
                "acquire_structured_evidence, persistence_recheck, "
                "navigate_to_observable_state, external_state_query."),
            "unknown_type_policy": (
                "For UNKNOWN, unknown_type must be exactly one of evidence_insufficient, "
                "verification_target_unclear, hidden_or_persistent_state, "
                "contract_unverifiable, guard_capability_insufficient, or "
                "environment_state_missing. Use guard_capability_insufficient when the "
                "provided evidence already appears sufficient but you cannot reach a reliable "
                "judgement."),
            "judgement_contract": ("judgement must be exactly one of verified, contradicted, "
                                   "or unknown; do not use correct/incorrect labels."),
            "transition_policy": consistency_policy,
            "transient_state_policy": (
                "A navigation state such as an open menu, panel, or dialog may be transient. "
                "It is VERIFIED when the before image visibly proves it existed, or when the "
                "after image clearly shows a listed direct_successor_state that could only be "
                "reached through it. The active state does not need to remain visible after a "
                "successful transition. Verify only the active node; do not mark a successor "
                "verified unless it was itself the active proposal."),
            "causal_policy": (
                "An observed contradiction is NOT necessarily the causal root. Your task is "
                "not to identify where the problem became visible. Trace backward through the "
                "relevant causal_chain (which lists the causal prerequisites of the active "
                "node in dependency order) and identify the EARLIEST state whose corruption "
                "is sufficient to explain the current contradiction. A previously VERIFIED "
                "node may become untrustworthy if new evidence contradicts it. "
                "fault_root must be one of the nodes in causal_chain, or null."),
        }, default=str)
        images = [x for x in (before.screenshot, after.screenshot) if x]
        messages = [{"role": "user", "content": prompt}]
        error = None
        for _ in range(self.max_parse_retries + 1):
            response = self._generate(messages, images, response_schema={
                "type": "object",
                "required": ["judgement"],
                "properties": {
                    "judgement": {"type": "string"},
                    "verification_target": {"type": ["string", "null"]},
                    "unknown_reason": {"type": ["string", "null"]},
                    "unknown_type": {"type": ["string", "null"]},
                    "evidence_gap": {"type": ["object", "null"]},
                },
            })
            try:
                result = parse_guard_output(response.parsed)
                gap = result.evidence_gap or {}
                self.strategy_normalization_count += sum(
                    key in gap for key in (
                        "raw_attempted_strategy", "raw_recommended_strategy"))
                if result.fault_root:
                    allowed = set(candidate_nodes) if candidate_nodes else set(task_state.nodes)
                    if result.fault_root not in task_state or result.fault_root not in allowed:
                        raise ValueError(
                            f"fault_root {result.fault_root} outside the causal candidate set")
                valid_updates = []
                ignored_updates = []
                for update in result.progress_updates:
                    if not isinstance(update, dict):
                        ignored_updates.append("progress update is not an object")
                        continue
                    if update.get("node_id") not in task_state:
                        ignored_updates.append(
                            f"unknown progress node {update.get('node_id')}")
                        continue
                    evidence = update.get("evidence") or update.get("visual_evidence")
                    if update.get("status") != "verified" or not evidence:
                        ignored_updates.append(
                            f"invalid progress update for {update.get('node_id')}")
                        continue
                    if isinstance(evidence, list):
                        evidence = " ".join(str(item) for item in evidence)
                    elif not isinstance(evidence, str):
                        evidence = str(evidence)
                    update["evidence"] = evidence
                    valid_updates.append(update)
                result.progress_updates = valid_updates
                if ignored_updates:
                    self.progress_update_drop_count += len(ignored_updates)
                    warning = "Ignored unsafe progress metadata: " + "; ".join(ignored_updates)
                    result.reason = f"{result.reason} {warning}".strip()
                record_parse(self.model_client, "completed", result.to_dict())
                return result
            except ValueError as exc:
                record_parse(self.model_client, "failed", response.parsed, exc)
                error = exc
                messages.extend([
                    {"role": "assistant", "content": response.text},
                    {"role": "user", "content":
                        f"Invalid Guard JSON: {exc}. Correct the previous JSON and return JSON only."},
                ])
        self.parse_fail_open_count += 1
        result = _inconclusive_guard_result(error)
        record_parse(self.model_client, "fallback", result.to_dict(), error)
        return result

    def diagnose_candidates(self, task_state, before, proposal, after, candidate_nodes,
                            trace_window=None):
        """Stage 2: judge candidate state trust independently of fault visibility."""
        divergence_nodes = _execution_divergence_nodes(trace_window)
        if divergence_nodes:
            return {
                node_id: "NO" if node_id in divergence_nodes else "YES"
                for node_id in candidate_nodes
            }
        chain = _causal_chain(task_state, proposal.subgoal_id, candidate_nodes)
        prompt = json.dumps({
            "active_node": proposal.subgoal_id,
            "candidate_states": chain,
            "observation_before": _observation_payload(before),
            "observation_after": _observation_payload(after),
            "causal_trace_window": [
                item.to_dict() if hasattr(item, "to_dict") else item
                for item in (trace_window or [])
            ],
            "instruction": (
                "For EACH candidate state, audit both its HISTORICAL TRANSITION INTEGRITY "
                "and its current visible state. Return one JSON object named "
                "trust_judgements whose keys are exactly the candidate node IDs and values "
                "are YES or NO. In causal_trace_window, proposed_action is what the executor "
                "intended and action is what was actually sent to the environment. Return NO "
                "when these differ materially for that node, or when the immediate screenshots "
                "or trace affirmatively contradict its expected effect. A later successful "
                "retry does not erase a recorded execution-integrity failure: the question is "
                "whether this node ever contains the earliest observable corrupted transition. "
                "A state that is merely not visible remains YES. Judge nodes independently; "
                "do not choose only the downstream location where failure became visible."
            ),
        }, default=str)
        images = [image for image in (before.screenshot, after.screenshot) if image]
        response = self._generate(
            [{"role": "user", "content": prompt}], images,
            response_schema={"type": "object"})
        parsed = response.parsed or {}
        values = parsed.get("trust_judgements", parsed)
        if not isinstance(values, dict):
            raise ValueError("candidate diagnosis must return a JSON object")
        result = {}
        for node_id in candidate_nodes:
            value = str(values.get(node_id, "")).strip().upper()
            if value not in {"YES", "NO"}:
                raise ValueError(f"candidate diagnosis missing YES/NO for {node_id}")
            result[node_id] = value
        record_parse(self.model_client, "completed", result)
        return result


def _inconclusive_guard_result(error) -> object:
    from ...core.schema import GuardResult
    return GuardResult(
        "unknown",
        verification_target="Acquire fresh evidence and retry verification.",
        reason=f"Guard response could not be parsed safely: {error}",
        unknown_reason="verifier_inconclusive",
        evidence_gap={
            "missing_evidence": ["a parseable verifier judgement"],
            "available_evidence": [],
            "unavailable_evidence": [],
            "attempted_strategy": None,
            "recommended_strategy": "acquire_visual_evidence",
            "requires_new_source": False,
            "same_contract": True,
        },
    )
