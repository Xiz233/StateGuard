from abc import ABC, abstractmethod


class GuardBackend(ABC):
    @abstractmethod
    def verify(self, task_state, before, proposal, after, repair_context=None): ...
