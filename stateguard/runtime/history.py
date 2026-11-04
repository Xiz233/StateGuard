class ActionHistory:
    def __init__(self, limit=10):
        self.limit, self.items = limit, []

    def append(self, value):
        self.items.append(value)

    def recent(self):
        return self.items[-self.limit:]

    def blocked_actions(self):
        return [
            {"subgoal_id": item.get("subgoal"), "action": item.get("action"),
             "reason": item.get("guard_reason") or "repeated action produced no effect"}
            for item in self.recent() if item.get("blocked_action")
        ]

    def add_transition(self, step, proposal, observation, guard_result,
                       execution_phase="normal", blocked_action=False):
        self.append({"step": step, "subgoal": proposal.subgoal_id,
                     "action": proposal.action,
                     "intent": proposal.intent, "expected_effect": proposal.expected_effect,
                     "observation_summary": observation.visible_text,
                     "guard_judgement": guard_result.judgement,
                     "verification_target": guard_result.verification_target,
                     "guard_reason": guard_result.reason,
                     "evidence_update": guard_result.progress_updates,
                     "execution_phase": execution_phase,
                     "blocked_action": bool(blocked_action)})
