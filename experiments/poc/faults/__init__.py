from dataclasses import dataclass
from enum import Enum


class ControlledFault(str, Enum):
    WRONG_TARGET = "wrong_target"
    WRONG_VALUE = "wrong_value"
    NO_EFFECT = "no_effect"
    EARLIER_STATE_CORRUPTION = "earlier_state_corruption"


@dataclass
class FaultGroundTruth:
    fault_type: str
    injected_step: int
    fault_root: str
