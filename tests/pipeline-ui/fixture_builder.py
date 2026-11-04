"""Hand-built Claude Code transcripts for the pipeline-ui tests. No real session content."""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from pipeline_ui import transcripts  # noqa: E402
from pipeline_ui.timeutil import parse_ts  # noqa: E402

_counter = itertools.count(1)


def ts(minute, second=0):
    """A fixed-day timestamp in the transcript format."""
    return "2026-10-29T05:%02d:%02d.000Z" % (minute, second)


def tokens(inp=10, out=5, cache_read=0, write_5m=0, write_1h=0, split=False):
    usage = {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": write_5m + write_1h,
    }
    if split or write_1h:
        usage["cache_creation"] = {"ephemeral_5m_input_tokens": write_5m, "ephemeral_1h_input_tokens": write_1h}
    return usage


class Transcript(object):
    """Builds JSONL lines shaped like Claude Code's session and subagent transcripts."""

    def __init__(self, session_id="sess-1", cwd="C:/repo", branch="master", sidechain=False,
                 version="2.1.312", agent_id=None):
        self.session_id = session_id
        self.cwd = cwd
        self.branch = branch
        self.sidechain = sidechain
        self.version = version
        self.agent_id = agent_id
        self.lines = []

    def _entry(self, kind, minute, second):
        entry = {
            "type": kind, "uuid": "u%d" % next(_counter), "sessionId": self.session_id,
            "cwd": self.cwd, "gitBranch": self.branch, "version": self.version,
            "isSidechain": self.sidechain, "timestamp": ts(minute, second),
        }
        if self.agent_id:
            entry["agentId"] = self.agent_id
        return entry

    def add(self, entry):
        self.lines.append(json.dumps(entry))
        return entry

    def raw(self, line):
        self.lines.append(line)

    def command(self, minute, name, args="", second=0):
        entry = self._entry("user", minute, second)
        entry["message"] = {"role": "user", "content": (
            "<command-message>sdlc-pipeline:%s</command-message>\n"
            "<command-name>/sdlc-pipeline:%s</command-name>\n"
            "<command-args>%s</command-args>" % (name, name, args))}
        return self.add(entry)

    def user(self, minute, text, second=0, **extra):
        entry = self._entry("user", minute, second)
        entry["message"] = {"role": "user", "content": text}
        entry.update(extra)
        return self.add(entry)

    def assistant(self, minute, blocks, second=0, model="claude-opus-5-5", usage=None,
                  stop_reason="end_turn", message_id=None):
        entry = self._entry("assistant", minute, second)
        entry["message"] = {
            "id": message_id or "msg_%d" % next(_counter), "role": "assistant", "model": model,
            "content": blocks, "stop_reason": stop_reason,
            "usage": usage if usage is not None else tokens(),
        }
        return self.add(entry)

    def text(self, minute, text, **kw):
        return self.assistant(minute, [{"type": "text", "text": text}], **kw)

    def tool_use(self, minute, name, tool_input, tool_use_id, **kw):
        kw.setdefault("stop_reason", "tool_use")
        return self.assistant(minute, [{"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}], **kw)

    def tool_result(self, minute, tool_use_id, text, is_error=False, second=0):
        entry = self._entry("user", minute, second)
        entry["message"] = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": text, "is_error": is_error}]}
        return self.add(entry)

    def write(self, path, mtime=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            for line in self.lines:
                fh.write(line + "\n")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path


def parsed(transcript):
    """The user/assistant entries of a Transcript, as JsonlFile would keep them (without _line)."""
    out = []
    for line in transcript.lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("type") in ("user", "assistant"):
            out.append(entry)
    return out


def project_folder(cfg, repo):
    return os.path.join(cfg, "projects", transcripts.encode_project_path(repo))


def write_session(cfg, repo, transcript, mtime=None):
    path = os.path.join(project_folder(cfg, repo), transcript.session_id + ".jsonl")
    return transcript.write(path, mtime=mtime)


def write_agent(cfg, repo, session_id, transcript, agent_type, description, tool_use_id,
                spawn_depth=1, meta=True, mtime=None):
    """Write a subagent transcript; agent_type is the full agentType, e.g. 'sdlc-pipeline:planner'."""
    folder = os.path.join(project_folder(cfg, repo), session_id, "subagents")
    path = transcript.write(os.path.join(folder, "agent-%s.jsonl" % transcript.agent_id), mtime=mtime)
    if meta:
        with open(path[:-len(".jsonl")] + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"agentType": agent_type, "description": description,
                       "toolUseId": tool_use_id, "spawnDepth": spawn_depth}, fh)
    return path


def finished_agent(agent_id, minute, session_id="sess-1", cwd="C:/repo", branch="feature/x",
                   model="claude-sonnet-5-5", usage=None, duration=1, synthetic=False, spawn=None):
    """A subagent transcript that ends with SubagentHandback, like a real async pipeline agent."""
    t = Transcript(session_id=session_id, cwd=cwd, branch=branch, sidechain=True, agent_id=agent_id)
    t.user(minute, "Do the task.")
    t.tool_use(minute, "Read", {"file_path": "README.md"}, "tu-%s-1" % agent_id, model=model, usage=usage)
    t.tool_result(minute, "tu-%s-1" % agent_id, "ok")
    if spawn:
        t.tool_use(minute, "Agent", {"subagent_type": "Explore"}, spawn, second=30, model=model)
        t.tool_result(minute, spawn, "Async agent launched successfully.", second=31)
    if synthetic:
        t.assistant(minute, [{"type": "text", "text": "API error"}], second=40, model="<synthetic>",
                    usage=tokens(7, 3), stop_reason="tool_use")
    t.tool_use(minute + duration, "SubagentHandback", {"message": "Done."}, "tu-%s-2" % agent_id, model=model)
    t.tool_result(minute + duration, "tu-%s-2" % agent_id, '{"success":true,"message":"Report delivered to your caller."}')
    return t
