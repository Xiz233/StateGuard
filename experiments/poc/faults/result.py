from dataclasses import asdict, dataclass


@dataclass
class FaultInjectionEvent:
    fault_id: str
    fault_type: str
    injected_step: int
    fault_root: str
    original_proposal: dict
    executed_mutation: dict

    def to_dict(self): return asdict(self)


@dataclass
class FailureExposureEvent:
    fault_id: str
    exposed_step: int
    mode: str
    trigger_subgoal: str | None = None

    def to_dict(self): return asdict(self)


# Phase II-B compatibility for callers that imported the old name.
FaultEvent = FaultInjectionEvent
