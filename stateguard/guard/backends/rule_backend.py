from .base import GuardBackend
from ..verifier import verify_transition


class RuleBackend(GuardBackend):
    def verify(self, task_state, before, proposal, after, repair_context=None):
        return verify_transition(task_state.get(proposal.subgoal_id), proposal, before, after)
