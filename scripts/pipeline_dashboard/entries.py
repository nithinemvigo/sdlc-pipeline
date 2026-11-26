"""Helpers for reading Claude Code transcript entries (dicts parsed from JSONL)."""
import re

_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def _message(entry):
    msg = entry.get("message")
    return msg if isinstance(msg, dict) else {}


def _join_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    return ""


def message_text(entry):
    """Plain text of a user or assistant entry: string content, or its text parts joined."""
    return _join_text(_message(entry).get("content"))


def strip_reminders(text):
    return _REMINDER_RE.sub("", text)


def tool_uses(entry):
    """[(tool_use_id, name, input_dict)] for an assistant entry."""
    if entry.get("type") != "assistant":
        return []
    content = _message(entry).get("content")
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_input = block.get("input")
            out.append((block.get("id"), block.get("name"), tool_input if isinstance(tool_input, dict) else {}))
    return out


def tool_results(entry):
    """[(tool_use_id, text, is_error)] for a user entry."""
    if entry.get("type") != "user":
        return []
    content = _message(entry).get("content")
    if not isinstance(content, list):
        return []
    return [
        (block.get("tool_use_id"), _join_text(block.get("content")), bool(block.get("is_error")))
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def stop_reason(entry):
    return _message(entry).get("stop_reason")


def model_of(entry):
    model = _message(entry).get("model")
    return model if isinstance(model, str) else None


def is_typed_by_client(entry):
    """True for a user entry the client typed: not a tool result, notification, report or meta entry."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "user", "human"):
        return False
    if tool_results(entry):
        return False
    text = strip_reminders(message_text(entry)).strip()
    if not text:
        return False
    if text.startswith("<task-notification>") or text.startswith("Another Claude session sent a message"):
        return False
    return True
