from experiments.poc.faults import make_injector
from integrations.osworld import FakeOSWorldBackend, OSWorldAdapter
from stateguard.compiler.task_compiler import compile_from_spec
from stateguard.core.schema import ActionProposal
from stateguard.runtime.episode_runner import EpisodeRunner


class CapturingExecutor:
    def __init__(self):
        self.contexts, self.index = [], 0
        self.actions = [
            ("S1", {"type": "wait"}), ("S2", {"type": "click", "x": 1, "y": 1}),
            ("S3", {"type": "wait"}), ("S4", {"type": "wait"}),
            ("S4", {"type": "wait"}),
        ]

    def act(self, observation, task_state, repair_context=None):
        self.contexts.append(repair_context)
        if self.index == len(self.actions):
            return ActionProposal("", {}, "finish", "", True)
        node, action = self.actions[self.index]; self.index += 1
        return ActionProposal(node, action, node, "")


def test_latest_retry_receives_signal_only_after_exposure():
    nodes = [{"node_id": f"S{i}", "description": f"step {i}",
              "dependencies": [f"S{i-1}"] if i > 1 else [], "expected_result": "x set"}
             for i in range(1, 5)]
    state = compile_from_spec({"nodes": nodes})
    task = {"initial_state": {}, "success_state": {}, "action_rules": []}
    spec = {"fault_id": "delayed", "type": "earlier_state_corruption", "root_node": "S2",
            "inject": {"trigger": {"subgoal_id": "S2"},
                       "mutation": {"action_override": {"type": "click", "x": 2, "y": 2}}},
            "exposure": {"mode": "delayed", "trigger": {"subgoal_id": "S4"}}}
    executor = CapturingExecutor()
    EpisodeRunner(executor, mode="latest_retry").run(
        OSWorldAdapter(FakeOSWorldBackend(), (10, 10)), state, task, injector=make_injector(spec))
    assert executor.contexts[:4] == [None, None, None, None]
    prompt = executor.contexts[4]
    assert prompt == EpisodeRunner.LATEST_RETRY_PROMPT
    assert all(secret not in prompt for secret in
               ("S2", "delayed", "earlier_state_corruption", "affected", "preserve"))
