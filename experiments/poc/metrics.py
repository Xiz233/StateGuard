def episode_metrics(result, fault_spec, graph):
    root = fault_spec.get("root_node") if fault_spec else None
    predicted = result.root_predictions[-1] if result.root_predictions else None
    expected = set(fault_spec.get("expected_affected", [])) if fault_spec else set()
    affected = set([predicted] + graph.descendants(predicted)) if predicted else set()
    tp = len(expected & affected)
    precision = tp / len(affected) if affected else float(not expected)
    recall = tp / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    expected_preserved = set(fault_spec.get("expected_preserved", [])) if fault_spec else set()
    preservation = len(expected_preserved & set(result.preserved_nodes)) / len(expected_preserved) \
        if expected_preserved else 1.0
    return {"root_localization_accuracy": float(bool(root) and predicted == root),
            "affected_set_f1": f1, "repair_radius": len(set(result.reactivated_nodes)),
            "repair_action_count": len(result.repair_events),
            "progress_preservation_rate": preservation, "total_steps": result.total_steps}
