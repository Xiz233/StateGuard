"""Ground immutable semantic goals into evidence available in the current UI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..core.schema import TaskNode
from ..environment.capabilities import EnvironmentCapabilities
from ..training_logging import record_parse
from .contracts import (
    AdaptiveEvidenceContract, ContractProvenance, EvidenceSource, EvidenceType,
    ObservableClaim,
)
from .observation import ObservationBundle


class GroundingTrigger(str, Enum):
    NODE_ACTIVATED = "node_activated"
    PREVIOUS_NODE_VERIFIED = "previous_node_verified"
    CONTEXT_SHIFT = "context_shift"
    CONTRACT_STALE = "contract_stale"
    REPEATED_UNKNOWN = "repeated_unknown"
    EVIDENCE_SOURCE_FAILURE = "evidence_source_failure"
    POST_REPAIR_REVALIDATION = "post_repair_revalidation"
    LOCAL_REPLAN = "local_replan"


@dataclass(frozen=True)
class GroundingResult:
    contract: AdaptiveEvidenceContract | None
    reason: str = ""

    @property
    def groundable(self) -> bool:
        return self.contract is not None


class GroundingProvider(Protocol):
    def ground(self, *, node: TaskNode, observation: ObservationBundle,
               capabilities: EnvironmentCapabilities,
               previous_contract: AdaptiveEvidenceContract | None,
               trigger: GroundingTrigger, trace_summary=None) -> dict: ...


class VerificationGrounder:
    """Uses an optional model provider, with a conservative deterministic fallback."""

    def __init__(self, provider: GroundingProvider | None = None):
        self.provider = provider

    @staticmethod
    def is_feasible(node: TaskNode,
                    capabilities: EnvironmentCapabilities) -> bool:
        """Cheap preflight: require one theoretical source/verifier path."""
        intent = node.verification_intent
        preferred = tuple(
            intent.preferred_evidence_types if intent else (node.evidence_mode,))
        source = _choose_source(preferred, capabilities, node.semantic_goal.invariant)
        if source == EvidenceSource.EXTERNAL_TOOL and not node.verify_action:
            source = (EvidenceSource.SCREENSHOT
                      if EvidenceSource.SCREENSHOT in capabilities.available_sources else None)
        return source is not None and _verifier_for(source, capabilities) is not None

    def ground(self, node: TaskNode, observation: ObservationBundle,
               capabilities: EnvironmentCapabilities,
               previous_contract: AdaptiveEvidenceContract | None = None,
               trigger: GroundingTrigger = GroundingTrigger.NODE_ACTIVATED,
               trace_summary=None,
               excluded_sources: frozenset[EvidenceSource] = frozenset()) \
            -> GroundingResult:
        observation = (observation if isinstance(observation, ObservationBundle)
                       else ObservationBundle.from_observation(observation))
        if self.provider:
            try:
                raw = self.provider.ground(
                    node=node, observation=observation, capabilities=capabilities,
                    previous_contract=previous_contract, trigger=trigger,
                    trace_summary=trace_summary)
                raw = _unwrap_grounding_response(raw)
                if raw.get("ungroundable"):
                    if self.is_feasible(node, capabilities):
                        return self._deterministic(
                            node, observation, capabilities, previous_contract, trigger,
                            excluded_sources)
                    return GroundingResult(
                        None, str(raw.get("reason", "grounder reported ungroundable")))
                return self._from_hints(
                    node, observation, capabilities, previous_contract, raw,
                    excluded_sources)
            except (KeyError, TypeError, ValueError) as exc:
                return GroundingResult(None, f"grounder returned invalid hints: {exc}")
        return self._deterministic(
            node, observation, capabilities, previous_contract, trigger,
            excluded_sources)

    @staticmethod
    def _from_hints(node, observation, capabilities, previous, raw,
                    excluded_sources=frozenset()):
        """Bind model grounding hints to the immutable local semantic goal."""
        raw = _unwrap_grounding_response(raw)
        proposed_sources = raw.get("evidence_sources", raw.get("sources", ()))
        if isinstance(proposed_sources, str):
            proposed_sources = (proposed_sources,)
        sources = tuple(filter(None, (
            _normalise_source(value) for value in proposed_sources
        )))
        source = next((value for value in sources
                       if value in capabilities.available_sources
                       and value not in excluded_sources
                       and _verifier_for(value, capabilities)), None)
        if source is None:
            intent = node.verification_intent
            preferred = tuple(
                intent.preferred_evidence_types if intent else (node.evidence_mode,))
            source = _choose_source(
                preferred, capabilities, node.semantic_goal.invariant,
                excluded_sources)
        if source == EvidenceSource.EXTERNAL_TOOL and not node.verify_action:
            source = (EvidenceSource.SCREENSHOT
                      if EvidenceSource.SCREENSHOT in capabilities.available_sources else None)
        if source is None:
            return GroundingResult(None, "no available source can satisfy grounding hints")

        verifier = _verifier_for(source, capabilities)
        if verifier is None:
            return GroundingResult(None, f"no verifier is available for {source.value}")
        return GroundingResult(_build_contract(
            node=node,
            observation=observation,
            previous=previous,
            source=source,
            verifier=verifier,
            ui_anchor=raw.get("ui_anchor"),
            fallback_strategy=raw.get("fallback_strategy"),
            confidence=raw.get("confidence"),
        ))

    @staticmethod
    def _deterministic(node, observation, capabilities, previous, trigger,
                       excluded_sources=frozenset()):
        intent = node.verification_intent
        preferred = tuple(intent.preferred_evidence_types if intent else (node.evidence_mode,))
        source = _choose_source(
            preferred, capabilities, node.semantic_goal.invariant,
            excluded_sources)
        if source == EvidenceSource.EXTERNAL_TOOL and not node.verify_action:
            source = (EvidenceSource.SCREENSHOT
                      if EvidenceSource.SCREENSHOT in capabilities.available_sources else None)
        if source is None:
            return GroundingResult(None, "no available source can satisfy verification intent")
        verifier = _verifier_for(source, capabilities)
        if verifier is None:
            return GroundingResult(None, f"no verifier is available for {source.value}")
        return GroundingResult(_build_contract(
            node=node, observation=observation, previous=previous,
            source=source, verifier=verifier))


def context_signature(observation: ObservationBundle) -> dict:
    tree = observation.accessibility_tree
    tree_digest = hashlib.sha256(
        json.dumps(tree, sort_keys=True, default=str).encode()).hexdigest()[:16] if tree else None
    return {
        "active_app": (observation.app_state or {}).get("active_app"),
        "window": observation.metadata.get("window_title"),
        "page": observation.metadata.get("page") or observation.metadata.get("url"),
        "modal": observation.metadata.get("modal"),
        "a11y_root_hash": tree_digest,
    }


def _choose_source(preferred, capabilities, invariant, excluded_sources=frozenset()):
    mapping = {
        "structured": EvidenceSource.STRUCTURED_STATE,
        "accessibility": EvidenceSource.ACCESSIBILITY_TREE,
        "persistence": EvidenceSource.EXTERNAL_TOOL,
        "visual": EvidenceSource.SCREENSHOT,
        "hybrid": EvidenceSource.ACCESSIBILITY_TREE,
    }
    candidates = [mapping.get(value) for value in preferred]
    candidates += [EvidenceSource.STRUCTURED_STATE, EvidenceSource.ACCESSIBILITY_TREE,
                   EvidenceSource.EXTERNAL_TOOL, EvidenceSource.SCREENSHOT]
    machine_predicate = isinstance(invariant, dict) and {
        "field", "operator", "value"} <= invariant.keys()
    if not machine_predicate:
        candidates = [source for source in candidates
                      if source not in {EvidenceSource.STRUCTURED_STATE,
                                        EvidenceSource.APP_STATE,
                                        EvidenceSource.ACCESSIBILITY_TREE}]
    return next((source for source in candidates
                 if source and source in capabilities.available_sources
                 and source not in excluded_sources), None)


def _verifier_for(source, capabilities):
    value = {
        EvidenceSource.STRUCTURED_STATE: "structured_predicate",
        EvidenceSource.APP_STATE: "structured_predicate",
        EvidenceSource.ACCESSIBILITY_TREE: "accessibility_predicate",
        EvidenceSource.EXTERNAL_TOOL: "persistence",
        EvidenceSource.SCREENSHOT: "visual_mllm",
    }.get(source)
    return value if value in capabilities.supported_verifiers else None


def _type_for(source):
    return {
        EvidenceSource.STRUCTURED_STATE: EvidenceType.STRUCTURED,
        EvidenceSource.APP_STATE: EvidenceType.STRUCTURED,
        EvidenceSource.EXTERNAL_TOOL: EvidenceType.PERSISTENCE,
        EvidenceSource.ACCESSIBILITY_TREE: EvidenceType.STRUCTURED,
        EvidenceSource.SCREENSHOT: EvidenceType.VISUAL,
    }[source]


def _predicate_for(invariant):
    if not isinstance(invariant, dict):
        return None
    if {"field", "operator", "value"} <= invariant.keys():
        return {key: invariant[key] for key in ("field", "operator", "value")}
    return None


def _build_contract(*, node, observation, previous, source, verifier,
                    ui_anchor=None, fallback_strategy=None, confidence=None):
    goal = node.semantic_goal
    invariant = goal.invariant
    if isinstance(invariant, dict) and {"relation", "operator", "value"} <= invariant.keys():
        relation = str(invariant["relation"])
        operator = str(invariant["operator"])
        expected = invariant["value"]
        subject = invariant.get("subject")
    else:
        relation, operator, expected, subject = (
            f"semantic_goal:{node.node_id}", "satisfies", invariant, None)
    version = previous.version + 1 if previous else 1
    try:
        confidence = max(0.0, min(1.0, float(confidence))) \
            if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return AdaptiveEvidenceContract(
        contract_id=f"{node.node_id}-c{version}",
        node_id=node.node_id,
        version=version,
        semantic_goal_ref=goal.reference,
        grounded_at_step=observation.step,
        context_signature=context_signature(observation),
        evidence_type=_type_for(source),
        sources=(source,),
        observable_claims=(ObservableClaim(
            claim_id=f"{node.node_id}-claim",
            semantic_relation=relation,
            subject=subject,
            operator=operator,
            expected_value=expected,
            ui_anchor=ui_anchor if isinstance(ui_anchor, dict) else None,
            source_preference=(source,),
        ),),
        verifier_candidates=(verifier,),
        preferred_verifier=verifier,
        verifier_id=verifier,
        predicate=_predicate_for(invariant),
        verify_action=node.verify_action,
        success_condition=invariant,
        allow_mllm_fallback=source == EvidenceSource.SCREENSHOT,
        fallback_strategy=(str(fallback_strategy) if fallback_strategy
                           else "navigate_to_observable_state"),
        confidence=confidence,
        provenance=(ContractProvenance.REGROUNDER if previous
                    else ContractProvenance.GROUNDER),
    )


def _unwrap_grounding_response(value):
    if isinstance(value, list):
        if not value:
            raise ValueError("empty grounding response")
        value = value[0]
    if not isinstance(value, dict):
        raise TypeError("grounding response must be an object")
    for key in ("grounding", "grounding_hints", "contract"):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value


def _normalise_source(value):
    aliases = {
        "screenshot": EvidenceSource.SCREENSHOT,
        "visual": EvidenceSource.SCREENSHOT,
        "image": EvidenceSource.SCREENSHOT,
        "accessibility": EvidenceSource.ACCESSIBILITY_TREE,
        "accessibility_tree": EvidenceSource.ACCESSIBILITY_TREE,
        "a11y": EvidenceSource.ACCESSIBILITY_TREE,
        "structured": EvidenceSource.STRUCTURED_STATE,
        "structured_state": EvidenceSource.STRUCTURED_STATE,
        "app_state": EvidenceSource.APP_STATE,
        "external_tool": EvidenceSource.EXTERNAL_TOOL,
        "persistence": EvidenceSource.EXTERNAL_TOOL,
        "clipboard": EvidenceSource.CLIPBOARD,
    }
    return aliases.get(str(value).strip().lower())


class MLLMGroundingProvider:
    def __init__(self, model_client):
        self.model_client = model_client
        self.calls = self.tokens = 0
        self.latency = 0.0

    def ground(self, *, node, observation, capabilities, previous_contract,
               trigger, trace_summary=None) -> dict:
        payload = {
            "semantic_goal": node.semantic_goal.to_dict(),
            "semantic_goal_ref": node.semantic_goal.reference,
            "verification_intent": node.verification_intent.to_dict(),
            "current_observation": {
                "step": observation.step,
                "accessibility_tree": observation.accessibility_tree,
                "structured_state": observation.structured_state,
                "app_state": observation.app_state,
                "metadata": observation.metadata,
                "has_screenshot": observation.screenshot is not None,
            },
            "environment_capabilities": capabilities.to_dict(),
            "previous_contract": previous_contract.to_dict() if previous_contract else None,
            "trigger": trigger.value,
            "trace_summary": trace_summary,
            "instruction": (
                "Identify how the existing goal can be observed in the CURRENT environment. "
                "Do not rewrite the semantic goal, decide completion, or emit task GUI actions. "
                "Return grounding hints only: evidence_sources, ui_anchor, fallback_strategy, "
                "and confidence. Use only sources listed in environment_capabilities. If no "
                "reliable route can ever verify the goal after task execution, return "
                "ungroundable=true and a reason. A target not being visible yet is not "
                "ungroundable: choose a usable source and a navigation fallback. The runtime "
                "constructs and validates the immutable evidence contract locally."),
        }
        images = [observation.screenshot] if observation.screenshot else None
        response = self.model_client.generate(
            [{"role": "user", "content": json.dumps(payload, default=str)}],
            images, response_schema={
                "type": "object",
                "properties": {
                    "ungroundable": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "evidence_sources": {
                        "type": "array", "items": {"type": "string"}},
                    "ui_anchor": {"type": ["object", "null"]},
                    "fallback_strategy": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
            })
        self.calls += 1
        self.latency += getattr(response, "latency_seconds", 0.0)
        self.tokens += sum((response.usage or {}).get(key, 0)
                           for key in ("prompt_tokens", "completion_tokens"))
        try:
            result = _unwrap_grounding_response(response.parsed or {})
        except (KeyError, TypeError, ValueError) as exc:
            record_parse(self.model_client, "failed", response.parsed, exc)
            raise
        record_parse(self.model_client, "completed", result)
        return result
