from stateguard.runtime.repair_loop import RepairBudget


def test_repair_budget_stops_after_three_cycles():
    budget = RepairBudget(3)
    assert [budget.record("S1") for _ in range(4)] == [True, True, True, False]
