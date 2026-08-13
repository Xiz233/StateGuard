class HybridBackend:
    def __init__(self, rule_backend, mllm_backend):
        self.rule, self.mllm = rule_backend, mllm_backend

    def verify(self, task_state, before, proposal, after, repair_context=None):
        node = task_state.get(proposal.subgoal_id)
        if node.structured_predicate or node.expected_effect:
            result = self.rule.verify(task_state, before, proposal, after, repair_context)
            if result.judgement != "unknown":
                return result
        return self.mllm.verify(task_state, before, proposal, after, repair_context)
