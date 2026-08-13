"""Prompt templates for the future LLM-backed components. Phase I runtime is
fully rule-based; these freeze the intended schemas (指引.txt §21B/19)."""

PROMPTS = {
    "compile_instruction": """You are a task compiler. Decompose the instruction into verified task-state subgoals.
Output JSON (one node per subgoal):
{{"nodes": [{{"node_id": "S1", "description": "...", "device": "...", "app": "...",
   "dependencies": [], "expected_result": "checkable predicate"}}]}}
Devices available: {available_devices}
Instruction: {instruction}""",

    "verify_transition": """Verify whether the executed action achieved its subgoal.
Inputs: task_state, observation_before, action proposal, observation_after.
Output: {{"judgement": "verified|contradicted|unknown", "verification_target": null}}""",

    "localize": """Find the earliest violated task-state dependency.
Candidates must have all parents VERIFIED. Prefer (1) direct contradiction,
(2) transition mismatch, (3) explains most downstream failures,
(4) weakest verified evidence, (5) closest to failure source.
Output: {{"fault_root": "S3", "fault_type": "..."}}""",
}
