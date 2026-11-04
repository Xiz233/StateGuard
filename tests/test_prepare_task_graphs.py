from types import SimpleNamespace

from scripts.prepare_task_graphs import draft_graph


class FakeClient:
    def __init__(self):
        self.calls = []

    def generate(self, messages, response_schema=None):
        self.calls.append(messages)
        if len(self.calls) == 1:
            parsed = {"task_dag": {"nodes": []}}
        else:
            parsed = {"nodes": [{
                "node_id": "S1",
                "description": "Complete the visible task",
                "dependencies": [],
                "expected_result_semantic": "The requested result is visible",
                "evidence_mode": "visual",
                "required": True,
            }]}
        return SimpleNamespace(parsed=parsed, text=str(parsed))


def test_draft_graph_corrects_wrapped_output():
    client = FakeClient()
    result = draft_graph(client, {"task_id": "t1", "instruction": "Do the task"})
    assert result["nodes"][0]["node_id"] == "S1"
    assert len(client.calls) == 2
    assert "top-level object" in client.calls[1][-1]["content"]
