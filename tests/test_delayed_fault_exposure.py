from types import SimpleNamespace

from experiments.poc.faults import make_injector


def test_delayed_fault_exposure_is_separate_from_injection():
    spec = {"fault_id": "f", "type": "earlier_state_corruption", "root_node": "S2",
            "inject": {"trigger": {"subgoal_id": "S2"},
                       "mutation": {"action_override": {"type": "wait"}}},
            "exposure": {"mode": "delayed", "trigger": {"subgoal_id": "S4"}}}
    injector = make_injector(spec)
    proposal = lambda node: SimpleNamespace(subgoal_id=node, action={"type": "click", "x": 1, "y": 1},
        to_dict=lambda: {"subgoal_id": node})
    _, injected = injector.inject("t", 2, proposal("S2"), None)
    assert injected.injected_step == 2
    assert injector.poll_exposure(3, proposal("S3")) is None
    exposed = injector.poll_exposure(4, proposal("S4"))
    assert exposed.exposed_step == 4 and exposed.mode == "delayed"
