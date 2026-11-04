def root_prediction_metrics(events, ground_truth_root):
    roots = [event["fault_root"] for event in events if event.get("fault_root")]
    first, eventual = (roots[0] if roots else None), (roots[-1] if roots else None)
    return {"first_root_prediction": first, "eventual_root_prediction": eventual,
            "first_root_accuracy": float(bool(ground_truth_root) and first == ground_truth_root),
            "eventual_root_accuracy": float(bool(ground_truth_root) and eventual == ground_truth_root)}


def preservation_metrics(verified_before_fault, affected, invalidated, repair_targets,
                         final_verified):
    preservable = set(verified_before_fault) - set(affected)
    reexecuted = preservable & set(repair_targets)
    actually = preservable - set(invalidated) - reexecuted
    actually &= set(final_verified)
    n = len(preservable)
    return {"preservable_nodes": sorted(preservable),
            "actually_preserved_nodes": sorted(actually),
            "reexecuted_preserved_nodes": sorted(reexecuted),
            "state_preservation_rate": len(preservable & set(final_verified)) / n if n else 1.0,
            "strict_progress_preservation_rate": len(actually) / n if n else 1.0}


def false_intervention_metrics(events, certified_clean):
    count = sum(
        event.get("intervention_type") == "repair_request" for event in events
    ) if certified_clean else 0
    return {"guard_intervention_count": len(events), "certified_clean": certified_clean,
            "false_intervention_episode": bool(count),
            "false_intervention_event_count": count}


def episode_metrics(result, fault_spec, graph):
    predicted = result.first_root_prediction
    expected = set(fault_spec.get("expected_affected", [])) if fault_spec else set()
    affected = set([predicted] + graph.descendants(predicted)) if predicted else set()
    tp = len(expected & affected)
    precision = tp / len(affected) if affected else float(not expected)
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "first_root_accuracy": result.first_root_accuracy,
        "eventual_root_accuracy": result.eventual_root_accuracy,
        "affected_set_f1": f1,
        "repair_radius": len(set(result.reactivated_nodes)),
        "repair_cycle_count": result.repair_cycle_count,
        "repair_action_count": result.repair_action_count,
        "repair_budget_exhaustions": result.repair_budget_exhaustions,
        "suspicious_checkpoint_count": result.suspicious_checkpoint_count,
        "plan_revision_count": result.plan_revision_count,
        "local_replan_count": result.local_replan_count,
        "local_replan_success_count": result.local_replan_success_count,
        "contracts_generated": result.contracts_generated,
        "contract_revision_count": result.contract_revision_count,
        "nodes_unverifiable": result.nodes_unverifiable,
        "verification_debt_trigger_count": result.verification_debt_trigger_count,
        "executor_overclaim_count": result.executor_overclaim_count,
        "executor_finish_reconciliation_count": (
            result.executor_finish_reconciliation_count),
        "guard_parse_fail_open_count": result.guard_parse_fail_open_count,
        "guard_strategy_normalization_count": result.guard_strategy_normalization_count,
        "guard_progress_update_drop_count": result.guard_progress_update_drop_count,
        "replanner_fallback_count": result.replanner_fallback_count,
        "trace_entry_count": result.trace_entry_count,
        "frontier_recovery_count": result.frontier_recovery_count,
        "state_preservation_rate": result.state_preservation_rate,
        "strict_progress_preservation_rate": result.strict_progress_preservation_rate,
        "false_intervention_episode": result.false_intervention_episode,
        "total_steps": result.total_steps,
    }
