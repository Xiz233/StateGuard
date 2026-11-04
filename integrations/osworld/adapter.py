from __future__ import annotations

import io
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from stateguard.interfaces.environment import EnvironmentAdapter
from stateguard.environment.capabilities import EnvironmentCapabilities
from stateguard.verification.contracts import EvidenceSource
from stateguard.verification.observation import ObservationBundle

from .action_converter import convert_action
from .observation_converter import convert_observation


@dataclass
class EvaluationResult:
    success: bool
    score: float = 0.0
    details: dict | None = None


@runtime_checkable
class OSWorldBackendProtocol(Protocol):
    def reset(self, task_spec: dict) -> dict: ...
    def get_observation(self) -> dict: ...
    def execute_action(self, action: dict) -> dict: ...
    def evaluate(self, task_spec: dict) -> EvaluationResult | dict: ...
    def close(self) -> None: ...
    def health_check(self) -> bool: ...
    def backend_info(self) -> dict: ...


class DesktopEnvBackend:
    """The only version-sensitive OSWorld seam."""
    def __init__(self, **kwargs):
        osworld_root = kwargs.pop("osworld_root", None)
        if osworld_root and str(Path(osworld_root).resolve()) not in sys.path:
            sys.path.insert(0, str(Path(osworld_root).resolve()))
        try:
            from desktop_env.desktop_env import DesktopEnv
        except ImportError as exc:
            try:
                from desktop_env.envs.desktop_env import DesktopEnv
            except ImportError:
                raise RuntimeError("OSWorld is not installed") from exc
        if "provider" in kwargs and "provider_name" not in kwargs:
            kwargs["provider_name"] = kwargs.pop("provider")
        kwargs.setdefault("action_space", "pyautogui")
        self.env = DesktopEnv(**kwargs)

    @staticmethod
    def _task_config(task_spec):
        if not isinstance(task_spec, dict):
            raise ValueError("OSWorld task spec must be a dict")
        source = task_spec.get("task_config_path") or task_spec.get("source")
        if source:
            path = Path(source)
            if not path.is_file():
                raise ValueError(f"OSWorld task config does not exist: {path}")
            return json.loads(path.read_text(encoding="utf-8"))
        if {"id", "instruction", "evaluator"} <= task_spec.keys():
            return task_spec
        raise ValueError("OSWorld task spec needs task_config_path or a complete task config")

    def reset(self, task_spec): return self.env.reset(task_config=self._task_config(task_spec))
    def get_observation(self): return self.env._get_obs()
    def execute_action(self, action): return self.env.step(action)
    @staticmethod
    def _evaluation_value(value):
        if isinstance(value, (str, Path)):
            try:
                path = Path(value)
                if path.is_file():
                    data = path.read_bytes()
                    return {"kind": "artifact", "path": str(path),
                            "byte_size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()}
            except (OSError, ValueError):
                pass
        if isinstance(value, bytes):
            return {"kind": "bytes", "byte_size": len(value),
                    "sha256": hashlib.sha256(value).hexdigest()}
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            shape = list(value.shape) if hasattr(value, "shape") else None
            return {"kind": type(value).__name__, "shape": shape,
                    "repr": repr(value)[:20000]}

    def _evaluate_components(self):
        evaluator = self.env.evaluator
        metrics = self.env.metric if isinstance(self.env.metric, list) else [self.env.metric]
        result_getters = (self.env.result_getter if isinstance(
            self.env.result_getter, list) else [self.env.result_getter])
        expected_getters = (self.env.expected_getter if isinstance(
            self.env.expected_getter, list) else [self.env.expected_getter])
        result_configs = evaluator.get("result", [])
        if not isinstance(result_configs, list):
            result_configs = [result_configs]
        expected_configs = evaluator.get("expected", [])
        if not isinstance(expected_configs, list):
            expected_configs = [expected_configs]
        options = self.env.metric_options
        if not isinstance(options, list):
            options = [options]
        components = []
        for index, metric in enumerate(metrics):
            component = {
                "index": index,
                "metric": getattr(metric, "__name__", type(metric).__name__),
                "conjunction": getattr(self.env, "metric_conj", "and"),
                "result_config": result_configs[index] if index < len(result_configs) else None,
                "expected_config": (
                    expected_configs[index] if index < len(expected_configs) else None),
                "options": options[index] if index < len(options) else {},
                "observed": None, "expected": None, "score": None,
                "passed": None, "exception": None,
            }
            try:
                observed = result_getters[index](self.env, component["result_config"])
                expected = None
                getter = expected_getters[index] if index < len(expected_getters) else None
                if getter and component["expected_config"]:
                    expected = getter(self.env, component["expected_config"])
                    value = metric(observed, expected, **(component["options"] or {}))
                else:
                    value = metric(observed, **(component["options"] or {}))
                component["observed"] = self._evaluation_value(observed)
                component["expected"] = self._evaluation_value(expected)
                component["score"] = float(value)
                component["passed"] = float(value) > 0.0
            except Exception as exc:
                component["exception"] = f"{type(exc).__name__}: {exc}"
            components.append(component)
        return components

    def evaluate(self, task_spec):
        score = float(self.env.evaluate())
        details = {
            "task_id": getattr(self.env, "task_id", None),
            "raw_evaluator_output": score,
            "conjunction": getattr(self.env, "metric_conj", None),
            "components": self._evaluate_components(),
        }
        return EvaluationResult(success=score > 0.0, score=score, details=details)
    def close(self): self.env.close()
    def health_check(self): return bool(getattr(self.env, "controller", None))
    def backend_info(self):
        return {"name": "desktop_env", "provider": self.env.provider_name,
                "action_format": self.env.action_space,
                "vm_ip": getattr(self.env, "vm_ip", None)}


class OSWorldAdapter(EnvironmentAdapter):
    def __init__(self, backend: OSWorldBackendProtocol | None = None, screen_size=(1920, 1080),
                 reset_ready_timeout_seconds=0.0, reset_poll_seconds=2.0,
                 reset_settle_seconds=0.0,
                 **backend_kwargs):
        self.backend = backend or DesktopEnvBackend(**backend_kwargs)
        self.screen_size, self._step, self._task = screen_size, 0, None
        self.last_execution_receipt = None
        self.reset_ready_timeout_seconds = reset_ready_timeout_seconds
        self.reset_poll_seconds = reset_poll_seconds
        self.reset_settle_seconds = reset_settle_seconds

    @staticmethod
    def _screen_is_usable(observation):
        screenshot = observation.screenshot
        if not isinstance(screenshot, bytes):
            return True
        try:
            from PIL import Image
            image = Image.open(io.BytesIO(screenshot)).convert("L")
        except ImportError as exc:
            raise RuntimeError("Pillow is required for OSWorld blank-screen detection") from exc
        except Exception:
            return False
        visible_pixels = sum(image.histogram()[11:])
        return visible_pixels >= image.width * image.height * 0.05

    def reset(self, task_spec=None):
        self._step, self._task = 0, task_spec or {}
        try:
            raw = self.backend.reset(self._task)
        except TypeError:
            raw = self.backend.reset()
        observation = convert_observation(raw, self._step)
        if self.reset_ready_timeout_seconds:
            deadline = time.monotonic() + self.reset_ready_timeout_seconds
            while not self._screen_is_usable(observation) and time.monotonic() < deadline:
                time.sleep(self.reset_poll_seconds)
                observation = self.observe()
            if not self._screen_is_usable(observation):
                raise RuntimeError(
                    f"OSWorld screen remained blank for {self.reset_ready_timeout_seconds:g}s")
        if self.reset_settle_seconds:
            time.sleep(self.reset_settle_seconds)
            observation = self.observe()
        return observation

    def observe(self):
        observe = getattr(self.backend, "get_observation", None) or self.backend.observe
        return convert_observation(observe(), self._step)

    def step(self, action):
        self._step += 1
        execute = getattr(self.backend, "execute_action", None) or self.backend.step
        info = self.backend_info()
        converted = convert_action(action, self.screen_size,
                                   info.get("action_format", "generic"))
        started = time.monotonic()
        receipt = {
            "step": self._step,
            "proposed_action": action,
            "backend_action": converted,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "success": False,
            "exception": None,
            "duration_seconds": None,
            "raw_environment_metadata": None,
        }
        try:
            raw = execute(converted)
            receipt["success"] = True
            if isinstance(raw, tuple) and len(raw) == 4:
                receipt["raw_environment_metadata"] = {
                    "reward": raw[1], "done": raw[2], "info": raw[3]}
            elif isinstance(raw, dict):
                receipt["raw_environment_metadata"] = raw.get("metadata")
            return convert_observation(raw, self._step)
        except Exception as exc:
            receipt["exception"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            receipt["duration_seconds"] = time.monotonic() - started
            receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
            self.last_execution_receipt = receipt

    def evaluate(self, task_spec=None):
        try:
            result = self.backend.evaluate(task_spec or self._task)
        except TypeError:
            result = self.backend.evaluate()
        if isinstance(result, EvaluationResult):
            return result
        if isinstance(result, dict):
            if "success" in result:
                return EvaluationResult(**result)
            if "score" in result:
                score = float(result["score"])
                return EvaluationResult(score > 0.0, score, result)
            if "ok" in result:
                return EvaluationResult(bool(result["ok"]), float(bool(result["ok"])), result)
        if isinstance(result, (int, float, bool)):
            score = float(result)
            return EvaluationResult(score > 0.0, score)
        raise ValueError(f"unsupported OSWorld evaluation result: {result!r}")

    def close(self):
        if hasattr(self.backend, "close"): self.backend.close()
    def health_check(self): return self.backend.health_check() if hasattr(self.backend, "health_check") else True
    def backend_info(self): return self.backend.backend_info() if hasattr(self.backend, "backend_info") else {"name": type(self.backend).__name__}

    def get_capabilities(self, observation=None):
        sources = {EvidenceSource.SCREENSHOT}
        if observation is not None and observation.ui_tree is not None:
            sources.add(EvidenceSource.ACCESSIBILITY_TREE)
        if observation is not None and observation.structured_state is not None:
            sources.add(EvidenceSource.STRUCTURED_STATE)
        supported = {"visual_mllm"}
        if EvidenceSource.ACCESSIBILITY_TREE in sources:
            supported.add("accessibility_predicate")
        if EvidenceSource.STRUCTURED_STATE in sources:
            supported.add("structured_predicate")
        visual_channels = frozenset({EvidenceSource.SCREENSHOT})
        return EnvironmentCapabilities(
            available_sources=frozenset(sources),
            supported_verifiers=frozenset(supported),
            action_effect_channels={
                action: visual_channels
                for action in ("click", "type", "hotkey", "scroll", "drag", "wait")
            },
        )

    @staticmethod
    def collect_observation_bundle(observation):
        return ObservationBundle.from_observation(observation)

    def note_fault_injection(self, event, spec):
        if hasattr(self.backend, "note_fault_injection"):
            self.backend.note_fault_injection(event, spec)

    def expose_failure(self, event):
        if hasattr(self.backend, "expose_failure"):
            self.backend.expose_failure(event)
        return self.observe()
