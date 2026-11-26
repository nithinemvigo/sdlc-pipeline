"""A run's overall status."""
from .entries import stop_reason
from .timeutil import parse_ts

RECENT_S = 120


def run_status(run, agents, checkpoints, main_mtime, now):
    """(status, since): status is finished | stopped | waiting | running; since is the epoch the
    client has been waiting from, else None. Rules are checked in this order (spec section 8)."""
    if any(a.agent_type == "ship-pr" and a.status == "finished" for a in agents):
        return "finished", None
    if run.superseded:
        return "stopped", None
    pending = [c for c in checkpoints if c.get("pending")]
    if pending:
        return "waiting", parse_ts(pending[-1].get("time"))
    last = run.entries[-1] if run.entries else None
    ended = last is not None and last.get("type") == "assistant" and stop_reason(last) == "end_turn"
    if any(a.status == "running" for a in agents):
        return "running", None
    if not ended and now - main_mtime <= RECENT_S:
        return "running", None
    if ended:
        return "waiting", parse_ts(last.get("timestamp"))
    return "stopped", None
