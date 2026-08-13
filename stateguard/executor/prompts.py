REPAIR_PROMPT = """A previously assumed task state has been invalidated.

Fault root:
{fault_root}

Repair goal:
{repair_goal}

Verified progress that must be preserved:
{preserve_nodes}

States that are no longer trusted:
{stale_nodes}

States requiring re-verification:
{reverify_nodes}

Do not restart the task.
Do not redo preserved subgoals unless new evidence invalidates them.
Repair the smallest necessary portion of the task."""
