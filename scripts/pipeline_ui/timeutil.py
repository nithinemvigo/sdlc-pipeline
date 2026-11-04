"""Timestamp parsing for transcript entries."""
from datetime import datetime, timezone


def parse_ts(value):
    """Epoch seconds for an ISO timestamp such as '2026-10-29T05:36:11.892Z', else None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()
