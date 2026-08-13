import json

from stateguard.compiler.manual_loader import load_manual_task


def test_manual_loader(tmp_path):
    path = tmp_path / "task.json"
    path.write_text(json.dumps({"nodes": [{"node_id": "S1", "description": "Open",
                                           "dependencies": [], "expected_result_semantic": "Open",
                                           "evidence_mode": "visual", "required": True}]}))
    assert load_manual_task(path).get("S1").evidence_mode == "visual"
