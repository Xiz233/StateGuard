from dataclasses import asdict, dataclass


@dataclass
class FaultEvent:
    fault_id: str
    fault_type: str
    injected_step: int
    fault_root: str
    original_proposal: dict
    executed_mutation: dict

    def to_dict(self): return asdict(self)
