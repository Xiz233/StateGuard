from __future__ import annotations

from stateguard.executor.parser import ActionBounds, validate_action


def _pyautogui_command(action: dict) -> str:
    kind = action["type"]
    if kind == "wait":
        return "WAIT"
    if kind == "click":
        button, clicks = action.get("button", "left"), action.get("clicks", 1)
        if button == "left" and clicks == 1:
            command = f"import pyautogui; pyautogui.click({action['x']}, {action['y']})"
        else:
            command = (
                "import pyautogui; "
                f"pyautogui.click({action['x']}, {action['y']}, "
                f"clicks={clicks}, interval=0.15, button={button!r})"
            )
    elif kind == "type":
        text = action["text"]
        if text.isascii():
            command = f"import pyautogui; pyautogui.write({text!r}, interval=0.01)"
        else:
            # pyautogui.write cannot type Unicode; use the desktop clipboard for that path.
            command = (
                "import pyautogui, pyperclip; "
                f"pyperclip.copy({text!r}); pyautogui.hotkey('ctrl', 'v')"
            )
    elif kind == "hotkey":
        keys = ", ".join(repr(str(key).lower()) for key in action["keys"])
        command = f"import pyautogui; pyautogui.hotkey({keys})"
    elif kind == "scroll":
        commands = ["import pyautogui"]
        if action["dy"]:
            commands.append(f"pyautogui.scroll({int(action['dy'])})")
        if action["dx"]:
            commands.append(f"pyautogui.hscroll({int(action['dx'])})")
        command = "; ".join(commands)
    elif kind == "drag":
        command = (
            "import pyautogui; "
            f"pyautogui.moveTo({action['x1']}, {action['y1']}); "
            f"pyautogui.dragTo({action['x2']}, {action['y2']}, duration=0.5)"
        )
    else:  # validate_action keeps this unreachable.
        raise ValueError(f"unsupported OSWorld action {kind!r}")
    # Current OSWorld accepts a raw command string. Its dict path first requires
    # `action_type`, so the older {"command": ...} wrapper raises KeyError.
    return command


def convert_action(action: dict, screen_size: tuple[int, int] | None = None,
                   action_format: str = "generic") -> dict | str:
    bounds = ActionBounds(*screen_size) if screen_size else None
    validated = validate_action(action, bounds)
    if action_format == "generic":
        return validated
    if action_format == "pyautogui":
        return _pyautogui_command(validated)
    raise ValueError(f"unsupported OSWorld action format {action_format!r}")
