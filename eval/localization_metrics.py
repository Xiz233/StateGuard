"""Fault localization metrics (指引.txt §27): root accuracy + affected-set
precision / recall / F1."""

from __future__ import annotations


def localization_accuracy(predicted_roots: list[str], gt_roots: list[str]) -> float:
    """Fraction of episodes where predicted root == ground-truth root."""
    n = len(predicted_roots)
    if n == 0:
        return 0.0
    return sum(p == g for p, g in zip(predicted_roots, gt_roots)) / n


def affected_set_metrics(predicted: list[list[str]], gt: list[list[str]]):
    """Per-episode precision/recall/F1 of the predicted affected subgraph
    vs ground truth; returns (mean_precision, mean_recall, mean_f1)."""
    precisions, recalls, f1s = [], [], []
    for p, g in zip(predicted, gt):
        p_set, g_set = set(p), set(g)
        if not p_set and not g_set:
            precisions.append(1.0); recalls.append(1.0); f1s.append(1.0)
            continue
        tp = len(p_set & g_set)
        precision = tp / len(p_set) if p_set else 0.0
        recall = tp / len(g_set) if g_set else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        precisions.append(precision); recalls.append(recall); f1s.append(f1)
    if not f1s:
        return 0.0, 0.0, 0.0
    return (sum(precisions) / len(precisions),
            sum(recalls) / len(recalls),
            sum(f1s) / len(f1s))
