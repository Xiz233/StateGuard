"""FaultType re-export + fault labels for injection (指引.txt §16/25).

Injection kinds and their meaning:
  wrong_target       action's effect targets the wrong location (Sheet2->Sheet1)
  wrong_value        executor fills a wrong payload value
  missing_subgoal    a necessary step is skipped entirely
  no_effect          action fires but environment state does not change
  not_persisted      action "succeeds" but the result is not in the state
  premature_finish   FINISH proposed while required nodes are incomplete
  dependency_violation  downstream acts on unverified (EXECUTED) prerequisites
"""

from stateguard.core.schema import FaultType

INJECTABLE = [  # §25 required set, minus wrong_format (kept in the enum)
    FaultType.WRONG_TARGET,
    FaultType.WRONG_VALUE,
    FaultType.MISSING_SUBGOAL,
    FaultType.NO_EFFECT,
    FaultType.NOT_PERSISTED,
    FaultType.PREMATURE_FINISH,
    FaultType.DEPENDENCY_VIOLATION,
]
