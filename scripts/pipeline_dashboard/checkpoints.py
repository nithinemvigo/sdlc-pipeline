"""Questions the orchestrator asked with AskUserQuestion, and the answers given."""
import re

from .entries import is_typed_by_client, message_text, strip_reminders, tool_results, tool_uses

ANSWER_RE = re.compile(r'"(?:[^"\\]|\\.)*"="((?:[^"\\]|\\.)*)"')
LIMIT = 300


def answer_text(result):
    """'User has answered your questions: "Q"="A". ...' -> 'A' (several joined with '; ')."""
    values = ANSWER_RE.findall(result)
    if values:
        return "; ".join(values)[:LIMIT]
    return result.strip()[:LIMIT]


def _typed_after(window, index):
    for entry in window[index + 1:]:
        if is_typed_by_client(entry):
            return strip_reminders(message_text(entry)).strip()[:LIMIT]
    return None


def _questions(tool_input):
    out = []
    for question in tool_input.get("questions") or []:
        if not isinstance(question, dict):
            continue
        options = [str(o.get("label", "")) for o in (question.get("options") or []) if isinstance(o, dict)]
        out.append({"header": str(question.get("header", "")), "question": str(question.get("question", "")),
                    "options": options})
    return out


def find_checkpoints(window):
    results = {}
    for index, entry in enumerate(window):
        for tool_use_id, text, is_error in tool_results(entry):
            if tool_use_id:
                results[tool_use_id] = (index, text, is_error)
    found = []
    for entry in window:
        for tool_use_id, name, tool_input in tool_uses(entry):
            if name != "AskUserQuestion":
                continue
            checkpoint = {"time": entry.get("timestamp"), "tool_use_id": tool_use_id,
                          "questions": _questions(tool_input), "answer": None,
                          "answered_in_chat": False, "pending": False}
            if tool_use_id in results:
                index, text, is_error = results[tool_use_id]
                if is_error:
                    typed = _typed_after(window, index)
                    checkpoint["answer"] = typed
                    checkpoint["answered_in_chat"] = typed is not None
                    checkpoint["pending"] = typed is None
                else:
                    checkpoint["answer"] = answer_text(text)
            else:
                checkpoint["pending"] = True
            found.append(checkpoint)
    return found
