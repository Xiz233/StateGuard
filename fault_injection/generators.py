"""Fault case generators: per-fault-type factories over the synthetic task
corpus (指引.txt §25)."""

from __future__ import annotations

from .injector import inject, make_cases, FaultCase  # re-export

__all__ = ["inject", "make_cases", "FaultCase"]


def wrong_target_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.WRONG_TARGET, target)


def wrong_value_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.WRONG_VALUE, target)


def missing_subgoal_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.MISSING_SUBGOAL, target)


def no_effect_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.NO_EFFECT, target)


def not_persisted_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.NOT_PERSISTED, target)


def premature_finish_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.PREMATURE_FINISH, target)


def dependency_violation_case(spec: dict, target: str | None = None) -> FaultCase:
    from stateguard.core.schema import FaultType
    return inject(spec, FaultType.DEPENDENCY_VIOLATION, target)
