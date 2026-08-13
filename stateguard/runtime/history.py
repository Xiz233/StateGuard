class ActionHistory:
    def __init__(self, limit=10):
        self.limit, self.items = limit, []

    def append(self, value):
        self.items.append(value)

    def recent(self):
        return self.items[-self.limit:]
