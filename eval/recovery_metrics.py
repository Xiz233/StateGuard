"""Recovery + false intervention metrics (指引.txt §27)."""

from __future__ import annotations


def recovery_success(recovered: list[bool]) -> float:
    """Fraction of injected episodes that end with all required nodes VERIFIED."""
    return sum(recovered) / len(recovered) if recovered else 0.0


def false_intervention_rate(contradictions_per_clean_episode: list[int]) -> float:
    """Fraction of clean episodes where StateGuard wrongly reports a
    contradiction (must stay low; 指引.txt §27)."""
    n = len(contradictions_per_clean_episode)
    return sum(c > 0 for c in contradictions_per_clean_episode) / n if n else 0.0
