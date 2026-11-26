"""Subagents: metadata, state, model, usage, and the run each one belongs to."""
import re
from collections import Counter

from . import usage as usage_mod
from .entries import message_text, model_of, stop_reason, tool_uses
from .timeutil import parse_ts

PREFIX = "sdlc-pipeline:"
RUNNING_WINDOW_S = 600
HANDBACK = "SubagentHandback"
TASK_ID_RE = re.compile(r"<task-notification>.*?<task-id>\s*([^<\s]+)\s*</task-id>", re.S)


def _str(meta, key):
    value = meta.get(key)
    return value if isinstance(value, str) and value else None


class Agent(object):
    def __init__(self, agent_id, meta, entries, mtime, path=None):
        self.agent_id = agent_id
        raw_type = _str(meta, "agentType") or "unknown"
        self.agent_type = raw_type[len(PREFIX):] if raw_type.startswith(PREFIX) else raw_type
        self.description = _str(meta, "description") or ""
        self.tool_use_id = _str(meta, "toolUseId")
        depth = meta.get("spawnDepth")
        self.spawn_depth = depth if isinstance(depth, int) and not isinstance(depth, bool) else 1
        self.entries = entries
        self.mtime = mtime
        self.path = path
        stamps = [e["timestamp"] for e in entries if isinstance(e.get("timestamp"), str)]
        self.first_ts = stamps[0] if stamps else None
        self.last_ts = stamps[-1] if stamps else None
        self.model = main_model(entries)
        self.usage_by_model = usage_mod.usage_by_model(entries)
        self.own_tool_use_ids = set(tid for e in entries for tid, _name, _input in tool_uses(e) if tid)
        self.parent_id = None
        self.stage = None
        self.fix = False
        self.other = False
        self.status = None


def main_model(entries):
    """The model used most often, ignoring Claude Code's '<synthetic>' error entries."""
    counts = Counter()
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        model = model_of(entry)
        if model and model != "<synthetic>":
            counts[model] += 1
    return counts.most_common(1)[0][0] if counts else None


def agent_state(entries, mtime, now, notified=False):
    last_handback = -1
    for index, entry in enumerate(entries):
        if any(name == HANDBACK for _tid, name, _input in tool_uses(entry)):
            last_handback = index
    if last_handback >= 0:
        if not any(e.get("type") == "assistant" for e in entries[last_handback + 1:]):
            return "finished"
    elif notified:
        return "finished"
    if entries and entries[-1].get("type") == "assistant" and stop_reason(entries[-1]) == "end_turn":
        return "finished"
    if now - mtime <= RUNNING_WINDOW_S:
        return "running"
    return "interrupted"


def notified_ids(main_entries):
    """Agent ids named by <task-notification> messages in the main session."""
    ids = set()
    for entry in main_entries:
        if entry.get("type") != "user":
            continue
        for match in TASK_ID_RE.finditer(message_text(entry)):
            ids.add(match.group(1))
    return ids


def _run_by_time(runs, stamp):
    moment = parse_ts(stamp)
    if moment is None:
        return None
    chosen = None
    for run in runs:
        started = parse_ts(run.started_at)
        if started is not None and started <= moment:
            chosen = run
    return chosen


def assign_agents(runs, agents):
    """{run_id: [agents]}: by the main-session tool call that launched each agent, through the
    parent agent for nested ones, else by start time. Sets agent.parent_id."""
    by_tool = {}
    for run in runs:
        for entry in run.entries:
            for tool_use_id, _name, _input in tool_uses(entry):
                if tool_use_id:
                    by_tool[tool_use_id] = run
    owner = {}
    for agent in agents:
        for tool_use_id in agent.own_tool_use_ids:
            owner[tool_use_id] = agent
    result = dict((run.run_id, []) for run in runs)
    for agent in agents:
        run = by_tool.get(agent.tool_use_id) if agent.tool_use_id else None
        parent = owner.get(agent.tool_use_id) if agent.tool_use_id else None
        if parent is not None and parent is not agent:
            agent.parent_id = parent.agent_id
            if run is None and parent.tool_use_id:
                run = by_tool.get(parent.tool_use_id)
        if run is None:
            run = _run_by_time(runs, agent.first_ts)
        if run is not None:
            result[run.run_id].append(agent)
    for run_id in result:
        result[run_id].sort(key=lambda a: a.first_ts or "")
    return result
