"""Append-only raw evidence logging for training-ready rollouts."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import mimetypes
from pathlib import Path
import time
from typing import Any
import uuid

from .models.base import ModelResponse, MultimodalModelClient


_CURRENT_EVENT_ID: ContextVar[str | None] = ContextVar(
    "stateguard_training_event_id", default=None)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serializable(value: Any) -> Any:
    if is_dataclass(value):
        return _serializable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serializable(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict"):
        return _serializable(value.to_dict())
    return str(value)


def normalized_state_delta(before: dict | None, after: dict | None) -> dict:
    before_nodes = (before or {}).get("nodes", {})
    after_nodes = (after or {}).get("nodes", {})
    changed = {}
    for node_id in sorted(set(before_nodes) | set(after_nodes)):
        old = before_nodes.get(node_id)
        new = after_nodes.get(node_id)
        if old == new:
            continue
        changed[node_id] = {
            "before_status": old.get("status") if isinstance(old, dict) else None,
            "after_status": new.get("status") if isinstance(new, dict) else None,
            "before_trust": old.get("trust_score") if isinstance(old, dict) else None,
            "after_trust": new.get("trust_score") if isinstance(new, dict) else None,
            "added": old is None,
            "removed": new is None,
        }
    newly_achieved = [node_id for node_id, value in changed.items()
                      if value["after_status"] == "verified"
                      and value["before_status"] != "verified"]
    broken = [node_id for node_id, value in changed.items()
              if value["after_status"] in {"failed", "stale", "unverifiable"}
              and value["before_status"] not in {"failed", "stale", "unverifiable"}]
    suspicious = [node_id for node_id, value in changed.items()
                  if value["after_status"] == "suspicious"
                  and value["before_status"] != "suspicious"]
    preserved = [node_id for node_id in sorted(set(before_nodes) & set(after_nodes))
                 if before_nodes[node_id].get("status") == "verified"
                 and after_nodes[node_id].get("status") == "verified"]
    return {
        "changed_nodes": changed,
        "newly_achieved": newly_achieved,
        "broken": broken,
        "suspicious": suspicious,
        "preserved": preserved,
    }


class TrainingReadyLogger:
    """Writes v1 evidence beside legacy episode artifacts without replacing them."""

    schema_version = "stateguard.training_events.v1"

    def __init__(self, episode_dir: str | Path, save_model_responses: bool = True):
        self.episode_dir = Path(episode_dir)
        self.artifact_dir = self.episode_dir / "artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.save_model_responses = bool(save_model_responses)
        self._event_sequence = 0
        self._call_sequence = 0
        self._intervention_sequence = 0
        self._open_interventions: list[str] = []
        self._open_unknowns: dict[str, dict] = {}
        self._event_steps: dict[str, int | None] = {}
        self._event_states: dict[str, dict | None] = {}
        self._known_artifacts: set[str] = set()
        self._append("events.jsonl", {
            "schema_version": self.schema_version,
            "event_type": "episode_logging_started",
            "event_id": self._new_event_id(),
            "timestamp": _utcnow(),
            "save_model_responses": self.save_model_responses,
        })

    def _append(self, name: str, value: dict) -> None:
        with (self.episode_dir / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_serializable(value), default=str) + "\n")

    def _new_event_id(self) -> str:
        self._event_sequence += 1
        return f"evt-{self._event_sequence:06d}"

    def new_call_id(self, role: str) -> str:
        self._call_sequence += 1
        return f"call-{role}-{self._call_sequence:06d}"

    @contextmanager
    def bind_event(self, event_id: str | None):
        token = _CURRENT_EVENT_ID.set(event_id)
        try:
            yield
        finally:
            _CURRENT_EVENT_ID.reset(token)

    def start_event(self, event_type: str, step_id: int | None,
                    state_before: dict | None = None, **payload) -> str:
        event_id = self._new_event_id()
        self._event_steps[event_id] = step_id
        self._event_states[event_id] = state_before
        self._append("events.jsonl", {
            "schema_version": self.schema_version,
            "event_id": event_id,
            "event_type": event_type,
            "event_phase": "started",
            "step_id": step_id,
            "timestamp": _utcnow(),
            "task_state_before": state_before,
            **payload,
        })
        return event_id

    def finish_event(self, event_id: str, event_type: str, step_id: int | None,
                     state_before: dict | None, state_after: dict | None,
                     status: str = "completed", **payload) -> None:
        self._append("events.jsonl", {
            "schema_version": self.schema_version,
            "event_id": event_id,
            "event_type": event_type,
            "event_phase": status,
            "step_id": step_id,
            "timestamp": _utcnow(),
            "task_state_before": state_before,
            "task_state_after": state_after,
            "state_delta": normalized_state_delta(state_before, state_after),
            **payload,
        })
        self._event_states[event_id] = state_after

    def register_artifact(self, value: str | bytes | None, role: str,
                          producer_id: str | None) -> str | None:
        if value is None:
            return None
        source_path = None
        if isinstance(value, bytes):
            data = value
            mime_type = "image/png"
        elif str(value).startswith("data:"):
            # Data URLs are already embedded in a request. Record identity without
            # duplicating potentially huge base64 text in the manifest.
            raw = str(value).encode()
            data, mime_type = raw, str(value).split(";", 1)[0].removeprefix("data:")
        else:
            source_path = Path(value)
            data = source_path.read_bytes()
            mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        sha256 = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256-{sha256}"
        suffix = ".png" if mime_type == "image/png" else (
            source_path.suffix if source_path is not None else ".bin")
        destination = self.artifact_dir / f"{sha256}{suffix}"
        if not destination.exists():
            destination.write_bytes(data)
        width = height = None
        if mime_type.startswith("image/"):
            try:
                from PIL import Image
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
            except Exception:
                pass
        usage_key = f"{artifact_id}:{role}:{producer_id}"
        if usage_key not in self._known_artifacts:
            self._known_artifacts.add(usage_key)
            self._append("artifact_manifest.jsonl", {
                "schema_version": self.schema_version,
                "artifact_id": artifact_id,
                "sha256": sha256,
                "relative_path": str(destination.relative_to(self.episode_dir)),
                "role": role,
                "mime_type": mime_type,
                "width": width,
                "height": height,
                "byte_size": len(data),
                "producer_id": producer_id,
                "source_path": str(source_path) if source_path else None,
            })
        return artifact_id

    def record_model_call(self, record: dict) -> None:
        if self.save_model_responses:
            self._append("model_calls.jsonl", record)
        state = self._event_states.get(record.get("parent_event_id"))
        self._append("events.jsonl", {
            "schema_version": self.schema_version,
            "event_id": self._new_event_id(),
            "parent_event_id": record.get("parent_event_id"),
            "event_type": "model_call",
            "event_phase": record.get("status", "completed"),
            "timestamp": _utcnow(),
            "call_id": record.get("call_id"),
            "role": record.get("role"),
            "model": record.get("model"),
            "error": record.get("error"),
            "task_state_before": state,
            "task_state_after": state,
            "state_delta": normalized_state_delta(state, state),
        })

    def record_model_call_started(self, record: dict) -> None:
        """Persist the request before entering a potentially long provider call."""
        if self.save_model_responses:
            self._append("model_calls.jsonl", {
                **record,
                "record_type": "call_started",
                "status": "started",
            })

    def record_model_parse(self, call_id: str | None, status: str,
                           parsed_response=None, error=None,
                           failure_type=None) -> None:
        if not call_id:
            return
        record = {
            "record_type": "parse_update",
            "call_id": call_id,
            "timestamp": _utcnow(),
            "parse_status": status,
            "parsed_response": parsed_response,
            "parse_error": str(error) if error else None,
            "failure_type": failure_type or _parse_failure_type(error, status),
        }
        if self.save_model_responses:
            self._append("model_calls.jsonl", record)

    def record_intervention(self, step_id: int | None, intervention_type: str,
                            decision=None, execution=None, immediate_result=None,
                            parent_event_id=None, task_state=None) -> str:
        self._intervention_sequence += 1
        intervention_id = f"intervention-{self._intervention_sequence:06d}"
        event_id = self._new_event_id()
        state = (task_state if task_state is not None
                 else self._event_states.get(parent_event_id))
        self._open_interventions.append(intervention_id)
        self._append("interventions.jsonl", {
            "schema_version": self.schema_version,
            "intervention_id": intervention_id,
            "event_id": event_id,
            "step_id": step_id,
            "intervention_type": intervention_type,
            "decision": decision,
            "execution": execution,
            "immediate_result": immediate_result,
            "later_outcome": None,
            "parent_event_id": parent_event_id,
            "timestamp": _utcnow(),
        })
        self._append("events.jsonl", {
            "schema_version": self.schema_version,
            "event_id": event_id,
            "parent_event_id": parent_event_id,
            "event_type": "intervention",
            "event_phase": "completed",
            "step_id": step_id,
            "timestamp": _utcnow(),
            "intervention_id": intervention_id,
            "intervention_type": intervention_type,
            "decision": decision,
            "execution": execution,
            "immediate_result": immediate_result,
            "task_state_before": state,
            "task_state_after": state,
            "state_delta": normalized_state_delta(state, state),
        })
        return intervention_id

    def close_interventions(self, status: str, success: bool, score: float) -> None:
        for intervention_id in self._open_interventions:
            self._append("interventions.jsonl", {
                "schema_version": self.schema_version,
                "record_type": "hindsight_outcome",
                "intervention_id": intervention_id,
                "timestamp": _utcnow(),
                "later_outcome": {
                    "episode_status": status,
                    "episode_success": success,
                    "environment_score": score,
                },
            })
        self._open_interventions.clear()

    def record_unknown(self, event_id: str, step_id: int | None, node_id: str,
                       guard_result: dict, evidence=None) -> str:
        unknown_id = f"unknown-{event_id}"
        if unknown_id in self._open_unknowns:
            return unknown_id
        value = {
            "schema_version": self.schema_version,
            "record_type": "unknown_opened",
            "unknown_event_id": unknown_id,
            "source_event_id": event_id,
            "step_id": step_id,
            "node_id": node_id,
            "unknown_type": guard_result.get("unknown_type"),
            "unknown_reason": guard_result.get("unknown_reason"),
            "verification_target": guard_result.get("verification_target"),
            "reason": guard_result.get("reason"),
            "evidence_gap": guard_result.get("evidence_gap"),
            "opening_evidence": list(evidence or []),
            "resolution": "PENDING",
            "timestamp": _utcnow(),
        }
        self._open_unknowns[unknown_id] = value
        self._append("unknown_resolutions.jsonl", value)
        return unknown_id

    def resolve_unknowns(self, node_id: str | None, resolution: str,
                         step_id: int | None, evidence=None,
                         source: str = "later_state") -> None:
        for unknown_id, opened in list(self._open_unknowns.items()):
            if node_id is not None and opened.get("node_id") != node_id:
                continue
            self._append("unknown_resolutions.jsonl", {
                "schema_version": self.schema_version,
                "record_type": "unknown_resolved",
                "unknown_event_id": unknown_id,
                "source_event_id": opened.get("source_event_id"),
                "node_id": opened.get("node_id"),
                "resolution": resolution,
                "resolution_step": step_id,
                "resolution_evidence": list(evidence or []),
                "resolution_source": source,
                "timestamp": _utcnow(),
            })
            del self._open_unknowns[unknown_id]

    def close_unknowns(self, success: bool, evaluator_event_id: str | None) -> None:
        self.resolve_unknowns(
            None, "VALID" if success else "UNRESOLVED", None,
            [evaluator_event_id] if evaluator_event_id else [],
            "evaluator" if success else "hindsight")

    def record_evaluator(self, result=None, error=None, event_id=None,
                         task_state=None) -> None:
        details = _serializable(getattr(result, "details", None))
        for component in (details or {}).get("components", []):
            for side in ("observed", "expected"):
                artifact = component.get(side)
                if not isinstance(artifact, dict) or artifact.get("kind") != "artifact":
                    continue
                path = artifact.get("path")
                try:
                    artifact["artifact_id"] = self.register_artifact(
                        path, f"evaluator_{side}", "final-evaluator")
                except (OSError, ValueError):
                    artifact["artifact_id"] = None
        value = {
            "schema_version": self.schema_version,
            "timestamp": _utcnow(),
            "success": getattr(result, "success", None),
            "score": getattr(result, "score", None),
            "details": details,
            "exception": str(error) if error else None,
        }
        (self.episode_dir / "evaluator_result.json").write_text(
            json.dumps(_serializable(value), indent=2), encoding="utf-8")
        event_id = event_id or self.start_event(
            "evaluator", None, task_state)
        self.finish_event(event_id, "evaluator", None, task_state, task_state,
                          "failed" if error else "completed", evaluator=value)

    def record_termination(self, status: str, error: str | None,
                           step_id: int | None, task_state=None) -> None:
        event_id = self.start_event(
            "episode_termination", step_id, task_state,
            termination_reason=status)
        self.finish_event(
            event_id, "episode_termination", step_id, task_state, task_state,
            "completed", termination_reason=status, error=error)


class RecordingModelClient(MultimodalModelClient):
    """Records exact caller-visible requests and raw responses around any client."""

    def __init__(self, client: MultimodalModelClient, recorder: TrainingReadyLogger,
                 role: str):
        self.client = client
        self.recorder = recorder
        self.role = role
        self.last_call_id: str | None = None
        self.last_parent_event_id: str | None = None
        self._pending_retry_intervention_id: str | None = None

    @property
    def config(self):
        return getattr(self.client, "config", None)

    def generate(self, messages, images=None, response_schema=None) -> ModelResponse:
        parent_event_id = _CURRENT_EVENT_ID.get()
        retry_of_call_id = (self.last_call_id
                            if parent_event_id == self.last_parent_event_id else None)
        retry_intervention_id = (self._pending_retry_intervention_id
                                 if retry_of_call_id else None)
        self._pending_retry_intervention_id = None
        call_id = self.recorder.new_call_id(self.role)
        self.last_call_id = call_id
        self.last_parent_event_id = parent_event_id
        image_ids = [self.recorder.register_artifact(
            image, f"{self.role}_model_input", call_id) for image in (images or [])]
        config = getattr(self.client, "config", None)
        started_at = _utcnow()
        started = time.monotonic()
        base_record = {
            "schema_version": self.recorder.schema_version,
            "call_id": call_id,
            "parent_event_id": parent_event_id,
            "retry_of_call_id": retry_of_call_id,
            "retry_intervention_id": retry_intervention_id,
            "role": self.role,
            "provider": getattr(config, "provider_id", type(self.client).__name__),
            "model": getattr(config, "model", None),
            "started_at": started_at,
            "request": {"messages": messages, "response_schema": response_schema},
            "image_artifact_ids": image_ids,
        }
        self.recorder.record_model_call_started(base_record)
        try:
            response = self.client.generate(messages, images, response_schema)
        except Exception as exc:
            attempts = self._record_provider_attempts(
                call_id, parent_event_id, getattr(exc, "attempts", None))
            self.recorder.record_model_call({
                **base_record,
                "record_type": "call",
                "finished_at": _utcnow(),
                "latency_seconds": time.monotonic() - started,
                "status": "failed",
                "error": str(exc),
                "attempts": attempts,
            })
            raise
        attempts = self._record_provider_attempts(
            call_id, parent_event_id, getattr(response, "attempts", None))
        self.recorder.record_model_call({
            **base_record,
            "record_type": "call",
            "model": response.model or getattr(config, "model", None),
            "finished_at": _utcnow(),
            "latency_seconds": response.latency_seconds,
            "status": "completed",
            "raw_response": response.raw_response,
            "raw_text": response.text,
            "parsed_response": response.parsed,
            "usage": response.usage,
            "attempts": attempts,
        })
        return response

    def _record_provider_attempts(self, call_id, parent_event_id, attempts):
        normalized = []
        for index, attempt in enumerate(attempts or []):
            value = dict(attempt)
            value["attempt_id"] = f"{call_id}-attempt-{index + 1:02d}"
            value["retry_of_attempt_id"] = (
                normalized[-1]["attempt_id"] if normalized else None)
            normalized.append(value)
            if index:
                self.recorder.record_intervention(
                    self.recorder._event_steps.get(parent_event_id),
                    "provider_retry",
                    decision={"failed_attempt": normalized[index - 1]},
                    execution={"attempt_id": value["attempt_id"],
                               "call_id": call_id},
                    immediate_result={"status": value.get("status"),
                                      "error": value.get("error")},
                    parent_event_id=parent_event_id)
        return normalized or None

    def record_parse(self, status: str, parsed_response=None, error=None,
                     failure_type=None) -> None:
        self.recorder.record_model_parse(
            self.last_call_id, status, parsed_response, error, failure_type)
        if status == "failed":
            parent_event_id = _CURRENT_EVENT_ID.get()
            self._pending_retry_intervention_id = self.recorder.record_intervention(
                self.recorder._event_steps.get(parent_event_id), "retry",
                decision={"call_id": self.last_call_id,
                          "parse_error": str(error) if error else None},
                execution={"next_model_call_pending": True},
                immediate_result={"parse_status": "failed"},
                parent_event_id=parent_event_id)


def _parse_failure_type(error, status):
    if status not in {"failed", "rejected", "fallback"} or error is None:
        return None
    text = str(error).lower()
    if "missing required fields" in text:
        return "schema_missing_fields"
    if "blocked after repeated" in text:
        return "policy_blocked_action"
    if "outside the executable frontier" in text:
        return "policy_frontier_violation"
    if "already verified" in text or "unverified dependencies" in text:
        return "policy_state_violation"
    if "premature" in text or "is_finish=true" in text:
        return "policy_premature_finish"
    if "json" in text:
        return "invalid_json"
    if "enum" in text or "invalid" in text or "unsupported" in text:
        return "schema_invalid_value"
    return "schema_or_semantic_validation"


def record_parse(client, status: str, parsed_response=None, error=None,
                 failure_type=None) -> None:
    callback = getattr(client, "record_parse", None)
    if callback:
        callback(status, parsed_response, error, failure_type)
