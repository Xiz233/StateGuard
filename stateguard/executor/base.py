from abc import ABC, abstractmethod


class Executor(ABC):
    @abstractmethod
    def act(self, observation, task_state, repair_context=None): ...
