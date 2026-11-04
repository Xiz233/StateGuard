from __future__ import annotations

import io
from pathlib import Path


def observations_near_equal(first, second, max_mean_pixel_delta: float = 0.02) -> bool:
    """Return True when available structured, textual, or visual state is unchanged."""
    if first is None or second is None:
        return False
    left, right = _load_image(first.screenshot), _load_image(second.screenshot)
    if left is not None and right is not None:
        try:
            from PIL import ImageChops, ImageStat
            left = left.convert("RGB").resize((64, 36))
            right = right.convert("RGB").resize((64, 36))
            delta = ImageStat.Stat(ImageChops.difference(left, right)).mean
            return sum(delta) / (len(delta) * 255) <= max_mean_pixel_delta
        finally:
            left.close()
            right.close()
    if first.screenshot is not None and second.screenshot is not None:
        return first.screenshot == second.screenshot
    if first.visible_text and second.visible_text:
        return " ".join(first.visible_text.split()) == " ".join(second.visible_text.split())
    if first.structured_state is not None and second.structured_state is not None:
        return first.structured_state == second.structured_state
    return False


def _load_image(value):
    if value is None:
        return None
    try:
        from PIL import Image
        if isinstance(value, bytes):
            return Image.open(io.BytesIO(value))
        path = Path(value)
        return Image.open(path) if path.is_file() else None
    except Exception:
        return None
