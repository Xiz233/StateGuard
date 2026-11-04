"""Auto-DAG generation prompt (planning/phase-1)."""

AUTO_DAG_PROMPT = """You are planning a GUI task as a DAG of SEMANTIC STATES.

Task instruction:
{instruction}

Generate a task-state DAG (2-8 nodes) describing the states that must become
true, NOT the GUI actions used to achieve them.

Hard constraints:
- Generate STATES, not GUI actions.
  Good: "The requested setting is enabled."
  Bad: "Click the toggle at x=523, y=412."
  Good: "The document contains the transformed text."
  Bad: "Press Ctrl+A and choose Format > Text > lowercase."
- Each node is a semantic subgoal; a node may require several atomic actions.
- Every node must be an externally verifiable environment state. A screenshot,
  accessibility tree, structured application state, or persistence check must
  be able to prove whether it is true.
- semantic_goal is the stable task meaning. Its invariant must describe WHAT
  must be true and must not contain coordinates, selectors, or future UI labels.
- verification_intent describes what evidence would in principle prove the
  semantic goal. Exact UI grounding is deferred until the node becomes active.
- Do not create nodes for private reasoning, understanding, identification,
  inference, remembering, or reading. Keep those activities inside the
  Executor strategy and connect the surrounding observable environment states.
- expected_result_semantic must name concrete evidence in the environment,
  not an agent belief such as "the mapping is understood".
- Never predict coordinates or click sequences.
- Independent subtasks may be parallel (no dependency edge between them).
- Dependencies must express real prerequisites between states.
- For tasks that require saving/submitting/sending, include a final state
  asserting the result exists and is persisted; executing an action in the GUI
  does not by itself make a state true.
- Do not generate nodes that describe the evaluator, gold data, or hidden
  implementation details.
- Do not create cycles.
- Return between 2 and 8 nodes.

Return JSON only, exactly in this schema:
{{
  "nodes": [
    {{
      "node_id": "S1",
      "description": "...",
      "dependencies": [],
      "expected_result_semantic": "...",
      "evidence_mode": "visual",
      "semantic_goal": {
        "description": "...",
        "invariant": {"relation": "...", "operator": "equals", "value": "..."},
        "required": true
      },
      "verification_intent": {
        "target_claim": "...",
        "preferred_evidence_types": ["structured", "accessibility", "visual"],
        "persistence_required": false,
        "strength": "normal"
      },
      "required": true
    }}
  ]
}}

evidence_mode must be one of: visual, structured, persistence, hybrid.
node_id must be "S1", "S2", ... in topological order (dependencies before dependents)."""
