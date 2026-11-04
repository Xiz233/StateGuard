from stateguard.interfaces.observation import Observation


def convert_observation(raw, step=0, screenshot_path=None):
    transition = {}
    if isinstance(raw, tuple):
        if len(raw) != 4:
            raise ValueError(f"unexpected OSWorld step result length: {len(raw)}")
        raw, reward, done, info = raw
        transition = {"reward": reward, "done": done, "info": info}
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValueError(f"OSWorld observation must be a dict, got {type(raw).__name__}")
    metadata = dict(raw.get("metadata") or {})
    metadata.update(transition)
    for key in ("instruction", "terminal"):
        if raw.get(key) is not None:
            metadata[key] = raw[key]
    return Observation(step=step, screenshot=screenshot_path or raw.get("screenshot"),
                       structured_state=raw.get("structured_state"),
                       ui_tree=raw.get("ui_tree", raw.get("accessibility_tree")),
                       visible_text=raw.get("visible_text"),
                       active_app=raw.get("active_app"), metadata=metadata)
