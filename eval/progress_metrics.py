"""Progress preservation + repair radius metrics (指引.txt §27)."""

from __future__ import annotations


def progress_preservation_rate(preserved: list[int], verified_before: list[int]) -> float:
    """preserved verified nodes / verified nodes before failure (H3)."""
    if not verified_before:
        return 1.0
    return sum(preserved) / sum(verified_before)


def repair_radius_stats(reactivated_counts: list[int],
                        repair_action_counts: list[int]) -> dict:
    """Mean reactivated task nodes and mean repair actions."""
    def mean(xs: list[int]) -> float:
        return sum(xs) / len(xs) if xs else 0.0
    return {
        "reactivated_nodes_mean": mean(reactivated_counts),
        "repair_actions_mean": mean(repair_action_counts),
    }


def operational_metrics(total_steps=0, model_calls=0, guard_tokens=0,
                        executor_tokens=0, guard_latency=0.0,
                        executor_latency=0.0) -> dict:
    return dict(total_steps=total_steps, model_calls=model_calls,
                guard_tokens=guard_tokens, executor_tokens=executor_tokens,
                guard_latency=guard_latency, executor_latency=executor_latency)
