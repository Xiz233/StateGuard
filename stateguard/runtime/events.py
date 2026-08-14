from dataclasses import asdict, dataclass


@dataclass
class RootPredictionEvent:
    step: int
    fault_root: str

    def to_dict(self): return asdict(self)


@dataclass
class InterventionEvent:
    step: int
    intervention_type: str
    repair_cycle_id: int | None = None

    def to_dict(self): return asdict(self)
