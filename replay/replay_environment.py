"""ReplayEnvironment (指引.txt §23): debug StateGuard against saved
trajectories without Docker/OSWorld/AndroidWorld.

Input: list of trajectory records (the §28 trajectory.jsonl format),
each {"step", "proposal", "observation_before", "observation_after", ...}.
step() replays the saved observation_after for the next record.
"""

from __future__ import annotations

import json

from stateguard.interfaces.environment import EnvironmentAdapter
from stateguard.interfaces.action import Action
from stateguard.interfaces.observation import Observation


class ReplayEnvironment(EnvironmentAdapter):
    def __init__(self, records: list[dict]):
        self.records = list(records)
        self._idx = 0
        self._last = Observation({}, 0)

    @classmethod
    def load(cls, path: str) -> "ReplayEnvironment":
        with open(path) as f:
            return cls([json.loads(line) for line in f if line.strip()])

    def reset(self) -> Observation:
        self._idx = 0
        if self.records:
            rec = self.records[0]
            self._last = Observation.from_dict(
                rec.get("observation_before") or rec["observation_after"])
        else:
            self._last = Observation({}, 0)
        return self._last

    def observe(self) -> Observation:
        return self._last

    def step(self, action: Action) -> Observation:
        if self._idx >= len(self.records):
            raise RuntimeError("replay trajectory exhausted")
        rec = self.records[self._idx]
        self._idx += 1
        self._last = Observation.from_dict(rec["observation_after"])
        return self._last

    def fault_at(self, index: int, mutate: dict) -> None:
        """ponytail: splice a doctored observation into the replay to test
        localization on realistic trajectories."""
        rec = self.records[index]
        rec["observation_after"] = {
            "step": rec["observation_after"].get("step", index),
            "snapshot": mutate,
        }
