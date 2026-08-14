from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter, OSWorldBackendProtocol


def test_fake_backend_full_contract(tmp_path):
    backend = FakeOSWorldBackend(str(tmp_path))
    assert isinstance(backend, OSWorldBackendProtocol)
    task = {"initial_state": {"x": 0}, "success_state": {"x": 1},
            "action_rules": [{"match": {"type": "click", "x": 1, "y": 1},
                              "effect": {"x": 1}}]}
    env = OSWorldAdapter(backend, (10, 10))
    assert env.health_check() and env.reset(task).structured_state["x"] == 0
    assert env.step({"type": "click", "x": 1, "y": 1}).structured_state["x"] == 1
    assert env.evaluate().success and env.backend_info()["name"] == "fake"
    env.close()
