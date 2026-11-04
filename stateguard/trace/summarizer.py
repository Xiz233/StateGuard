from __future__ import annotations


def summarize_observation(observation) -> dict:
    if observation is None:
        return {}
    snapshot = getattr(observation, "snapshot", None)
    return {
        "step": getattr(observation, "step", None),
        "ref": getattr(observation, "ref", None),
        "snapshot": snapshot if isinstance(snapshot, (dict, list, str, int, float, bool)) else str(snapshot),
        "has_screenshot": bool(getattr(observation, "screenshot", None)),
    }


def causal_trace_window(entries, failed_node: str, ancestors: list[str], graph=None):
    """Return only transitions on the failed node's causal chain."""
    relevant = set(ancestors) | {failed_node}
    return [entry for entry in entries if entry.active_node_id in relevant]
