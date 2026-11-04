class RepairBudget:
    def __init__(self, max_cycles_per_fault=3, max_actions_per_cycle=20):
        self.limit = max_cycles_per_fault
        self.action_limit = max_actions_per_cycle
        self.counts = {}
        self.action_counts = {}

    def record(self, fault_root):
        return self.record_cycle(fault_root)

    def record_cycle(self, fault_root):
        self.counts[fault_root] = self.counts.get(fault_root, 0) + 1
        if self.counts[fault_root] <= self.limit:
            self.action_counts[(fault_root, self.counts[fault_root])] = 0
        return self.counts[fault_root] <= self.limit

    def record_action(self, fault_root, cycle_id):
        key = (fault_root, cycle_id)
        self.action_counts[key] = self.action_counts.get(key, 0) + 1
        return self.action_counts[key] <= self.action_limit

    def remap_root(self, old_root, new_root):
        """Preserve consumed repair budget when replanning replaces its root."""
        if old_root == new_root:
            return
        if old_root in self.counts:
            self.counts[new_root] = max(
                self.counts.get(new_root, 0), self.counts.pop(old_root))
        for (root, cycle_id), count in list(self.action_counts.items()):
            if root != old_root:
                continue
            key = (new_root, cycle_id)
            self.action_counts[key] = max(self.action_counts.get(key, 0), count)
            del self.action_counts[(root, cycle_id)]
