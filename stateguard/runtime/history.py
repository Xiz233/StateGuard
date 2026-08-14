class ActionHistory:
    def __init__(self, limit=10):
        self.limit, self.items = limit, []

    def append(self, value):
        self.items.append(value)

    def recent(self):
        return self.items[-self.limit:]

    def add_transition(self, step, proposal, observation, guard_result):
        self.append({"step": step, "subgoal": proposal.subgoal_id,
                     "intent": proposal.intent, "expected_effect": proposal.expected_effect,
                     "observation_summary": observation.visible_text,
                     "guard_judgement": guard_result.judgement,
                     "evidence_update": guard_result.progress_updates})
