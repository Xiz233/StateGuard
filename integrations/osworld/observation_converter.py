from stateguard.interfaces.observation import Observation


def convert_observation(raw, step=0, screenshot_path=None):
    raw = raw or {}
    return Observation(step=step, screenshot=screenshot_path or raw.get("screenshot"),
                       structured_state=raw.get("structured_state"),
                       ui_tree=raw.get("ui_tree"), visible_text=raw.get("visible_text"),
                       active_app=raw.get("active_app"), metadata=raw.get("metadata"))
