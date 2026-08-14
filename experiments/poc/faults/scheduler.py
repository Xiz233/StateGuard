from .earlier_state_corruption import EarlierStateCorruptionInjector
from .no_effect import NoEffectInjector
from .wrong_target import WrongTargetInjector
from .wrong_value import WrongValueInjector

INJECTORS = {
    "wrong_target": WrongTargetInjector,
    "wrong_value": WrongValueInjector,
    "no_effect": NoEffectInjector,
    "earlier_state_corruption": EarlierStateCorruptionInjector,
}


def make_injector(spec: dict | None):
    if not spec:
        return None
    try:
        return INJECTORS[spec["type"]](spec)
    except KeyError as exc:
        raise ValueError(f"unsupported fault type {spec.get('type')!r}") from exc
