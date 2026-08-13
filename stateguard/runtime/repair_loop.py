class RepairBudget:
    def __init__(self, max_cycles_per_fault=3):
        self.limit, self.counts = max_cycles_per_fault, {}

    def record(self, fault_root):
        self.counts[fault_root] = self.counts.get(fault_root, 0) + 1
        return self.counts[fault_root] <= self.limit
