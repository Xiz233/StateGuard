# OSWorld integration

`OSWorldAdapter` lazily imports `desktop_env`. It strictly accepts click, type,
hotkey, scroll, drag, and wait actions; malformed actions are rejected without
guessing. After OSWorld is installed, add reviewed DAGs under `configs/tasks/osworld/`.
