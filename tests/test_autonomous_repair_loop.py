from stateguard.runtime.repair_loop import RepairBudget


def test_repair_budget_stops_after_three_cycles():
    budget = RepairBudget(3)
    assert [budget.record("S1") for _ in range(4)] == [True, True, True, False]


def test_repair_budget_survives_root_replacement():
    budget = RepairBudget(2, max_actions_per_cycle=2)
    assert budget.record("S1")
    assert budget.record_action("S1", 1)
    budget.remap_root("S1", "S1R")

    assert budget.counts == {"S1R": 1}
    assert budget.record_action("S1R", 1)
    assert not budget.record_action("S1R", 1)
    assert budget.record("S1R")
    assert not budget.record("S1R")
