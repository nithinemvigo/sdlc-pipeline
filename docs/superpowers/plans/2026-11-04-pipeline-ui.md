# /pipeline-ui — local run dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `/sdlc-pipeline:pipeline-ui` command that opens a local, read-only browser dashboard and then runs `/pipeline-all`, `/pipeline` or `/pipeline-parallel` unchanged; the dashboard shows runs, stages, agents, token usage and cost, questions and answers, and each task's commits and diffs, live.

**Architecture:** A Python standard-library package `scripts/pipeline_ui/` reads what already exists — Claude Code's session and subagent transcripts (`<config dir>/projects/<encoded repo path>/`), git, and `docs/plans/` — and builds JSON. `scripts/pipeline-ui.py` serves that JSON and one self-contained HTML page on `127.0.0.1`, started detached by the command. The existing pipelines are not touched.

**Tech Stack:** Python 3.8+ standard library (`http.server`, `json`, `subprocess`, `unittest`); vanilla HTML/CSS/JS; Markdown command file.

**Spec:** `docs/superpowers/specs/2026-11-04-pipeline-ui-design.md`

## Global Constraints

- Branch `feature/pipeline-ui` (cut from `feature/pipeline-all`). Never commit to `master`. Do not push.
- **Python 3.8+, standard library only.** No `match`, no `str.removeprefix`, no `list[str]`/`dict[...]` annotations, no walrus operator, no third-party packages.
- Do NOT modify `commands/pipeline.md`, `commands/pipeline-all.md`, `commands/pipeline-parallel.md`, anything in `agents/`, `hooks/`, or the BA scripts.
- The dashboard is read-only. The only files it writes are its state file and log under `<config dir>/sdlc-pipeline/ui/` — never inside the repository or the transcript folders.
- Bind to `127.0.0.1` only. Git is always called with an argument list, never through a shell.
- The page never uses `innerHTML`, `insertAdjacentHTML` or `document.write`, and loads nothing from the internet.
- New text files are UTF-8 with LF line endings.
- Context-budget hook: files over 250 lines / 20,000 bytes are Read in windows (offset/limit ≤200). Never bypass the hook.
- Every commit message ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, whatever model you are.
- Tests: `python -I -m unittest discover -s tests/pipeline-ui` (whole suite, under a minute). One file: add `-p test_<name>.py`.
- Existing suites must stay green: `python -I -m unittest discover -s tests/acceptance` and `python -m unittest discover -s hooks/tests`.

## Verified transcript facts (2026-10-29 EMI run, Claude Code 2.1.312)

The code relies on these; they were checked against a real `/pipeline-all` run, not assumed:

- Folder name = absolute project path with every non-`[A-Za-z0-9]` character replaced by `-`.
- Subagents: `<session>/subagents/agent-<id>.jsonl` + `agent-<id>.meta.json` (`agentType`, `description`, `toolUseId`, `spawnDepth`).
- A command run is a user entry whose string content starts `<command-message>…<command-name>/sdlc-pipeline:pipeline-all</command-name><command-args>…`. A Skill hand-off is a `tool_result` "Launching skill: …", not a new command entry.
- One API response can be written as several assistant lines with the same `message.id` and identical `usage` (51 of 155 in the EMI main session) — count each id once.
- Pipeline agents are async: every assistant entry has `stop_reason: "tool_use"`; a finished agent ends with a `SubagentHandback` tool call and its result "Report delivered to your caller."; the main session then gets a user entry `<task-notification>…<task-id><agent id></task-id>…` with an `origin` of kind `task-notification`.

---

### Task 1: Package skeleton, transcript reader and test fixtures

**Files:**
- Create: `scripts/pipeline_ui/__init__.py`
- Create: `scripts/pipeline_ui/timeutil.py`
- Create: `scripts/pipeline_ui/entries.py`
- Create: `scripts/pipeline_ui/transcripts.py`
- Create: `tests/pipeline-ui/fixture_builder.py`
- Test: `tests/pipeline-ui/test_transcripts.py`

**Interfaces:**
- Produces:
  - `timeutil.parse_ts(value) -> float | None` (epoch seconds; accepts `...Z`).
  - `entries.message_text(entry) -> str`, `entries.strip_reminders(text) -> str`, `entries.tool_uses(entry) -> [(id, name, input_dict)]`, `entries.tool_results(entry) -> [(tool_use_id, text, is_error)]`, `entries.stop_reason(entry)`, `entries.model_of(entry)`, `entries.is_typed_by_client(entry) -> bool`.
  - `transcripts.config_dir(environ=None) -> str`, `encode_project_path(path) -> str`, `worktree_paths(repo) -> [str]`, `project_paths(repo) -> [str]`, `transcript_folders(repo, cfg=None) -> [str]`, `list_sessions(folder) -> [(session_id, path)]`, `subagent_files(folder, session_id) -> [(agent_id, jsonl_path, meta_path_or_None)]`, `read_meta(path_or_None) -> dict`.
  - `transcripts.JsonlFile(path)` with `.refresh()`, `.entries` (user/assistant dicts, each with `_line` = 1-based physical line), `.bad_lines`, `.versions`, `.mtime`; `transcripts.FileCache().get(path) -> JsonlFile` (refreshed).
  - Test helpers in `fixture_builder`: `ts(minute, second=0)`, `tokens(...)`, `Transcript`, `parsed(transcript)`, `project_folder(cfg, repo)`, `write_session(...)`, `write_agent(...)`, `finished_agent(...)` (later tasks add `make_git_repo` and `emi_like`).

- [ ] **Step 1: Create the package and the fixture builder**

`scripts/pipeline_ui/__init__.py`:

```python
"""Readers behind the /pipeline-ui dashboard. Standard library only, Python 3.8+."""
```

`tests/pipeline-ui/fixture_builder.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

`tests/pipeline-ui/test_transcripts.py`:

```python
"""Tests for pipeline_ui.transcripts, entries and timeutil."""
import json
import os
import shutil
import tempfile
import unittest

import fixture_builder as fb
from pipeline_ui import entries, timeutil, transcripts


class EncodeTest(unittest.TestCase):
    def test_every_non_alphanumeric_becomes_dash(self):
        if os.name == "nt":
            self.assertEqual(
                transcripts.encode_project_path(r"C:\Users\EMVIGO-USER\Muhassin\workspace\claude-investigation\emi"),
                "C--Users-EMVIGO-USER-Muhassin-workspace-claude-investigation-emi")
        else:
            self.assertEqual(transcripts.encode_project_path("/home/dev/my_repo.v2"), "-home-dev-my-repo-v2")

    def test_config_dir_prefers_env(self):
        self.assertEqual(transcripts.config_dir({"CLAUDE_CONFIG_DIR": "/x/cfg"}), "/x/cfg")
        self.assertTrue(transcripts.config_dir({}).endswith(".claude"))


class FoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "cfg")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direct_folder(self):
        t = fb.Transcript(cwd=self.repo)
        t.user(0, "hi")
        fb.write_session(self.cfg, self.repo, t)
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [fb.project_folder(self.cfg, self.repo)])

    def test_fallback_scan_matches_cwd(self):
        other = os.path.join(self.cfg, "projects", "shortened-name")
        t = fb.Transcript(cwd=self.repo)
        t.user(0, "hi")
        t.write(os.path.join(other, "s.jsonl"))
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [other])

    def test_no_folders(self):
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [])

    def test_lists_sessions_and_subagents(self):
        folder = fb.project_folder(self.cfg, self.repo)
        main = fb.Transcript(session_id="s1", cwd=self.repo)
        main.user(0, "hi")
        fb.write_session(self.cfg, self.repo, main)
        with_meta = fb.Transcript(session_id="s1", cwd=self.repo, sidechain=True, agent_id="a1")
        with_meta.user(0, "go")
        fb.write_agent(self.cfg, self.repo, "s1", with_meta, "sdlc-pipeline:planner", "Plan it", "tu-1")
        no_meta = fb.Transcript(session_id="s1", cwd=self.repo, sidechain=True, agent_id="a2")
        no_meta.user(0, "go")
        fb.write_agent(self.cfg, self.repo, "s1", no_meta, "x", "y", "tu-2", meta=False)

        self.assertEqual(transcripts.list_sessions(folder), [("s1", os.path.join(folder, "s1.jsonl"))])
        files = transcripts.subagent_files(folder, "s1")
        self.assertEqual([f[0] for f in files], ["a1", "a2"])
        self.assertEqual(transcripts.read_meta(files[0][2])["agentType"], "sdlc-pipeline:planner")
        self.assertIsNone(files[1][2])
        self.assertEqual(transcripts.read_meta(None), {})


class JsonlFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "s.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _append(self, text):
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def test_reads_only_new_complete_lines(self):
        self._append(json.dumps({"type": "user", "version": "2.1.312"}) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        self.assertEqual(len(f.entries), 1)
        self._append(json.dumps({"type": "assistant"}) + "\n" + '{"type": "user"')
        f.refresh()
        self.assertEqual(len(f.entries), 2)
        self._append("}\n")
        f.refresh()
        self.assertEqual([e["_line"] for e in f.entries], [1, 2, 3])
        self.assertEqual(f.versions, {"2.1.312"})

    def test_counts_bad_lines_and_skips_other_types(self):
        self._append("{not json\n" + json.dumps({"type": "queue-operation", "version": "2.1.400"}) + "\n"
                     + json.dumps([1, 2]) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        self.assertEqual(f.entries, [])
        self.assertEqual(f.bad_lines, 2)
        self.assertEqual(f.versions, {"2.1.400"})

    def test_shrunk_file_is_reread(self):
        self._append(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "user"}) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"type": "assistant"}) + "\n")
        f.refresh()
        self.assertEqual([e["type"] for e in f.entries], ["assistant"])

    def test_cache_returns_refreshed_file(self):
        self._append(json.dumps({"type": "user"}) + "\n")
        cache = transcripts.FileCache()
        self.assertEqual(len(cache.get(self.path).entries), 1)
        self._append(json.dumps({"type": "user"}) + "\n")
        self.assertEqual(len(cache.get(self.path).entries), 2)


class EntriesTest(unittest.TestCase):
    def test_text_and_tools(self):
        t = fb.Transcript()
        use = t.tool_use(0, "Skill", {"skill": "x"}, "tu-1")
        self.assertEqual(entries.tool_uses(use), [("tu-1", "Skill", {"skill": "x"})])
        result = t.tool_result(0, "tu-1", "done", is_error=True)
        self.assertEqual(entries.tool_results(result), [("tu-1", "done", True)])
        self.assertEqual(entries.message_text(t.user(0, "hello")), "hello")
        self.assertEqual(entries.stop_reason(use), "tool_use")
        self.assertEqual(entries.model_of(use), "claude-opus-5-5")

    def test_typed_by_client(self):
        t = fb.Transcript()
        self.assertTrue(entries.is_typed_by_client(t.user(0, "Approve it")))
        self.assertFalse(entries.is_typed_by_client(
            t.user(0, "<task-notification>\n<task-id>a1</task-id>", origin={"kind": "task-notification"})))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "report", isMeta=True)))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "<system-reminder>x</system-reminder>")))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "Another Claude session sent a message: hi")))
        self.assertFalse(entries.is_typed_by_client(t.tool_result(0, "tu", "x")))

    def test_parse_ts(self):
        a = timeutil.parse_ts("2026-10-29T05:36:11.892Z")
        b = timeutil.parse_ts("2026-10-29T05:36:10.892Z")
        self.assertAlmostEqual(a - b, 1.0)
        self.assertIsNone(timeutil.parse_ts("nope"))
        self.assertIsNone(timeutil.parse_ts(None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_transcripts.py`
Expected: ERROR — `ImportError: cannot import name 'transcripts' from 'pipeline_ui'` (or `timeutil`).

- [ ] **Step 4: Implement `timeutil.py`, `entries.py` and `transcripts.py`**

`scripts/pipeline_ui/timeutil.py`:

```python
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
```

`scripts/pipeline_ui/entries.py`:

```python
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
```

`scripts/pipeline_ui/transcripts.py`:

```python
"""Locate a repository's Claude Code transcript folders and read JSONL files incrementally."""
import glob
import json
import os
import re
import subprocess

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")
KEPT_TYPES = ("user", "assistant")
FALLBACK_FILES_PER_FOLDER = 3


def config_dir(environ=None):
    env = os.environ if environ is None else environ
    value = env.get("CLAUDE_CONFIG_DIR")
    return value if value else os.path.join(os.path.expanduser("~"), ".claude")


def encode_project_path(path):
    """Claude Code's folder name for a project: every non-alphanumeric character becomes '-'."""
    return _NON_ALNUM.sub("-", os.path.abspath(path))


def _norm(path):
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


def worktree_paths(repo):
    try:
        proc = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"],
                              capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    text = proc.stdout.decode("utf-8", errors="replace")
    return [line[len("worktree "):].strip() for line in text.splitlines() if line.startswith("worktree ")]


def project_paths(repo):
    paths = [os.path.abspath(repo)]
    seen = {_norm(repo)}
    for path in worktree_paths(repo):
        if _norm(path) not in seen:
            seen.add(_norm(path))
            paths.append(os.path.abspath(path))
    return paths


def first_cwd(jsonl_path, max_lines=50):
    """The first 'cwd' value in a transcript, or None."""
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as fh:
            for number, line in enumerate(fh):
                if number >= max_lines:
                    break
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and isinstance(entry.get("cwd"), str):
                    return entry["cwd"]
    except OSError:
        return None
    return None


def transcript_folders(repo, cfg=None):
    """Transcript folders for the repo and its worktrees (direct name first, then a cwd scan)."""
    root = os.path.join(cfg or config_dir(), "projects")
    paths = project_paths(repo)
    folders = []
    missing = False
    for path in paths:
        folder = os.path.join(root, encode_project_path(path))
        if os.path.isdir(folder):
            folders.append(folder)
        else:
            missing = True
    if missing and os.path.isdir(root):
        wanted = {_norm(p) for p in paths}
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            if folder in folders or not os.path.isdir(folder):
                continue
            for jsonl in sorted(glob.glob(os.path.join(glob.escape(folder), "*.jsonl")))[:FALLBACK_FILES_PER_FOLDER]:
                cwd = first_cwd(jsonl)
                if cwd and _norm(cwd) in wanted:
                    folders.append(folder)
                    break
    return folders


def list_sessions(folder):
    """[(session_id, path)] for every main-session transcript in a folder."""
    return [(os.path.basename(p)[:-len(".jsonl")], p)
            for p in sorted(glob.glob(os.path.join(glob.escape(folder), "*.jsonl")))]


def subagent_files(folder, session_id):
    """[(agent_id, jsonl_path, meta_path or None)] for a session's subagents."""
    pattern = os.path.join(glob.escape(os.path.join(folder, session_id, "subagents")), "agent-*.jsonl")
    out = []
    for path in sorted(glob.glob(pattern)):
        agent_id = os.path.basename(path)[len("agent-"):-len(".jsonl")]
        meta = path[:-len(".jsonl")] + ".meta.json"
        out.append((agent_id, path, meta if os.path.isfile(meta) else None))
    return out


def read_meta(path):
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class JsonlFile(object):
    """A JSONL file parsed incrementally. Keeps user/assistant entries only."""

    def __init__(self, path):
        self.path = path
        self._reset()
        self.mtime = 0.0

    def _reset(self):
        self.offset = 0
        self.entries = []
        self.bad_lines = 0
        self.versions = set()
        self._line_no = 0

    def refresh(self):
        """Parse lines added since the last call. Returns True when something new was read."""
        try:
            info = os.stat(self.path)
        except OSError:
            return False
        if info.st_size < self.offset:
            self._reset()
        self.mtime = info.st_mtime
        if info.st_size == self.offset:
            return False
        with open(self.path, "rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
        end = data.rfind(b"\n")
        if end < 0:
            return False  # only a partial line so far
        chunk = data[:end + 1]
        self.offset += len(chunk)
        for raw in chunk.split(b"\n")[:-1]:
            self._line_no += 1
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                self.bad_lines += 1
                continue
            if not isinstance(entry, dict):
                self.bad_lines += 1
                continue
            version = entry.get("version")
            if isinstance(version, str):
                self.versions.add(version)
            if entry.get("type") in KEPT_TYPES:
                entry["_line"] = self._line_no
                self.entries.append(entry)
        return True


class FileCache(object):
    def __init__(self):
        self._files = {}

    def get(self, path):
        jsonl = self._files.get(path)
        if jsonl is None:
            jsonl = self._files[path] = JsonlFile(path)
        jsonl.refresh()
        return jsonl
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_transcripts.py`
Expected: `OK` (13 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_ui/__init__.py scripts/pipeline_ui/timeutil.py scripts/pipeline_ui/entries.py scripts/pipeline_ui/transcripts.py tests/pipeline-ui/fixture_builder.py tests/pipeline-ui/test_transcripts.py
git commit -m "feat: pipeline-ui transcript reader" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Usage, de-duplication and cost estimate

**Files:**
- Create: `scripts/pipeline_ui/usage.py`
- Create: `scripts/pipeline-ui-prices.json`
- Test: `tests/pipeline-ui/test_usage.py`

**Interfaces:**
- Consumes: `fixture_builder.Transcript`, `tokens`, `parsed` (Task 1).
- Produces: `usage.Usage(input=0, output=0, cache_write_5m=0, cache_write_1h=0, cache_read=0)` with `.cache_write`, `.total`, `.add(other)`, `.copy()`, `.to_dict() -> {"input","output","cache_write","cache_read","total"}`; `usage_of(raw_usage) -> Usage`; `usage_by_model(entries) -> {model: Usage}`; `merge([by_model, ...]) -> {model: Usage}` (new objects); `total(by_model) -> Usage`; `load_prices(path=None) -> {model: rates}`; `price_for(model, prices) -> rates | None`; `estimate_cost(by_model, prices) -> (usd_float, complete_bool)`.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline-ui/test_usage.py`:

```python
"""Tests for pipeline_ui.usage."""
import unittest

import fixture_builder as fb
from pipeline_ui import usage


class UsageTest(unittest.TestCase):
    def test_dedupes_by_message_id(self):
        t = fb.Transcript()
        t.text(0, "a", message_id="m1", usage=fb.tokens(10, 5, cache_read=100, write_5m=20))
        t.text(0, "b", message_id="m1", usage=fb.tokens(10, 5, cache_read=100, write_5m=20))
        t.text(1, "c", message_id="m2", model="claude-haiku-5-5", usage=fb.tokens(1, 1, write_1h=8))
        by_model = usage.usage_by_model(fb.parsed(t))
        self.assertEqual(by_model["claude-opus-5-5"].to_dict(),
                         {"input": 10, "output": 5, "cache_write": 20, "cache_read": 100, "total": 135})
        self.assertEqual(by_model["claude-haiku-5-5"].cache_write_1h, 8)
        self.assertEqual(by_model["claude-haiku-5-5"].cache_write_5m, 0)

    def test_user_entries_ignored(self):
        t = fb.Transcript()
        t.user(0, "hi")
        self.assertEqual(usage.usage_by_model(fb.parsed(t)), {})

    def test_unsplit_cache_write_counts_as_5m(self):
        u = usage.usage_of({"input_tokens": 1, "output_tokens": 2, "cache_creation_input_tokens": 30})
        self.assertEqual((u.cache_write_5m, u.cache_write_1h), (30, 0))

    def test_cost_with_known_and_unknown_models(self):
        prices = {"claude-opus-5-5": {"input": 4, "output": 20, "cache_write_5m": 5, "cache_write_1h": 8,
                                      "cache_read": 0.2}}
        by_model = {
            "claude-opus-5-5": usage.Usage(input=1000000, output=100000, cache_write_1h=1000000, cache_read=1000000),
            "<synthetic>": usage.Usage(input=5),
        }
        cost, complete = usage.estimate_cost(by_model, prices)
        self.assertAlmostEqual(cost, 4 + 2 + 8 + 0.2)
        self.assertFalse(complete)
        self.assertEqual(usage.estimate_cost({"claude-opus-5-5": usage.Usage(input=1000000)}, prices), (4.0, True))

    def test_longest_prefix_price(self):
        prices = {"claude-opus-5": {"input": 5}, "claude-opus-5-5": {"input": 4}}
        self.assertEqual(usage.price_for("claude-opus-5-5", prices)["input"], 4)
        self.assertEqual(usage.price_for("claude-opus-5-5[1m]", prices)["input"], 4)
        self.assertEqual(usage.price_for("claude-opus-5-20260101", prices)["input"], 5)
        self.assertIsNone(usage.price_for("gpt-x", prices))

    def test_shipped_price_table(self):
        prices = usage.load_prices()
        for model in ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5",
                      "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"):
            self.assertEqual(set(prices[model]), {"input", "output", "cache_write_5m", "cache_write_1h", "cache_read"})
        self.assertEqual(prices["claude-opus-5-5"]["cache_read"], 0.20)
        self.assertEqual(prices["claude-fable-5-1"]["cache_read"], 0.25)

    def test_merge_does_not_mutate_inputs(self):
        a = {"m": usage.Usage(input=1)}
        b = {"m": usage.Usage(output=2), "n": usage.Usage(cache_read=3)}
        merged = usage.merge([a, b])
        self.assertEqual(usage.total(merged).total, 6)
        self.assertEqual(a["m"].output, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_usage.py`
Expected: ERROR — `ImportError: cannot import name 'usage' from 'pipeline_ui'`.

- [ ] **Step 3: Implement `usage.py` and the price table**

`scripts/pipeline_ui/usage.py`:

```python
"""Token usage per model (each API response counted once) and the estimated cost."""
import json
import os

PRICES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline-ui-prices.json")
RATE_KEYS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


class Usage(object):
    FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")

    def __init__(self, input=0, output=0, cache_write_5m=0, cache_write_1h=0, cache_read=0):
        self.input = input
        self.output = output
        self.cache_write_5m = cache_write_5m
        self.cache_write_1h = cache_write_1h
        self.cache_read = cache_read

    @property
    def cache_write(self):
        return self.cache_write_5m + self.cache_write_1h

    @property
    def total(self):
        return self.input + self.output + self.cache_write + self.cache_read

    def add(self, other):
        for name in self.FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    def copy(self):
        return Usage(*[getattr(self, name) for name in self.FIELDS])

    def to_dict(self):
        return {"input": self.input, "output": self.output, "cache_write": self.cache_write,
                "cache_read": self.cache_read, "total": self.total}


def _int(source, key):
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_of(raw):
    """Usage from one message.usage dict. Cache writes without a TTL split count as 5-minute."""
    split = raw.get("cache_creation") if isinstance(raw, dict) else None
    if isinstance(split, dict) and ("ephemeral_5m_input_tokens" in split or "ephemeral_1h_input_tokens" in split):
        write_5m = _int(split, "ephemeral_5m_input_tokens")
        write_1h = _int(split, "ephemeral_1h_input_tokens")
    else:
        write_5m, write_1h = _int(raw, "cache_creation_input_tokens"), 0
    return Usage(_int(raw, "input_tokens"), _int(raw, "output_tokens"), write_5m, write_1h,
                 _int(raw, "cache_read_input_tokens"))


def usage_by_model(entries):
    """{model: Usage} over assistant entries. A response written on several lines shares one
    message.id and repeats the same usage, so each id is counted once."""
    seen = set()
    out = {}
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        message_id = message.get("id")
        if message_id:
            if message_id in seen:
                continue
            seen.add(message_id)
        model = message.get("model") if isinstance(message.get("model"), str) else "unknown"
        out.setdefault(model, Usage()).add(usage_of(message["usage"]))
    return out


def merge(by_models):
    out = {}
    for by_model in by_models:
        for model, value in by_model.items():
            if model in out:
                out[model].add(value)
            else:
                out[model] = value.copy()
    return out


def total(by_model):
    result = Usage()
    for value in by_model.values():
        result.add(value)
    return result


def load_prices(path=None):
    try:
        with open(path or PRICES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return {}
    return {name: rates for name, rates in models.items()
            if isinstance(rates, dict) and all(isinstance(rates.get(k), (int, float)) for k in RATE_KEYS)}


def price_for(model, prices):
    """Exact match, else the longest price key that the model id starts with."""
    if model in prices:
        return prices[model]
    best = None
    for key in prices:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return prices[best] if best else None


def estimate_cost(by_model, prices):
    """(usd, complete): complete is False when some tokens have no price (e.g. '<synthetic>')."""
    amount = 0.0
    complete = True
    for model, value in by_model.items():
        if value.total == 0:
            continue
        rates = price_for(model, prices)
        if rates is None:
            complete = False
            continue
        amount += (value.input * rates["input"] + value.output * rates["output"]
                   + value.cache_write_5m * rates["cache_write_5m"]
                   + value.cache_write_1h * rates["cache_write_1h"]
                   + value.cache_read * rates["cache_read"]) / 1000000.0
    return amount, complete
```

`scripts/pipeline-ui-prices.json`:

```json
{
  "_source": "Anthropic first-party API rates in USD per million tokens, from the claude-api skill's model table (cached 2026-10-06) and its prompt-caching reference. Cache write = 1.25x input for the 5-minute cache and 2x input for the 1-hour cache; cache read is 0.1x input except where the reference states a model's own rate (Fable 5.1 0.25, Opus 5.5 0.20, Fable 5 1.00). Haiku 5.5 rates are for prompts up to 100K tokens. Check the Anthropic pricing page before relying on these numbers; edit freely.",
  "models": {
    "claude-fable-5-1":  {"input": 10.0, "output": 50.0, "cache_write_5m": 12.5,  "cache_write_1h": 20.0, "cache_read": 0.25},
    "claude-mythos-5-1": {"input": 10.0, "output": 50.0, "cache_write_5m": 12.5,  "cache_write_1h": 20.0, "cache_read": 0.25},
    "claude-fable-5":    {"input": 10.0, "output": 50.0, "cache_write_5m": 12.5,  "cache_write_1h": 20.0, "cache_read": 1.00},
    "claude-opus-5-5":   {"input": 4.0,  "output": 20.0, "cache_write_5m": 5.0,   "cache_write_1h": 8.0,  "cache_read": 0.20},
    "claude-opus-5":     {"input": 5.0,  "output": 25.0, "cache_write_5m": 6.25,  "cache_write_1h": 10.0, "cache_read": 0.50},
    "claude-opus-4-8":   {"input": 5.0,  "output": 25.0, "cache_write_5m": 6.25,  "cache_write_1h": 10.0, "cache_read": 0.50},
    "claude-opus-4-7":   {"input": 5.0,  "output": 25.0, "cache_write_5m": 6.25,  "cache_write_1h": 10.0, "cache_read": 0.50},
    "claude-opus-4-6":   {"input": 5.0,  "output": 25.0, "cache_write_5m": 6.25,  "cache_write_1h": 10.0, "cache_read": 0.50},
    "claude-sonnet-5-5": {"input": 2.0,  "output": 10.0, "cache_write_5m": 2.5,   "cache_write_1h": 4.0,  "cache_read": 0.20},
    "claude-sonnet-5":   {"input": 2.0,  "output": 10.0, "cache_write_5m": 2.5,   "cache_write_1h": 4.0,  "cache_read": 0.20},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0, "cache_write_5m": 3.75,  "cache_write_1h": 6.0,  "cache_read": 0.30},
    "claude-haiku-5-5":  {"input": 0.10, "output": 0.50, "cache_write_5m": 0.125, "cache_write_1h": 0.20, "cache_read": 0.01},
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0,  "cache_write_5m": 1.25,  "cache_write_1h": 2.0,  "cache_read": 0.10}
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_usage.py`
Expected: `OK` (7 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_ui/usage.py scripts/pipeline-ui-prices.json tests/pipeline-ui/test_usage.py
git commit -m "feat: pipeline-ui token usage and cost estimate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Runs and checkpoints

**Files:**
- Create: `scripts/pipeline_ui/runs.py`
- Create: `scripts/pipeline_ui/checkpoints.py`
- Test: `tests/pipeline-ui/test_runs.py`

**Interfaces:**
- Consumes: `entries.message_text`, `tool_uses`, `tool_results`, `strip_reminders`, `is_typed_by_client` (Task 1).
- Produces:
  - `runs.Run` with `.run_id` (`"<session>:<_line of start, or index>"`), `.session_id`, `.command`, `.flow`, `.title`, `.branch`, `.started_at`, `.entries` (main-session entries of the window), `.superseded` (bool).
  - `runs.find_runs(session_id, entries) -> [Run]`; constants `runs.FLOWS`, `runs.BASE_BRANCHES = ("main", "master")`, `runs.CHOOSING = "choosing…"`.
  - `checkpoints.find_checkpoints(window_entries) -> [{"time", "tool_use_id", "questions": [{"header","question","options"}], "answer", "answered_in_chat", "pending"}]`; `checkpoints.answer_text(result) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline-ui/test_runs.py`:

```python
"""Tests for pipeline_ui.runs and pipeline_ui.checkpoints."""
import unittest

import fixture_builder as fb
from pipeline_ui import checkpoints
from pipeline_ui import runs as runs_mod

ASK = {"questions": [{"header": "Plan", "question": "Approve the plan?",
                      "options": [{"label": "Approve"}, {"label": "Change"}]}]}


class FindRunsTest(unittest.TestCase):
    def test_two_runs_in_one_session(self):
        t = fb.Transcript(session_id="s1")
        t.command(0, "pipeline-ui", "Add calculate_emi\nwith details")
        t.tool_use(1, "Skill", {"skill": "sdlc-pipeline:pipeline-all", "args": "Add calculate_emi"}, "tu-skill")
        t.tool_result(1, "tu-skill", "Launching skill: sdlc-pipeline:pipeline-all")
        t.branch = "feature/calculate-emi"
        t.text(5, "Building.")
        t.branch = "master"
        t.text(6, "Back on master.")
        t.command(10, "pipeline", "")
        first, second = runs_mod.find_runs("s1", fb.parsed(t))
        self.assertEqual((first.command, first.flow, first.title, first.branch, first.superseded),
                         ("pipeline-ui", "pipeline-all", "Add calculate_emi", "feature/calculate-emi", True))
        self.assertEqual((second.flow, second.title, second.branch, second.superseded),
                         ("pipeline", "(no request text)", "master", False))
        self.assertEqual(first.run_id, "s1:0")
        self.assertEqual(first.started_at, fb.ts(0))
        self.assertEqual(len(first.entries), 5)

    def test_pipeline_ui_before_the_flow_is_chosen(self):
        t = fb.Transcript()
        t.command(0, "pipeline-ui", "x")
        [run] = runs_mod.find_runs("s", fb.parsed(t))
        self.assertEqual(run.flow, runs_mod.CHOOSING)

    def test_quoted_command_is_not_a_run(self):
        t = fb.Transcript()
        t.command(0, "pipeline", "x")
        t.user(3, "Another Claude session sent a message: <command-name>/sdlc-pipeline:pipeline-all</command-name>")
        t.user(4, "<command-message>x</command-message><command-name>/sdlc-pipeline:pipeline-all</command-name>",
               isMeta=True)
        self.assertEqual(len(runs_mod.find_runs("s", fb.parsed(t))), 1)

    def test_other_commands_and_sidechains_ignored(self):
        t = fb.Transcript()
        t.command(0, "verify-acceptance", "")
        side = fb.Transcript(sidechain=True)
        side.command(1, "pipeline", "")
        self.assertEqual(runs_mod.find_runs("s", fb.parsed(t) + fb.parsed(side)), [])


class CheckpointsTest(unittest.TestCase):
    def test_answer_from_tool_result(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_result(1, "q1", 'User has answered your questions: "Approve the plan?"="Approve". '
                               "You can now continue with the user's answers in mind.")
        [cp] = checkpoints.find_checkpoints(fb.parsed(t))
        self.assertEqual(cp["answer"], "Approve")
        self.assertFalse(cp["pending"])
        self.assertFalse(cp["answered_in_chat"])
        self.assertEqual(cp["questions"], [{"header": "Plan", "question": "Approve the plan?",
                                            "options": ["Approve", "Change"]}])
        self.assertEqual(cp["time"], fb.ts(0))

    def test_answer_typed_in_chat_after_an_error_result(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_result(0, "q1", "Tool result missing due to internal error", is_error=True)
        t.user(1, "<task-notification>\n<task-id>a1</task-id>", origin={"kind": "task-notification"})
        t.user(2, "<system-reminder>ctx</system-reminder>Approve it")
        [cp] = checkpoints.find_checkpoints(fb.parsed(t))
        self.assertEqual(cp["answer"], "Approve it")
        self.assertTrue(cp["answered_in_chat"])
        self.assertFalse(cp["pending"])

    def test_pending(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_use(1, "AskUserQuestion", ASK, "q2")
        t.tool_result(1, "q2", "Tool result missing due to internal error", is_error=True)
        self.assertEqual([cp["pending"] for cp in checkpoints.find_checkpoints(fb.parsed(t))], [True, True])

    def test_unrecognised_result_text_kept(self):
        self.assertEqual(checkpoints.answer_text("  The user declined.  "), "The user declined.")
        self.assertEqual(checkpoints.answer_text('"A?"="x". "B?"="y".'), "x; y")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_runs.py`
Expected: ERROR — `ImportError: cannot import name 'checkpoints' from 'pipeline_ui'`.

- [ ] **Step 3: Implement `runs.py` and `checkpoints.py`**

`scripts/pipeline_ui/runs.py`:

```python
"""Find pipeline runs in a main-session transcript."""
import re

from .entries import message_text, tool_uses

CMD_RE = re.compile(
    r"<command-name>/?(?:sdlc-pipeline:)?(pipeline-all|pipeline-parallel|pipeline-ui|pipeline)</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
FLOWS = ("pipeline-all", "pipeline", "pipeline-parallel")
BASE_BRANCHES = ("main", "master")
CHOOSING = "choosing\u2026"
TITLE_LIMIT = 120


def is_run_start(entry):
    """The command name when this entry starts a pipeline run, else None.

    Only an entry whose text *starts* with the command markup counts: hand-back reports from
    subagents arrive as user messages too, and one that quotes a command must not open a run.
    """
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    text = message_text(entry).lstrip()
    if not (text.startswith("<command-message>") or text.startswith("<command-name>")):
        return None
    match = CMD_RE.search(text)
    return match.group(1) if match else None


def run_title(text):
    match = ARGS_RE.search(text)
    args = match.group(1).strip() if match else ""
    if not args:
        return "(no request text)"
    return args.splitlines()[0].strip()[:TITLE_LIMIT]


def run_flow(command, window):
    """The flow that runs: the command itself, or for pipeline-ui the flow it handed off to."""
    if command != "pipeline-ui":
        return command
    for entry in window:
        for _tool_use_id, name, tool_input in tool_uses(entry):
            skill = tool_input.get("skill")
            if name == "Skill" and isinstance(skill, str) and skill.startswith("sdlc-pipeline:"):
                flow = skill.split(":", 1)[1]
                if flow in FLOWS:
                    return flow
    return CHOOSING


def run_branch(window):
    """The latest non-base branch seen in the window, else the base branch, else ''."""
    branch = None
    base = None
    for entry in window:
        name = entry.get("gitBranch")
        if not isinstance(name, str) or not name or name == "HEAD":
            continue
        if name in BASE_BRANCHES:
            base = base or name
        else:
            branch = name
    return branch or base or ""


class Run(object):
    def __init__(self, run_id, session_id, command, window, superseded):
        self.run_id = run_id
        self.session_id = session_id
        self.command = command
        self.entries = window
        self.superseded = superseded
        self.started_at = window[0].get("timestamp")
        self.title = run_title(message_text(window[0]))
        self.flow = run_flow(command, window)
        self.branch = run_branch(window)


def find_runs(session_id, entries):
    main = [e for e in entries if not e.get("isSidechain")]
    starts = []
    for index, entry in enumerate(main):
        command = is_run_start(entry)
        if command:
            starts.append((index, command))
    found = []
    for number, (index, command) in enumerate(starts):
        end = starts[number + 1][0] if number + 1 < len(starts) else len(main)
        line = main[index].get("_line", index)
        found.append(Run("%s:%d" % (session_id, line), session_id, command, main[index:end],
                         number + 1 < len(starts)))
    return found
```

`scripts/pipeline_ui/checkpoints.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_runs.py`
Expected: `OK` (8 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_ui/runs.py scripts/pipeline_ui/checkpoints.py tests/pipeline-ui/test_runs.py
git commit -m "feat: pipeline-ui runs and checkpoints" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Agents

**Files:**
- Create: `scripts/pipeline_ui/agents.py`
- Test: `tests/pipeline-ui/test_agents.py`

**Interfaces:**
- Consumes: `entries.*` (Task 1), `usage.usage_by_model` (Task 2), `runs.find_runs`, `Run` (Task 3).
- Produces:
  - `agents.Agent(agent_id, meta, entries, mtime, path=None)` with `.agent_id`, `.agent_type` (prefix `sdlc-pipeline:` removed; `"unknown"` without meta), `.description`, `.tool_use_id`, `.spawn_depth`, `.entries`, `.mtime`, `.path`, `.first_ts`, `.last_ts`, `.model`, `.usage_by_model`, `.own_tool_use_ids`, and attributes set later: `.parent_id`, `.stage`, `.fix`, `.other`, `.status` (all `None`/`False` initially).
  - `agents.main_model(entries) -> str | None`; `agents.agent_state(entries, mtime, now, notified=False) -> "finished" | "running" | "interrupted"`; `agents.notified_ids(main_entries) -> set`; `agents.assign_agents(runs, agents) -> {run_id: [Agent sorted by first_ts]}` (also sets `.parent_id`).

- [ ] **Step 1: Write the failing tests**

`tests/pipeline-ui/test_agents.py`:

```python
"""Tests for pipeline_ui.agents."""
import unittest

import fixture_builder as fb
from pipeline_ui import agents
from pipeline_ui import runs as runs_mod
from pipeline_ui.timeutil import parse_ts

NOW = parse_ts(fb.ts(30))


class AgentStateTest(unittest.TestCase):
    def test_handback_means_finished(self):
        self.assertEqual(agents.agent_state(fb.parsed(fb.finished_agent("a1", 0)), 0, NOW), "finished")

    def test_work_after_handback_is_running_again(self):
        t = fb.finished_agent("a1", 0)
        t.user(5, "One more thing")
        t.tool_use(6, "Read", {}, "tu-x")
        self.assertEqual(agents.agent_state(fb.parsed(t), NOW - 30, NOW), "running")

    def test_without_handback(self):
        t = fb.Transcript(sidechain=True, agent_id="a1")
        t.user(0, "go")
        t.tool_use(1, "Read", {}, "tu-1")
        entries = fb.parsed(t)
        self.assertEqual(agents.agent_state(entries, 0, NOW, notified=True), "finished")
        self.assertEqual(agents.agent_state(entries, NOW - 60, NOW), "running")
        self.assertEqual(agents.agent_state(entries, NOW - 3600, NOW), "interrupted")

    def test_end_turn_is_finished(self):
        t = fb.Transcript(sidechain=True, agent_id="a1")
        t.user(0, "go")
        t.text(1, "All done.")
        self.assertEqual(agents.agent_state(fb.parsed(t), NOW - 3600, NOW), "finished")

    def test_notified_ids(self):
        t = fb.Transcript()
        t.user(0, "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>",
               origin={"kind": "task-notification"})
        t.user(1, "<task-id>a2</task-id> without the notification wrapper")
        self.assertEqual(agents.notified_ids(fb.parsed(t)), {"a1"})


class AgentFieldsTest(unittest.TestCase):
    def test_fields(self):
        t = fb.finished_agent("a1", 3, model="claude-sonnet-5-5", usage=fb.tokens(100, 50), synthetic=True)
        a = agents.Agent("a1", {"agentType": "sdlc-pipeline:planner", "description": "Plan EMI",
                                "toolUseId": "tu-pl", "spawnDepth": 1}, fb.parsed(t), mtime=0, path="p")
        self.assertEqual((a.agent_type, a.description, a.tool_use_id, a.spawn_depth, a.model, a.path),
                         ("planner", "Plan EMI", "tu-pl", 1, "claude-sonnet-5-5", "p"))
        self.assertEqual((a.first_ts, a.last_ts), (fb.ts(3), fb.ts(4)))
        self.assertIn("<synthetic>", a.usage_by_model)
        self.assertIn("tu-a1-2", a.own_tool_use_ids)

    def test_missing_meta(self):
        a = agents.Agent("a2", {}, [], 0)
        self.assertEqual((a.agent_type, a.tool_use_id, a.first_ts, a.model, a.spawn_depth),
                         ("unknown", None, None, None, 1))


class AssignTest(unittest.TestCase):
    def test_by_tool_use_id_parent_and_time(self):
        main = fb.Transcript(session_id="s1")
        main.command(0, "pipeline", "one")
        main.tool_use(1, "Agent", {"subagent_type": "sdlc-pipeline:planner"}, "tu-pl")
        main.command(10, "pipeline", "two")
        main.tool_use(11, "Agent", {}, "tu-cr")
        run1, run2 = runs_mod.find_runs("s1", fb.parsed(main))

        planner = agents.Agent("a-pl", {"agentType": "sdlc-pipeline:planner", "toolUseId": "tu-pl"},
                               fb.parsed(fb.finished_agent("a-pl", 2, spawn="tu-nested")), 0)
        nested = agents.Agent("a-n", {"agentType": "Explore", "toolUseId": "tu-nested", "spawnDepth": 2},
                              fb.parsed(fb.finished_agent("a-n", 3)), 0)
        reviewer = agents.Agent("a-cr", {"agentType": "sdlc-pipeline:code-reviewer", "toolUseId": "tu-cr"},
                                fb.parsed(fb.finished_agent("a-cr", 12)), 0)
        orphan = agents.Agent("a-o", {}, fb.parsed(fb.finished_agent("a-o", 15)), 0)

        by_run = agents.assign_agents([run1, run2], [reviewer, nested, planner, orphan])
        self.assertEqual([a.agent_id for a in by_run[run1.run_id]], ["a-pl", "a-n"])
        self.assertEqual([a.agent_id for a in by_run[run2.run_id]], ["a-cr", "a-o"])
        self.assertEqual(nested.parent_id, "a-pl")
        self.assertIsNone(planner.parent_id)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_agents.py`
Expected: ERROR — `ImportError: cannot import name 'agents' from 'pipeline_ui'`.

- [ ] **Step 3: Implement `agents.py`**

`scripts/pipeline_ui/agents.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_agents.py`
Expected: `OK` (8 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_ui/agents.py tests/pipeline-ui/test_agents.py
git commit -m "feat: pipeline-ui agent records and run attribution" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Stages and run status

**Files:**
- Create: `scripts/pipeline_ui/stages.py`
- Create: `scripts/pipeline_ui/status.py`
- Test: `tests/pipeline-ui/test_stages.py`

**Interfaces:**
- Consumes: `agents.Agent` with `.agent_type`, `.status`, `.first_ts` (Task 4); `runs.Run` (Task 3); `entries.stop_reason`; `timeutil.parse_ts`.
- Produces:
  - `stages.STAGES` (ordered `(key, label)`), `stages.ORDER`, `stages.LABEL`, `stages.AGENT_STAGE`, `stages.FLOW_STAGES`.
  - `stages.place_agents(agents)` — sets `.stage`, `.fix`, `.other` (agents in start order).
  - `stages.build_stages(flow, agents, run_status) -> [{"key","label","state","agents":[agent_id]}]`; states `"in progress" | "done" | "skipped" | "not reached"`.
  - `status.run_status(run, agents, checkpoints, main_mtime, now) -> (status, since_epoch_or_None)`; statuses `"finished" | "stopped" | "waiting" | "running"`.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline-ui/test_stages.py`:

```python
"""Tests for pipeline_ui.stages and pipeline_ui.status."""
import os
import unittest

import fixture_builder as fb
from pipeline_ui import agents, stages, status
from pipeline_ui import runs as runs_mod
from pipeline_ui.timeutil import parse_ts

NOW = parse_ts(fb.ts(30))
AGENTS_DIR = os.path.join(fb.REPO_ROOT, "agents")


def make(agent_id, agent_type, minute, state="finished"):
    agent_kind = agent_type if agent_type == "general-purpose" else "sdlc-pipeline:" + agent_type
    agent = agents.Agent(agent_id, {"agentType": agent_kind}, fb.parsed(fb.finished_agent(agent_id, minute)), 0)
    agent.status = state
    return agent


class PlaceTest(unittest.TestCase):
    def test_mapping_fix_round_and_other(self):
        seq = [make("a1", "requirements-writer", 1), make("a2", "planner", 2), make("a3", "implementer", 3),
               make("a4", "acceptance-verifier", 5), make("a5", "implementer", 7), make("a6", "general-purpose", 8)]
        stages.place_agents(seq)
        self.assertEqual([(a.stage, a.fix, a.other) for a in seq],
                         [("R", False, False), ("1", False, False), ("3", False, False),
                          ("5.85", False, False), ("5.85", True, False), ("5.85", False, True)])

    def test_every_plugin_agent_has_a_stage(self):
        names = [f[:-3] for f in os.listdir(AGENTS_DIR) if f.endswith(".md")]
        self.assertTrue(names)
        for name in names:
            self.assertIn(name, stages.AGENT_STAGE, name)


class BuildStagesTest(unittest.TestCase):
    def states(self, flow, seq, run_status):
        stages.place_agents(seq)
        return dict((s["key"], s["state"]) for s in stages.build_stages(flow, seq, run_status))

    def test_waiting_at_plan_approval(self):
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "ceo-reviewer", 2),
                                       make("a3", "eng-reviewer", 2)], "waiting")
        self.assertEqual((out["0.8"], out["1"], out["2"], out["3"]), ("skipped", "done", "done", "not reached"))
        self.assertNotIn("1-B", out)

    def test_in_progress(self):
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "implementer", 3, "running")], "running")
        self.assertEqual((out["1"], out["3"]), ("done", "in progress"))
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "implementer", 3)], "running")
        self.assertEqual(out["3"], "in progress")

    def test_bug_track_shows_investigate_not_plan(self):
        out = self.states("pipeline", [make("a1", "investigator", 1)], "running")
        self.assertIn("1-B", out)
        self.assertNotIn("1", out)

    def test_pipeline_all_stage_list(self):
        keys = [s["key"] for s in stages.build_stages("pipeline-all", [], "running")]
        self.assertEqual(keys, stages.FLOW_STAGES["pipeline-all"])


class StatusTest(unittest.TestCase):
    def run_of(self, t):
        return runs_mod.find_runs("s", fb.parsed(t))[0]

    def base(self):
        t = fb.Transcript()
        t.command(0, "pipeline", "x")
        return t

    def test_finished_when_ship_pr_finished(self):
        self.assertEqual(status.run_status(self.run_of(self.base()), [make("a", "ship-pr", 1)], [], 0, NOW),
                         ("finished", None))

    def test_superseded_run_is_stopped(self):
        t = self.base()
        t.command(5, "pipeline", "y")
        self.assertEqual(status.run_status(runs_mod.find_runs("s", fb.parsed(t))[0], [], [], NOW, NOW),
                         ("stopped", None))

    def test_pending_question_waits(self):
        cps = [{"pending": True, "time": fb.ts(5)}]
        self.assertEqual(status.run_status(self.run_of(self.base()), [], cps, NOW, NOW),
                         ("waiting", parse_ts(fb.ts(5))))

    def test_running_agent_wins_over_ended_turn(self):
        t = self.base()
        t.text(1, "Dispatched the planner.")
        self.assertEqual(status.run_status(self.run_of(t), [make("a", "planner", 1, "running")], [], 0, NOW),
                         ("running", None))

    def test_recent_activity_mid_turn(self):
        t = self.base()
        t.tool_use(1, "Bash", {}, "tu")
        self.assertEqual(status.run_status(self.run_of(t), [], [], NOW - 30, NOW), ("running", None))
        self.assertEqual(status.run_status(self.run_of(t), [], [], NOW - 600, NOW), ("stopped", None))

    def test_ended_turn_waits(self):
        t = self.base()
        t.text(1, "Type Continue now.")
        self.assertEqual(status.run_status(self.run_of(t), [], [], 0, NOW), ("waiting", parse_ts(fb.ts(1))))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_stages.py`
Expected: ERROR — `ImportError: cannot import name 'stages' from 'pipeline_ui'`.

- [ ] **Step 3: Implement `stages.py` and `status.py`**

`scripts/pipeline_ui/stages.py`:

```python
"""Map agents to pipeline stages and work out each stage's state."""

STAGES = [
    ("R", "Requirements"), ("Q", "BA analysis"), ("0.8", "Distil"), ("1", "Plan"), ("1-B", "Investigate"),
    ("2", "Plan review"), ("2.7", "ADR"), ("3", "Build"), ("4", "Unit tests"), ("4.5", "QA"),
    ("5", "Code + security review"), ("5.5", "Performance"), ("5.8", "Docs"), ("5.85", "Acceptance"),
    ("6", "Ship"),
]
ORDER = dict((key, index) for index, (key, _label) in enumerate(STAGES))
LABEL = dict(STAGES)

AGENT_STAGE = {
    "requirements-writer": "R",
    "requirement-analyst": "Q", "gap-analysis-agent": "Q", "story-generation-agent": "Q",
    "distiller": "0.8",
    "planner": "1",
    "investigator": "1-B",
    "ceo-reviewer": "2", "eng-reviewer": "2", "design-reviewer": "2",
    "adr-writer": "2.7",
    "implementer": "3",
    "unit-tester": "4",
    "qa-tester": "4.5",
    "code-reviewer": "5", "security-reviewer": "5",
    "perf-tester": "5.5",
    "doc-writer": "5.8",
    "acceptance-verifier": "5.85",
    "ship-pr": "6",
}

_PIPELINE = ["0.8", "1", "1-B", "2", "2.7", "3", "4", "4.5", "5", "5.5", "5.8", "6"]
FLOW_STAGES = {
    "pipeline-all": ["R", "Q", "0.8", "1", "2", "2.7", "3", "4", "4.5", "5", "5.5", "5.8", "5.85", "6"],
    "pipeline": list(_PIPELINE),
    "pipeline-parallel": list(_PIPELINE),
}


def place_agents(agents):
    """Set .stage/.fix/.other on agents given in start order.

    An implementer that starts after a later stage has begun is a fix round of that stage.
    An agent type outside the table goes to the stage reached at that time, marked other.
    """
    reached = None
    for agent in agents:
        mapped = AGENT_STAGE.get(agent.agent_type)
        agent.fix = False
        agent.other = False
        if mapped is None:
            agent.other = True
            agent.stage = reached
        elif mapped == "3" and reached is not None and ORDER[reached] > ORDER["3"]:
            agent.fix = True
            agent.stage = reached
        else:
            agent.stage = mapped
        if agent.stage is not None and (reached is None or ORDER[agent.stage] > ORDER[reached]):
            reached = agent.stage


def stage_list(flow, agents):
    keys = list(FLOW_STAGES.get(flow, FLOW_STAGES["pipeline-all"]))
    types = set(a.agent_type for a in agents)
    if "1-B" in keys and "investigator" not in types:
        keys.remove("1-B")
    if "1" in keys and "investigator" in types and "planner" not in types:
        keys.remove("1")
    for agent in agents:
        if agent.stage and agent.stage not in keys:
            keys.append(agent.stage)
    keys.sort(key=lambda k: ORDER[k])
    return keys


def build_stages(flow, agents, run_status):
    keys = stage_list(flow, agents)
    default = keys[0] if keys else None
    groups = dict((key, []) for key in keys)
    for agent in agents:
        groups.setdefault(agent.stage or default, []).append(agent)
    with_agents = [key for key in keys if groups.get(key)]
    latest = with_agents[-1] if with_agents else None
    out = []
    for key in keys:
        members = groups.get(key, [])
        running = any(a.status == "running" for a in members)
        if members and (running or (key == latest and run_status == "running")):
            state = "in progress"
        elif members:
            state = "done"
        elif any(ORDER[other] > ORDER[key] for other in with_agents):
            state = "skipped"
        else:
            state = "not reached"
        out.append({"key": key, "label": LABEL[key], "state": state, "agents": [a.agent_id for a in members]})
    return out
```

`scripts/pipeline_ui/status.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_stages.py`
Expected: `OK` (12 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_ui/stages.py scripts/pipeline_ui/status.py tests/pipeline-ui/test_stages.py
git commit -m "feat: pipeline-ui stage mapping and run status" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Git and artifacts

**Files:**
- Create: `scripts/pipeline_ui/gitinfo.py`
- Create: `scripts/pipeline_ui/artifacts.py`
- Modify: `tests/pipeline-ui/fixture_builder.py` (append `git`, `write_file`, `make_git_repo`)
- Test: `tests/pipeline-ui/test_git_artifacts.py`

**Interfaces:**
- Consumes: `entries.tool_uses` (Task 1); `fixture_builder.Transcript`, `parsed`.
- Produces:
  - `gitinfo.SHA_RE`, `gitinfo.git(repo, *args, timeout=15) -> str | None`, `gitinfo.base_branch(repo) -> "main" | "master" | None`, `gitinfo.branch_commits(repo, branch, base) -> [{"sha","time","subject"}]` (oldest first), `gitinfo.task_of(subject, numbers) -> int | None`, `gitinfo.commit_diff(repo, sha) -> str | None`.
  - `artifacts.slug_of(branch) -> str | None`, `artifacts.plan_tasks(repo, slug) -> [{"number","id","name","path"}]`, `artifacts.bug_plans(repo, slug) -> [abs path]`, `artifacts.ba_paths(repo, window) -> (requirements_abs, artifact_root_abs)`, `artifacts.inside(repo, path) -> bool`, `artifacts.artifact_list(repo, slug, window) -> [{"key","label","path","kind"}]`, `artifacts.resolve(repo, items, key) -> (abs_path, kind) | None`.
  - `fixture_builder.make_git_repo(path) -> path`: `master` (README, `docs/bugs/rounding-mini-plan.md`), `feature/calculate-emi` (checked out; plan with tasks 01–03; commits `docs: plan for calculate-emi`, `feat: task 01 scaffolding`, `feat(Task-02): validation`, `feat: implement task 3 calculation`, `docs: requirements and BA output`), and `fix/rounding` (one commit `fix: rounding`).

- [ ] **Step 1: Append the git repo builder to `fixture_builder.py`**

Add at the end of `tests/pipeline-ui/fixture_builder.py`:

```python
import subprocess  # noqa: E402

GIT_IDENTITY = ["-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false"]


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo] + GIT_IDENTITY + list(args), capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace")))
    return proc.stdout.decode("utf-8", "replace").strip()


def write_file(repo, relative, text, append=False):
    path = os.path.join(repo, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a" if append else "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def make_git_repo(path):
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q")
    git(path, "config", "core.autocrlf", "false")  # keep fixture files byte-exact on Windows
    git(path, "symbolic-ref", "HEAD", "refs/heads/master")
    write_file(path, "README.md", "demo\n")
    write_file(path, "docs/bugs/rounding-mini-plan.md", "# Rounding bug\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "chore: start")
    git(path, "checkout", "-q", "-b", "feature/calculate-emi")
    write_file(path, "docs/plans/calculate-emi/00-overview.md", "# Plan\n")
    write_file(path, "docs/plans/calculate-emi/task-01-scaffolding.md", "# Task 01\n")
    write_file(path, "docs/plans/calculate-emi/task-02-validation.md", "# Task 02\n")
    write_file(path, "docs/plans/calculate-emi/task-03-calculation.md", "# Task 03\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "docs: plan for calculate-emi")
    for subject, line in (("feat: task 01 scaffolding", "x = 1\n"), ("feat(Task-02): validation", "y = 2\n"),
                          ("feat: implement task 3 calculation", "z = 3\n")):
        write_file(path, "emi.py", line, append=True)
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", subject)
    write_file(path, "docs/features/calculate-emi.requirements.md", "# Requirements\n")
    write_file(path, "docs/features/ba/calculate-emi/stories/detailed_stories.md", "# Stories\n")
    write_file(path, "docs/features/ba/calculate-emi/acceptance/acceptance-report.md", "# Acceptance\n")
    write_file(path, "docs/features/ba/calculate-emi/reports/phase3.html", "<!doctype html><title>r</title>\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "docs: requirements and BA output")
    git(path, "checkout", "-q", "-b", "fix/rounding", "master")
    write_file(path, "README.md", "fixed\n", append=True)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fix: rounding")
    git(path, "checkout", "-q", "feature/calculate-emi")
    return path
```

- [ ] **Step 2: Write the failing tests**

`tests/pipeline-ui/test_git_artifacts.py`:

```python
"""Tests for pipeline_ui.gitinfo and pipeline_ui.artifacts."""
import os
import shutil
import tempfile
import unittest

import fixture_builder as fb
from pipeline_ui import artifacts, gitinfo

BRANCH = "feature/calculate-emi"


class GitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_base_branch(self):
        self.assertEqual(gitinfo.base_branch(self.repo), "master")

    def test_commits_and_task_matching(self):
        commits = gitinfo.branch_commits(self.repo, BRANCH, "master")
        subjects = [c["subject"] for c in commits]
        self.assertEqual(subjects, ["docs: plan for calculate-emi", "feat: task 01 scaffolding",
                                    "feat(Task-02): validation", "feat: implement task 3 calculation",
                                    "docs: requirements and BA output"])
        self.assertEqual([gitinfo.task_of(s, [1, 2, 3]) for s in subjects], [None, 1, 2, 3, None])
        self.assertTrue(all(gitinfo.SHA_RE.match(c["sha"]) for c in commits))

    def test_task_10_is_not_task_1(self):
        self.assertEqual(gitinfo.task_of("feat: task 10 done", [1, 10]), 10)
        self.assertIsNone(gitinfo.task_of("feat: task 10 done", [1]))

    def test_diff_needs_a_full_sha(self):
        commits = gitinfo.branch_commits(self.repo, BRANCH, "master")
        self.assertIsNone(gitinfo.commit_diff(self.repo, "HEAD"))
        self.assertIn("emi.py", gitinfo.commit_diff(self.repo, commits[1]["sha"]))

    def test_option_like_branch_rejected(self):
        self.assertEqual(gitinfo.branch_commits(self.repo, "--all", "master"), [])

    def test_not_a_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain, exist_ok=True)
        self.assertIsNone(gitinfo.base_branch(plain))
        self.assertEqual(gitinfo.branch_commits(plain, BRANCH, "master"), [])


class ArtifactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def window(self, args):
        t = fb.Transcript()
        t.tool_use(5, "Skill", {"skill": "sdlc-pipeline:ba-run", "args": args}, "tu-ba")
        return fb.parsed(t)

    def test_slug(self):
        self.assertEqual(artifacts.slug_of(BRANCH), "calculate-emi")
        self.assertIsNone(artifacts.slug_of("master"))
        self.assertIsNone(artifacts.slug_of("feature/../x"))

    def test_plan_tasks(self):
        tasks = artifacts.plan_tasks(self.repo, "calculate-emi")
        self.assertEqual([(t["number"], t["id"], t["name"]) for t in tasks],
                         [(1, "01", "scaffolding"), (2, "02", "validation"), (3, "03", "calculation")])
        self.assertEqual(tasks[0]["path"], "docs/plans/calculate-emi/task-01-scaffolding.md")

    def test_artifact_list_derives_the_ba_folder(self):
        items = artifacts.artifact_list(self.repo, "calculate-emi",
                                        self.window("--requirements docs/features/calculate-emi.requirements.md"))
        self.assertEqual([i["key"] for i in items], ["plan-overview", "task-01", "task-02", "task-03",
                                                     "requirements", "stories", "acceptance", "html-1"])
        self.assertEqual(items[-1]["kind"], "html")

    def test_quoted_absolute_artifact_root(self):
        root = os.path.join(self.repo, "docs", "features", "ba", "calculate-emi")
        args = '--requirements "docs/features/calculate-emi.requirements.md" --artifact-root "%s"' % root
        keys = [i["key"] for i in artifacts.artifact_list(self.repo, None, self.window(args))]
        self.assertEqual(keys, ["requirements", "stories", "acceptance", "html-1"])

    def test_bug_plans(self):
        self.assertEqual([os.path.basename(p) for p in artifacts.bug_plans(self.repo, "rounding")],
                         ["rounding-mini-plan.md"])
        keys = [i["key"] for i in artifacts.artifact_list(self.repo, "rounding", [])]
        self.assertEqual(keys, ["bug-1"])

    def test_inside_and_resolve(self):
        self.assertTrue(artifacts.inside(self.repo, os.path.join(self.repo, "README.md")))
        self.assertFalse(artifacts.inside(self.repo, os.path.join(self.repo, "..", "x")))
        items = artifacts.artifact_list(self.repo, "calculate-emi", [])
        path, kind = artifacts.resolve(self.repo, items, "plan-overview")
        self.assertTrue(path.endswith("00-overview.md"))
        self.assertEqual(kind, "md")
        self.assertIsNone(artifacts.resolve(self.repo, items, "../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_git_artifacts.py`
Expected: ERROR — `ImportError: cannot import name 'artifacts' from 'pipeline_ui'`.

- [ ] **Step 4: Implement `gitinfo.py` and `artifacts.py`**

`scripts/pipeline_ui/gitinfo.py`:

```python
"""Read-only git queries. Every call uses an argument list, never a shell."""
import re
import subprocess

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIFF_LIMIT = 1000000


def git(repo, *args, **kwargs):
    timeout = kwargs.get("timeout", 15)
    try:
        proc = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace")


def base_branch(repo):
    """'main' if it exists, else 'master', else None (also None when this is not a git repo)."""
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + name) is not None:
            return name
    return None


def branch_commits(repo, branch, base):
    """Commits on branch since it left base, oldest first."""
    if not branch or not base or branch == base or branch.startswith("-"):
        return []
    merge_base = git(repo, "merge-base", base, branch)
    if merge_base is None:
        return []
    out = git(repo, "log", "--reverse", "--format=%H%x09%aI%x09%s", "%s..%s" % (merge_base.strip(), branch))
    if out is None:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and SHA_RE.match(parts[0]):
            commits.append({"sha": parts[0], "time": parts[1], "subject": parts[2]})
    return commits


def task_of(subject, numbers):
    """The first task number the subject mentions ('task 03', 'Task 3', 'task-03'), else None."""
    for number in numbers:
        if re.search(r"\btask[ -]?0*%d\b" % number, subject, re.I):
            return number
    return None


def commit_diff(repo, sha):
    if not isinstance(sha, str) or not SHA_RE.match(sha):
        return None
    out = git(repo, "show", "--stat", "--patch", "--no-color", "--no-ext-diff", sha, timeout=30)
    if out is None:
        return None
    if len(out) > DIFF_LIMIT:
        return out[:DIFF_LIMIT] + "\n\n[truncated at 1 MB]\n"
    return out
```

`scripts/pipeline_ui/artifacts.py`:

```python
"""Plan, requirements and report files a run produced. Only known files inside the repo."""
import glob
import os
import re

from .entries import tool_uses

_VALUE = r"(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
REQ_RE = re.compile(r"--requirements\s+" + _VALUE)
ROOT_RE = re.compile(r"--artifact-root\s+" + _VALUE)
TASK_RE = re.compile(r"^task-(\d+)-(.+)\.md$")


def slug_of(branch):
    """'feature/calculate-emi' -> 'calculate-emi'; None for a branch without '/' or a bad slug."""
    if not branch or "/" not in branch:
        return None
    slug = branch.split("/", 1)[1]
    if not slug or ".." in slug or slug.startswith(("/", "\\")):
        return None
    return slug


def _rel(repo, path):
    return os.path.relpath(path, repo).replace("\\", "/")


def plan_tasks(repo, slug):
    if not slug:
        return []
    folder = os.path.join(repo, "docs", "plans", slug)
    tasks = []
    for path in sorted(glob.glob(os.path.join(glob.escape(folder), "task-*.md"))):
        match = TASK_RE.match(os.path.basename(path))
        if match:
            tasks.append({"number": int(match.group(1)), "id": match.group(1),
                          "name": match.group(2).replace("-", " "), "path": _rel(repo, path)})
    return tasks


def bug_plans(repo, slug):
    if not slug:
        return []
    return sorted(glob.glob(os.path.join(glob.escape(os.path.join(repo, "docs", "bugs")),
                                         glob.escape(slug) + "*.md")))


def _arg(regex, text):
    match = regex.search(text)
    if not match:
        return None
    return next((group for group in match.groups() if group), None)


def ba_paths(repo, window):
    """(requirements, artifact root) as absolute paths, from the run's first ba-run Skill call."""
    for entry in window:
        for _tool_use_id, name, tool_input in tool_uses(entry):
            if name != "Skill" or tool_input.get("skill") != "sdlc-pipeline:ba-run":
                continue
            args = tool_input.get("args") if isinstance(tool_input.get("args"), str) else ""
            requirements = _arg(REQ_RE, args)
            root = _arg(ROOT_RE, args)
            if requirements and not os.path.isabs(requirements):
                requirements = os.path.join(repo, requirements)
            if root and not os.path.isabs(root):
                root = os.path.join(repo, root)
            if requirements and not root:
                stem = os.path.basename(requirements)
                if stem.endswith(".md"):
                    stem = stem[:-len(".md")]
                if stem.endswith(".requirements"):
                    stem = stem[:-len(".requirements")]
                root = os.path.join(os.path.dirname(requirements), "ba", stem)
            return requirements, root
    return None, None


def inside(repo, path):
    try:
        real_repo = os.path.normcase(os.path.realpath(repo))
        real_path = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([real_repo, real_path]) == real_repo
    except ValueError:  # different drives on Windows
        return False


def artifact_list(repo, slug, window):
    items = []

    def add(key, label, path):
        if path and os.path.isfile(path) and inside(repo, path):
            items.append({"key": key, "label": label, "path": _rel(repo, path),
                          "kind": os.path.splitext(path)[1].lower().lstrip(".")})

    if slug:
        add("plan-overview", "Plan overview", os.path.join(repo, "docs", "plans", slug, "00-overview.md"))
        for task in plan_tasks(repo, slug):
            add("task-" + task["id"], "Task " + task["id"], os.path.join(repo, task["path"]))
        for number, path in enumerate(bug_plans(repo, slug), 1):
            add("bug-%d" % number, "Bug plan", path)
    requirements, root = ba_paths(repo, window)
    add("requirements", "Requirements", requirements)
    if root:
        add("stories", "Detailed stories", os.path.join(root, "stories", "detailed_stories.md"))
        add("acceptance", "Acceptance report", os.path.join(root, "acceptance", "acceptance-report.md"))
        pattern = os.path.join(glob.escape(root), "**", "*.html")
        for number, path in enumerate(sorted(glob.glob(pattern, recursive=True)), 1):
            add("html-%d" % number, os.path.basename(path), path)
    return items


def resolve(repo, items, key):
    """(absolute path, kind) for an artifact key from items, else None."""
    for item in items:
        if item["key"] == key:
            path = os.path.join(repo, *item["path"].split("/"))
            if os.path.isfile(path) and inside(repo, path):
                return path, item["kind"]
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_git_artifacts.py`
Expected: `OK` (12 tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_ui/gitinfo.py scripts/pipeline_ui/artifacts.py tests/pipeline-ui/fixture_builder.py tests/pipeline-ui/test_git_artifacts.py
git commit -m "feat: pipeline-ui git commits, diffs and run artifacts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dashboard assembly

**Files:**
- Create: `scripts/pipeline_ui/dashboard.py`
- Modify: `tests/pipeline-ui/fixture_builder.py` (append `emi_like`)
- Test: `tests/pipeline-ui/test_dashboard.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces:
  - `dashboard.Dashboard(repo, cfg=None, prices=None, clock=time.time)` with `.repo` (absolute path), `.lock`, and
    `runs() -> {"project", "folders", "runs": [summary]}`;
    `run(run_id) -> detail | None`;
    `diff(run_id, sha) -> str | None`;
    `file(run_id, key) -> (abs_path, kind) | None`.
  - Summary keys: `id, session, command, flow, title, branch, started, status, waiting_since, duration_s, tokens{input,output,cache_write,cache_read,total}, cost, cost_complete, linked, resumed_from` (+ `errors` when a run could not be built).
  - Detail = summary + `stages, agents, checkpoints, tasks{slug,tasks[{number,id,name,path,commits}],other_commits,bug_plans,git}, artifacts, warnings` (+ `errors{section: message}`).
  - Agent row keys: `id, parent, type, description, model, stage, stage_label, fix, other, started, duration_s, status, tokens, cost, cost_complete`; the last row is `id: "orchestrator"`.
  - `fixture_builder.emi_like(cfg, repo, mtime=None) -> {"session", "run1", "run2"}`.

- [ ] **Step 1: Append the EMI-shaped fixture to `fixture_builder.py`**

Add at the end of `tests/pipeline-ui/fixture_builder.py`:

```python
def emi_like(cfg, repo, mtime=None):
    """Two runs in one session, shaped like the 2026-10-29 EMI run.

    Run 1: /pipeline-ui -> pipeline-all, an agent for every stage it reaches, a fix round after the
    acceptance verifier, an unknown agent without meta, a nested agent, a notification-only finish,
    two questions (one answered in chat), a duplicated response, one invalid line. Shipped.
    Run 2: /pipeline on master, one pending question.
    Every file gets mtime = ts(45) unless given.
    """
    mtime = parse_ts(ts(45)) if mtime is None else mtime
    s = Transcript(session_id="sess-emi", cwd=repo, branch="master")
    s.command(0, "pipeline-ui", "Add calculate_emi(principal, annual_rate, months)\nRound half up.")
    run1_line = len(s.lines)
    s.tool_use(1, "Skill", {"skill": "sdlc-pipeline:pipeline-all", "args": "Add calculate_emi"}, "tu-skill")
    s.tool_result(1, "tu-skill", "Launching skill: sdlc-pipeline:pipeline-all")
    dispatched = []

    def dispatch(minute, agent_id, agent_type, description, tool_use_id):
        s.tool_use(minute, "Agent", {"subagent_type": "sdlc-pipeline:" + agent_type, "description": description},
                   tool_use_id)
        s.tool_result(minute, tool_use_id, "Async agent launched successfully.\nagentId: %s" % agent_id)
        dispatched.append((agent_id, agent_type, description, tool_use_id, minute))

    dispatch(2, "a-rw", "requirements-writer", "Draft EMI requirements", "tu-rw")
    s.tool_use(4, "AskUserQuestion", {"questions": [{"header": "Requirements", "question": "Approve the requirements?",
                                                     "options": [{"label": "Approve"}, {"label": "Change"}]}]}, "tu-q1")
    s.tool_result(4, "tu-q1", 'User has answered your questions: "Approve the requirements?"="Approve". '
                              "You can now continue.", second=30)
    s.tool_use(5, "Skill", {"skill": "sdlc-pipeline:ba-run",
                            "args": "--requirements docs/features/calculate-emi.requirements.md"}, "tu-ba")
    s.tool_result(5, "tu-ba", "Launching skill: sdlc-pipeline:ba-run")
    dispatch(6, "a-ra", "requirement-analyst", "Decompose atomic requirements", "tu-ra")
    dispatch(8, "a-pl", "planner", "Plan EMI feature", "tu-pl")
    dispatch(10, "a-ceo", "ceo-reviewer", "CEO plan review", "tu-ceo")
    dispatch(10, "a-eng", "eng-reviewer", "Eng plan review", "tu-eng")
    s.tool_use(12, "AskUserQuestion", {"questions": [{"header": "Plan", "question": "Approve the plan?",
                                                      "options": [{"label": "Approve"}]}]}, "tu-q2")
    s.tool_result(12, "tu-q2", "Tool result missing due to internal error", is_error=True)
    s.user(12, "<task-notification>\n<task-id>a-eng</task-id>\n<status>completed</status>\n</task-notification>",
           second=40, origin={"kind": "task-notification"})
    s.user(13, "<system-reminder>context</system-reminder>Approve it")
    s.branch = "feature/calculate-emi"
    dispatch(14, "a-i1", "implementer", "Implement task 01 scaffolding", "tu-i1")
    dispatch(16, "a-i2", "implementer", "Implement task 02 validation", "tu-i2")
    dispatch(18, "a-cr", "code-reviewer", "Code review of branch", "tu-cr")
    dispatch(18, "a-sr", "security-reviewer", "Security review of branch", "tu-sr")
    dispatch(20, "a-av", "acceptance-verifier", "Verify acceptance criteria", "tu-av")
    dispatch(22, "a-fix", "implementer", "Fix US-003.2", "tu-fix")
    dispatch(24, "a-oth", "general-purpose", "Look something up", "tu-oth")
    dispatch(26, "a-ship", "ship-pr", "Ship the PR", "tu-ship")
    s.text(28, "Shipped.", message_id="msg-dup", usage=tokens(1000, 0))
    s.text(28, "Shipped.", message_id="msg-dup", usage=tokens(1000, 0))
    s.raw("{not json")
    s.raw(json.dumps({"type": "queue-operation", "operation": "enqueue", "version": "2.1.312"}))
    s.branch = "master"
    s.command(40, "pipeline", "Fix rounding")
    run2_line = len(s.lines)
    s.tool_use(41, "AskUserQuestion", {"questions": [{"header": "Type", "question": "Feature or bug?",
                                                      "options": [{"label": "Bug"}]}]}, "tu-q3")
    write_session(cfg, repo, s, mtime=mtime)

    for agent_id, agent_type, description, tool_use_id, minute in dispatched:
        if agent_id == "a-eng":  # finished only by the main session's task notification
            t = Transcript(session_id=s.session_id, cwd=repo, sidechain=True, agent_id=agent_id)
            t.user(minute + 1, "Review the plan.")
            t.tool_use(minute + 1, "Read", {"file_path": "plan.md"}, "tu-a-eng-1", model="claude-haiku-5-5")
            t.tool_result(minute + 1, "tu-a-eng-1", "ok")
        else:
            t = finished_agent(agent_id, minute + 1, session_id=s.session_id, cwd=repo,
                               usage=tokens(100, 50, cache_read=1000, write_5m=200) if agent_id == "a-pl" else None,
                               synthetic=agent_id == "a-ra", spawn="tu-nested" if agent_id == "a-pl" else None)
        write_agent(cfg, repo, s.session_id, t, "sdlc-pipeline:" + agent_type, description, tool_use_id,
                    meta=agent_id != "a-oth", mtime=mtime)
    nested = finished_agent("a-nest", 10, session_id=s.session_id, cwd=repo)
    write_agent(cfg, repo, s.session_id, nested, "Explore", "Find the formula", "tu-nested", spawn_depth=2,
                mtime=mtime)
    return {"session": s.session_id, "run1": "sess-emi:%d" % run1_line, "run2": "sess-emi:%d" % run2_line}
```

- [ ] **Step 2: Write the failing tests**

`tests/pipeline-ui/test_dashboard.py`:

```python
"""Tests for pipeline_ui.dashboard against the EMI-shaped fixture."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fixture_builder as fb
from pipeline_ui import gitinfo, usage
from pipeline_ui.dashboard import Dashboard
from pipeline_ui.timeutil import parse_ts


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.cfg = os.path.join(cls.tmp, "cfg")
        cls.ids = fb.emi_like(cls.cfg, cls.repo)
        now = parse_ts(fb.ts(50))
        cls.dash = Dashboard(cls.repo, cfg=cls.cfg, prices=usage.load_prices(), clock=lambda: now)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_run_list(self):
        data = self.dash.runs()
        self.assertEqual(data["project"], os.path.abspath(self.repo))
        self.assertEqual(data["folders"], [fb.project_folder(self.cfg, self.repo)])
        run2, run1 = data["runs"]
        self.assertEqual((run1["id"], run1["command"], run1["flow"], run1["title"], run1["branch"], run1["status"]),
                         (self.ids["run1"], "pipeline-ui", "pipeline-all",
                          "Add calculate_emi(principal, annual_rate, months)", "feature/calculate-emi", "finished"))
        self.assertEqual((run2["id"], run2["flow"], run2["status"], run2["waiting_since"]),
                         (self.ids["run2"], "pipeline", "waiting", parse_ts(fb.ts(41))))
        self.assertGreater(run1["cost"], 0)
        self.assertFalse(run1["cost_complete"])  # the '<synthetic>' entry has no price
        self.assertEqual(run1["duration_s"], 28 * 60)

    def test_stages(self):
        d = self.dash.run(self.ids["run1"])
        states = dict((s["key"], s["state"]) for s in d["stages"])
        self.assertEqual(states, {"R": "done", "Q": "done", "0.8": "skipped", "1": "done", "2": "done",
                                  "2.7": "skipped", "3": "done", "4": "skipped", "4.5": "skipped", "5": "done",
                                  "5.5": "skipped", "5.8": "skipped", "5.85": "done", "6": "done"})

    def test_agents(self):
        rows = dict((r["id"], r) for r in self.dash.run(self.ids["run1"])["agents"])
        self.assertEqual(len(rows), 15)  # 13 dispatched + nested + orchestrator
        self.assertEqual((rows["a-fix"]["stage"], rows["a-fix"]["fix"]), ("5.85", True))
        self.assertEqual((rows["a-oth"]["type"], rows["a-oth"]["other"]), ("unknown", True))
        self.assertEqual((rows["a-nest"]["parent"], rows["a-nest"]["stage"]), ("a-pl", "1"))
        self.assertEqual(rows["a-eng"]["status"], "finished")
        self.assertEqual(rows["a-pl"]["tokens"]["cache_read"], 1000)
        orchestrator = rows["orchestrator"]
        self.assertTrue(1000 <= orchestrator["tokens"]["input"] < 2000)  # duplicated response counted once
        self.assertEqual(orchestrator["stage_label"], "All stages")

    def test_checkpoints(self):
        cps = self.dash.run(self.ids["run1"])["checkpoints"]
        self.assertEqual([(c["answer"], c["answered_in_chat"]) for c in cps],
                         [("Approve", False), ("Approve it", True)])
        self.assertTrue(self.dash.run(self.ids["run2"])["checkpoints"][0]["pending"])

    def test_tasks_and_commits(self):
        tasks = self.dash.run(self.ids["run1"])["tasks"]
        self.assertTrue(tasks["git"])
        self.assertEqual([(t["id"], [c["subject"] for c in t["commits"]]) for t in tasks["tasks"]],
                         [("01", ["feat: task 01 scaffolding"]), ("02", ["feat(Task-02): validation"]),
                          ("03", ["feat: implement task 3 calculation"])])
        self.assertEqual([c["subject"] for c in tasks["other_commits"]],
                         ["docs: plan for calculate-emi", "docs: requirements and BA output"])
        self.assertEqual(self.dash.run(self.ids["run2"])["tasks"]["tasks"], [])

    def test_artifacts_and_warnings(self):
        d = self.dash.run(self.ids["run1"])
        self.assertEqual([a["key"] for a in d["artifacts"]],
                         ["plan-overview", "task-01", "task-02", "task-03", "requirements", "stories",
                          "acceptance", "html-1"])
        self.assertEqual(d["warnings"], ["1 line could not be read \u00b7 Claude Code 2.1.312"])

    def test_diff_only_for_the_runs_commits(self):
        good = gitinfo.branch_commits(self.repo, "feature/calculate-emi", "master")[1]["sha"]
        other = fb.git(self.repo, "rev-parse", "fix/rounding")
        self.assertIn("emi.py", self.dash.diff(self.ids["run1"], good))
        self.assertIsNone(self.dash.diff(self.ids["run1"], other))
        self.assertIsNone(self.dash.diff("no-such-run", good))

    def test_file_only_for_known_keys(self):
        path, kind = self.dash.file(self.ids["run1"], "acceptance")
        self.assertTrue(path.endswith("acceptance-report.md"))
        self.assertEqual(kind, "md")
        self.assertIsNone(self.dash.file(self.ids["run1"], "../README.md"))
        self.assertIsNone(self.dash.run("no-such-run"))

    def test_a_failing_section_does_not_break_the_page(self):
        with mock.patch("pipeline_ui.artifacts.artifact_list", side_effect=RuntimeError("boom")):
            d = self.dash.run(self.ids["run1"])
        self.assertIsNone(d["artifacts"])
        self.assertEqual(d["errors"], {"artifacts": "RuntimeError: boom"})
        self.assertTrue(d["stages"])

    def test_empty_project(self):
        other = os.path.join(self.tmp, "empty")
        os.makedirs(other, exist_ok=True)
        data = Dashboard(other, cfg=os.path.join(self.tmp, "nocfg")).runs()
        self.assertEqual(data, {"project": os.path.abspath(other), "folders": [], "runs": []})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_dashboard.py`
Expected: ERROR — `ModuleNotFoundError: No module named 'pipeline_ui.dashboard'`.

- [ ] **Step 4: Implement `dashboard.py`**

`scripts/pipeline_ui/dashboard.py`:

```python
"""Builds the dashboard's JSON from transcripts, git and plan files. Read-only."""
import os
import threading
import time

from . import agents as agents_mod
from . import artifacts, checkpoints, gitinfo, stages, transcripts
from . import runs as runs_mod
from . import status as status_mod
from . import usage as usage_mod
from .timeutil import parse_ts

GIT_TTL_S = 5.0


def _span(first, last):
    start, end = parse_ts(first), parse_ts(last)
    return (end - start) if start is not None and end is not None else None


def _error(exc):
    return "%s: %s" % (type(exc).__name__, exc)


class Dashboard(object):
    def __init__(self, repo, cfg=None, prices=None, clock=time.time):
        self.repo = os.path.abspath(repo)
        self.cfg = cfg or transcripts.config_dir()
        self.prices = usage_mod.load_prices() if prices is None else prices
        self.clock = clock
        self.cache = transcripts.FileCache()
        self.lock = threading.Lock()
        self._folders = None
        self._ttl = {}

    # ---- public API: each call holds the lock ----
    def runs(self):
        with self.lock:
            items = self._collect()
            return {"project": self.repo, "folders": list(self._folders or []),
                    "runs": [item["summary"] for item in items]}

    def run(self, run_id):
        with self.lock:
            item = self._find(run_id)
            return self._detail(item) if item else None

    def diff(self, run_id, sha):
        with self.lock:
            item = self._find(run_id)
            if not item:
                return None
            if sha not in set(c["sha"] for c in (self._commits(item["run"].branch) or [])):
                return None
            return gitinfo.commit_diff(self.repo, sha)

    def file(self, run_id, key):
        with self.lock:
            item = self._find(run_id)
            if not item:
                return None
            run = item["run"]
            items = artifacts.artifact_list(self.repo, artifacts.slug_of(run.branch), run.entries)
            return artifacts.resolve(self.repo, items, key)

    # ---- collection ----
    def folders(self):
        if not self._folders:  # an empty result is retried on the next request
            self._folders = transcripts.transcript_folders(self.repo, self.cfg)
        return self._folders

    def _collect(self):
        now = self.clock()
        items = []
        for folder in self.folders():
            for session_id, path in transcripts.list_sessions(folder):
                main = self.cache.get(path)
                found = runs_mod.find_runs(session_id, main.entries)
                if not found:
                    continue
                loaded = self._load_agents(folder, session_id, agents_mod.notified_ids(main.entries), now)
                by_run = agents_mod.assign_agents(found, loaded)
                for run in found:
                    items.append(self._build(run, by_run.get(run.run_id, []), main, now))
        self._link(items)
        items.sort(key=lambda item: item["summary"]["started"] or "", reverse=True)
        return items

    def _find(self, run_id):
        for item in self._collect():
            if item["summary"]["id"] == run_id:
                return item
        return None

    def _load_agents(self, folder, session_id, notified, now):
        loaded = []
        for agent_id, path, meta_path in transcripts.subagent_files(folder, session_id):
            jsonl = self.cache.get(path)
            agent = agents_mod.Agent(agent_id, transcripts.read_meta(meta_path), jsonl.entries, jsonl.mtime, path=path)
            agent.status = agents_mod.agent_state(jsonl.entries, jsonl.mtime, now, notified=agent_id in notified)
            loaded.append(agent)
        return loaded

    def _build(self, run, run_agents, main, now):
        item = {"run": run, "agents": run_agents, "main": main, "checkpoints": [], "orchestrator": {}}
        summary = {"id": run.run_id, "session": run.session_id, "command": run.command, "flow": run.flow,
                   "title": run.title, "branch": run.branch, "started": run.started_at, "status": "error",
                   "waiting_since": None, "duration_s": None, "tokens": usage_mod.Usage().to_dict(),
                   "cost": None, "cost_complete": False, "linked": [], "resumed_from": None}
        try:
            stages.place_agents(run_agents)
            item["checkpoints"] = checkpoints.find_checkpoints(run.entries)
            state, since = status_mod.run_status(run, run_agents, item["checkpoints"], main.mtime, now)
            item["orchestrator"] = usage_mod.usage_by_model(run.entries)
            combined = usage_mod.merge([item["orchestrator"]] + [a.usage_by_model for a in run_agents])
            cost, complete = usage_mod.estimate_cost(combined, self.prices)
            stamps = [run.entries[-1].get("timestamp")] + [a.last_ts for a in run_agents]
            last = max((s for s in stamps if isinstance(s, str)), default=None)
            summary.update({"status": state, "waiting_since": since, "duration_s": _span(run.started_at, last),
                            "tokens": usage_mod.total(combined).to_dict(), "cost": cost,
                            "cost_complete": complete})
        except Exception as exc:  # one unreadable run must not hide the others
            summary["errors"] = {"run": _error(exc)}
        item["summary"] = summary
        return item

    def _link(self, items):
        groups = {}
        for item in items:
            branch = item["summary"]["branch"]
            if branch and branch not in runs_mod.BASE_BRANCHES:
                groups.setdefault(branch, []).append(item["summary"])
        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda s: s["started"] or "")
            ids = [s["id"] for s in group]
            for index, summary in enumerate(group):
                summary["linked"] = [other for other in ids if other != summary["id"]]
                summary["resumed_from"] = ids[index - 1] if index else None

    # ---- detail ----
    def _detail(self, item):
        out = dict(item["summary"])
        errors = dict(out.get("errors") or {})
        run = item["run"]

        def section(name, build):
            try:
                out[name] = build()
            except Exception as exc:  # each part fails on its own
                out[name] = None
                errors[name] = _error(exc)

        section("stages", lambda: stages.build_stages(run.flow, item["agents"], out["status"]))
        section("agents", lambda: self._agent_rows(item))
        section("checkpoints", lambda: item["checkpoints"])
        section("tasks", lambda: self._tasks(run.branch))
        section("artifacts", lambda: [dict(a) for a in artifacts.artifact_list(
            self.repo, artifacts.slug_of(run.branch), run.entries)])
        section("warnings", lambda: self._warnings(item))
        if errors:
            out["errors"] = errors
        return out

    def _row(self, by_model):
        cost, complete = usage_mod.estimate_cost(by_model, self.prices)
        return {"tokens": usage_mod.total(by_model).to_dict(), "cost": cost, "cost_complete": complete}

    def _agent_rows(self, item):
        rows = []
        for agent in item["agents"]:
            row = {"id": agent.agent_id, "parent": agent.parent_id, "type": agent.agent_type,
                   "description": agent.description, "model": agent.model, "stage": agent.stage,
                   "stage_label": stages.LABEL.get(agent.stage, "Other"), "fix": agent.fix, "other": agent.other,
                   "started": agent.first_ts, "duration_s": _span(agent.first_ts, agent.last_ts),
                   "status": agent.status}
            row.update(self._row(agent.usage_by_model))
            rows.append(row)
        run = item["run"]
        row = {"id": "orchestrator", "parent": None, "type": "orchestrator",
               "description": "Main session (the pipeline itself)", "model": agents_mod.main_model(run.entries),
               "stage": None, "stage_label": "All stages", "fix": False, "other": False,
               "started": run.started_at, "duration_s": _span(run.started_at, run.entries[-1].get("timestamp")),
               "status": item["summary"]["status"]}
        row.update(self._row(item["orchestrator"]))
        rows.append(row)
        return rows

    def _cached(self, key, build):
        now = time.monotonic()
        hit = self._ttl.get(key)
        if hit and now - hit[0] < GIT_TTL_S:
            return hit[1]
        value = build()
        self._ttl[key] = (now, value)
        return value

    def _commits(self, branch):
        """Commits on the run's branch since it left the base branch; None when git is unavailable."""
        def build():
            base = gitinfo.base_branch(self.repo)
            return None if base is None else gitinfo.branch_commits(self.repo, branch, base)
        return self._cached(("commits", branch), build)

    def _tasks(self, branch):
        slug = artifacts.slug_of(branch)
        plan = self._cached(("tasks", slug), lambda: artifacts.plan_tasks(self.repo, slug))
        tasks = [dict(task, commits=[]) for task in plan]
        commits = self._commits(branch)
        by_number = dict((task["number"], task) for task in tasks)
        other = []
        for commit in commits or []:
            number = gitinfo.task_of(commit["subject"], list(by_number))
            (by_number[number]["commits"] if number is not None else other).append(commit)
        bugs = [] if tasks else [os.path.relpath(p, self.repo).replace("\\", "/")
                                 for p in artifacts.bug_plans(self.repo, slug)]
        return {"slug": slug, "tasks": tasks, "other_commits": other, "bug_plans": bugs, "git": commits is not None}

    def _warnings(self, item):
        files = [item["main"]] + [self.cache.get(a.path) for a in item["agents"] if a.path]
        bad = sum(f.bad_lines for f in files)
        if not bad:
            return []
        versions = sorted(set().union(*[f.versions for f in files]))
        return ["%d line%s could not be read \u00b7 Claude Code %s"
                % (bad, "" if bad == 1 else "s", ", ".join(versions) or "version unknown")]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_dashboard.py`
Expected: `OK` (10 tests).

- [ ] **Step 6: Run the whole pipeline-ui suite**

Run: `python -I -m unittest discover -s tests/pipeline-ui`
Expected: `OK` (all tests from Tasks 1–7).

- [ ] **Step 7: Commit**

```bash
git add scripts/pipeline_ui/dashboard.py tests/pipeline-ui/fixture_builder.py tests/pipeline-ui/test_dashboard.py
git commit -m "feat: pipeline-ui dashboard assembly" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Server and CLI

**Files:**
- Create: `scripts/pipeline-ui.py`
- Create: `scripts/pipeline-ui.html` (placeholder page; Task 9 replaces it)
- Test: `tests/pipeline-ui/test_server.py`

**Interfaces:**
- Consumes: `dashboard.Dashboard` (Task 7), `transcripts.config_dir` (Task 1), `fixture_builder.make_git_repo`, `emi_like`.
- Produces (module `scripts/pipeline-ui.py`, loaded in tests with `importlib`):
  - Constants `HOST = "127.0.0.1"`, `FIRST_PORT = 8765`, `PORT_COUNT = 20`, `IDLE_LIMIT_S = 7200`.
  - `free_port() -> int | None`, `state_path(project, cfg=None)`, `read_state`, `write_state`, `remove_state`, `health(port, timeout=1.0) -> dict | None` (no proxy).
  - `Server(port, dashboard)` (`ThreadingHTTPServer` subclass with `.dashboard`, `.last_request`, `.stopping`), `make_server(project, port, cfg=None) -> Server`, `start_idle_watch(server, idle_limit, interval=60.0)`, `serve(project, port, cfg=None, idle_limit=IDLE_LIMIT_S)`.
  - `cmd_start(project, open_browser=False, cfg=None) -> {"url","pid","reused"} | {"error"}`, `cmd_stop(project, cfg=None) -> {"stopped": True} | {"running": False} | {"error"}`, `cmd_status(project, cfg=None) -> {"running": True, "url", "pid"} | {"running": False}`, `main(argv=None) -> int`.
  - HTTP: `GET /`, `/api/health`, `/api/runs`, `/api/runs/<url-encoded id>`, `/api/diff?run=&commit=`, `/api/file?run=&key=`; 403 for a foreign `Host`; `Cache-Control: no-store` on every response.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline-ui/test_server.py`:

```python
"""Tests for scripts/pipeline-ui.py: HTTP API, security rules, idle shutdown and the CLI."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

import fixture_builder as fb
from pipeline_ui import gitinfo

SCRIPT = os.path.join(fb.SCRIPTS, "pipeline-ui.py")
_spec = importlib.util.spec_from_file_location("pipeline_ui_cli", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.cfg = os.path.join(cls.tmp, "cfg")
        cls.ids = fb.emi_like(cls.cfg, cls.repo)
        cls.port = cli.free_port()
        cls.server = cli.make_server(cls.repo, cls.port, cfg=cls.cfg)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, host=None):
        request = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path))
        if host:
            request.add_header("Host", host)
        try:
            with OPENER.open(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def run_path(self, key):
        return urllib.parse.quote(self.ids[key], safe="")

    def test_bound_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_health_and_runs(self):
        code, headers, body = self.get("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["project"], os.path.abspath(self.repo))
        self.assertEqual(headers["Cache-Control"], "no-store")
        code, _headers, body = self.get("/api/runs")
        self.assertEqual([r["id"] for r in json.loads(body)["runs"]], [self.ids["run2"], self.ids["run1"]])

    def test_run_detail_and_unknown_run(self):
        code, _headers, body = self.get("/api/runs/" + self.run_path("run1"))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"], "finished")
        self.assertEqual(self.get("/api/runs/nope")[0], 404)

    def test_page(self):
        code, headers, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn(b"<title>", body)

    def test_diff_only_for_the_runs_commits(self):
        good = gitinfo.branch_commits(self.repo, "feature/calculate-emi", "master")[1]["sha"]
        other = fb.git(self.repo, "rev-parse", "fix/rounding")
        code, _headers, body = self.get("/api/diff?run=%s&commit=%s" % (self.run_path("run1"), good))
        self.assertEqual(code, 200)
        self.assertIn(b"emi.py", body)
        self.assertEqual(self.get("/api/diff?run=%s&commit=%s" % (self.run_path("run1"), other))[0], 404)

    def test_files(self):
        base = "/api/file?run=%s&key=" % self.run_path("run1")
        self.assertEqual(self.get(base + urllib.parse.quote("../../README.md"))[0], 404)
        code, _headers, body = self.get(base + "acceptance")
        self.assertEqual((code, body), (200, b"# Acceptance\n"))
        code, headers, _body = self.get(base + "html-1")
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Security-Policy"], "sandbox allow-scripts")

    def test_foreign_host_refused(self):
        self.assertEqual(self.get("/api/runs", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.get("/api/runs", host="localhost:%d" % self.port)[0], 200)


class IdleTest(unittest.TestCase):
    def test_idle_server_shuts_down(self):
        tmp = tempfile.mkdtemp()
        try:
            server = cli.make_server(tmp, cli.free_port(), cfg=os.path.join(tmp, "cfg"))
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            server.last_request = time.time() - 10
            cli.start_idle_watch(server, idle_limit=1, interval=0.05)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            server.server_close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CliTest(unittest.TestCase):
    def test_start_reuse_status_stop(self):
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(tmp, "cfg"))

        def call(*args):
            proc = subprocess.run([sys.executable, SCRIPT] + list(args) + ["--project", repo],
                                  capture_output=True, text=True, env=env, timeout=30)
            return json.loads(proc.stdout)

        try:
            first = call("start")
            self.assertIn("url", first, first)
            self.assertFalse(first["reused"])
            try:
                second = call("start")
                self.assertTrue(second["reused"])
                self.assertEqual(second["url"], first["url"])
                self.assertTrue(call("status")["running"])
            finally:
                self.assertEqual(call("stop"), {"stopped": True})
            deadline = time.time() + 10
            while time.time() < deadline and cli.health(int(first["url"].rsplit(":", 1)[1].strip("/"))):
                time.sleep(0.2)
            self.assertEqual(call("status"), {"running": False})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_server.py`
Expected: ERROR — `FileNotFoundError` for `scripts/pipeline-ui.py`.

- [ ] **Step 3: Implement the server and a placeholder page**

`scripts/pipeline-ui.html` (placeholder; replaced in Task 9):

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Pipeline runs</title></head>
<body><p>Pipeline dashboard: the page arrives in the next task. The API is at /api/runs.</p></body></html>
```

`scripts/pipeline-ui.py`:

```python
#!/usr/bin/env python3
"""Local, read-only dashboard for sdlc-pipeline runs.

    python pipeline-ui.py start  --project <repo> [--open]   start (or reuse) the server, print its URL
    python pipeline-ui.py serve  --project <repo> --port <n> run the server in the foreground
    python pipeline-ui.py stop   --project <repo>            stop this project's server
    python pipeline-ui.py status --project <repo>            is it running?

Prints one JSON line. Standard library only, Python 3.8+. Listens on 127.0.0.1 only, never writes
to the repository; its only files are a state file and a log under <config dir>/sdlc-pipeline/ui/.
"""
import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pipeline_ui import transcripts  # noqa: E402
from pipeline_ui.dashboard import Dashboard  # noqa: E402

HOST = "127.0.0.1"
FIRST_PORT = 8765
PORT_COUNT = 20
IDLE_LIMIT_S = 2 * 3600
PAGE = os.path.join(HERE, "pipeline-ui.html")
PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
FILE_TYPES = {"md": "text/plain; charset=utf-8", "json": "application/json; charset=utf-8",
              "html": "text/html; charset=utf-8"}
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def plugin_version():
    try:
        with open(os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version", "unknown")
    except (OSError, ValueError):
        return "unknown"


def _ui_dir(cfg=None):
    return os.path.join(cfg or transcripts.config_dir(), "sdlc-pipeline", "ui")


def _digest(project):
    return hashlib.sha1(os.path.normcase(os.path.abspath(project)).encode("utf-8")).hexdigest()[:12]


def state_path(project, cfg=None):
    return os.path.join(_ui_dir(cfg), _digest(project) + ".json")


def log_path(project, cfg=None):
    return os.path.join(_ui_dir(cfg), _digest(project) + ".log")


def read_state(project, cfg=None):
    try:
        with open(state_path(project, cfg), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(project, data, cfg=None):
    path = state_path(project, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def remove_state(project, cfg=None):
    try:
        os.remove(state_path(project, cfg))
    except OSError:
        pass


def health(port, timeout=1.0):
    if not isinstance(port, int) or port <= 0:
        return None
    try:
        with _NO_PROXY.open("http://%s:%d/api/health" % (HOST, port), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _same_project(info, project):
    return (isinstance(info, dict) and isinstance(info.get("project"), str)
            and os.path.normcase(info["project"]) == os.path.normcase(os.path.abspath(project)))


def free_port():
    for port in range(FIRST_PORT, FIRST_PORT + PORT_COUNT):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((HOST, port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    return None


def _url(port):
    return "http://%s:%d/" % (HOST, port)


class Handler(BaseHTTPRequestHandler):
    server_version = "sdlc-pipeline-ui"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code, body, content_type, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload), "application/json; charset=utf-8")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def do_GET(self):
        self.server.touch()
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)

        def one(name):
            return (query.get(name) or [""])[0]

        dash = self.server.dashboard
        try:
            if url.path == "/":
                with open(PAGE, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_CSP})
            elif url.path == "/api/health":
                self._json(200, {"project": dash.repo, "version": plugin_version(), "pid": os.getpid()})
            elif url.path == "/api/runs":
                self._json(200, dash.runs())
            elif url.path.startswith("/api/runs/"):
                detail = dash.run(urllib.parse.unquote(url.path[len("/api/runs/"):]))
                if detail is None:
                    self._json(404, {"error": "unknown run"})
                else:
                    self._json(200, detail)
            elif url.path == "/api/diff":
                text = dash.diff(one("run"), one("commit"))
                if text is None:
                    self._json(404, {"error": "unknown commit for this run"})
                else:
                    self._send(200, text, "text/plain; charset=utf-8")
            elif url.path == "/api/file":
                found = dash.file(one("run"), one("key"))
                if found is None:
                    self._json(404, {"error": "unknown file for this run"})
                else:
                    path, kind = found
                    with open(path, "rb") as fh:
                        data = fh.read()
                    extra = {"Content-Security-Policy": "sandbox allow-scripts"} if kind == "html" else None
                    self._send(200, data, FILE_TYPES.get(kind, "text/plain; charset=utf-8"), extra)
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:  # never leak a traceback to the page
            try:
                self._json(500, {"error": type(exc).__name__})
            except Exception:
                pass


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, dashboard):
        ThreadingHTTPServer.__init__(self, (HOST, port), Handler)
        self.dashboard = dashboard
        self.last_request = time.time()
        self.stopping = threading.Event()

    def touch(self):
        self.last_request = time.time()


def make_server(project, port, cfg=None):
    return Server(port, Dashboard(project, cfg=cfg))


def start_idle_watch(server, idle_limit=IDLE_LIMIT_S, interval=60.0):
    def watch():
        while not server.stopping.wait(interval):
            if time.time() - server.last_request > idle_limit:
                server.stopping.set()
                server.shutdown()
                return

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def serve(project, port, cfg=None, idle_limit=IDLE_LIMIT_S):
    server = make_server(project, port, cfg)
    write_state(project, {"pid": os.getpid(), "port": port, "project": server.dashboard.repo,
                          "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, cfg)
    start_idle_watch(server, idle_limit)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.stopping.set()
        server.server_close()
        state = read_state(project, cfg)
        if state and state.get("pid") == os.getpid():
            remove_state(project, cfg)


def cmd_start(project, open_browser=False, cfg=None):
    project = os.path.abspath(project)
    state = read_state(project, cfg)
    if state:
        info = health(state.get("port"))
        if _same_project(info, project):
            if open_browser:
                webbrowser.open(_url(state["port"]))
            return {"url": _url(state["port"]), "pid": info.get("pid"), "reused": True}
        remove_state(project, cfg)
    port = free_port()
    if port is None:
        return {"error": "no free port in %d-%d" % (FIRST_PORT, FIRST_PORT + PORT_COUNT - 1)}
    os.makedirs(_ui_dir(cfg), exist_ok=True)
    command = [sys.executable, os.path.abspath(__file__), "serve", "--project", project, "--port", str(port)]
    with open(log_path(project, cfg), "ab") as log:
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": log, "close_fds": True}
        if os.name == "nt":
            options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        proc = subprocess.Popen(command, **options)
    deadline = time.time() + 5
    while time.time() < deadline:
        if _same_project(health(port, timeout=0.5), project):
            if open_browser:
                webbrowser.open(_url(port))
            return {"url": _url(port), "pid": proc.pid, "reused": False}
        if proc.poll() is not None:
            return {"error": "dashboard exited with code %s; see %s" % (proc.returncode, log_path(project, cfg))}
        time.sleep(0.2)
    return {"error": "dashboard did not answer on port %d within 5 s; see %s" % (port, log_path(project, cfg))}


def cmd_stop(project, cfg=None):
    state = read_state(project, cfg)
    if not state:
        return {"running": False}
    info = health(state.get("port"))
    if _same_project(info, project) and info.get("pid") == state.get("pid"):
        try:
            os.kill(state["pid"], signal.SIGTERM)
        except OSError as exc:
            return {"error": "could not stop pid %s: %s" % (state["pid"], exc)}
    remove_state(project, cfg)
    return {"stopped": True}


def cmd_status(project, cfg=None):
    state = read_state(project, cfg)
    if state:
        info = health(state.get("port"))
        if _same_project(info, project):
            return {"running": True, "url": _url(state["port"]), "pid": info.get("pid")}
    return {"running": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local, read-only dashboard for sdlc-pipeline runs.")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    for name in ("start", "serve", "stop", "status"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
        if name == "start":
            command.add_argument("--open", action="store_true")
        if name == "serve":
            command.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.project, args.port)
        return 0
    if args.command == "start":
        result = cmd_start(args.project, args.open)
    elif args.command == "stop":
        result = cmd_stop(args.project)
    else:
        result = cmd_status(args.project)
    print(json.dumps(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_server.py`
Expected: `OK` (9 tests). If `CliTest` fails, read the log file named in the `error` field.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline-ui.py scripts/pipeline-ui.html tests/pipeline-ui/test_server.py
git commit -m "feat: pipeline-ui local server and CLI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The dashboard page

**Files:**
- Modify (replace): `scripts/pipeline-ui.html`
- Create: `tests/pipeline-ui/demo_server.py`
- Test: `tests/pipeline-ui/test_page.py`

**Interfaces:**
- Consumes: the HTTP API from Task 8 and the JSON shapes from Task 7.
- Produces: the page (runs list at `#`, run view at `#run=<encoded id>`); `demo_server.py` serves the EMI-shaped fixture for manual checks.

- [ ] **Step 1: Write the failing page tests**

`tests/pipeline-ui/test_page.py`:

```python
"""Static checks for scripts/pipeline-ui.html."""
import os
import re
import unittest

import fixture_builder as fb

PAGE = os.path.join(fb.SCRIPTS, "pipeline-ui.html")


class PageTest(unittest.TestCase):
    def setUp(self):
        with open(PAGE, encoding="utf-8") as fh:
            self.html = fh.read()

    def test_no_external_resources(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']https?://""", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("fonts.googleapis", self.html)

    def test_never_renders_markup_from_data(self):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(banned, self.html, banned)

    def test_title_dark_mode_and_mobile(self):
        self.assertIn("<title>Pipeline runs</title>", self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn('name="viewport"', self.html)

    def test_uses_every_api_route(self):
        for route in ("/api/runs", "/api/diff", "/api/file"):
            self.assertIn(route, self.html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_page.py`
Expected: FAIL — `prefers-color-scheme: dark` and `/api/diff` not found in the placeholder.

- [ ] **Step 3: Replace `scripts/pipeline-ui.html` with the page**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline runs</title>
<style>
:root {
  --bg: #f6f6f3; --panel: #ffffff; --text: #1d1d1b; --muted: #6b6b66; --line: #e2e1dc;
  --accent: #2f5fd0; --ok: #1f7a4d; --warn: #9a5800; --bad: #b3261e; --add: #e3f4e8; --del: #fbe7e5;
  --mono: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --panel: #1f1f1d; --text: #ecebe6; --muted: #9a9993; --line: #34342f;
    --accent: #8fb0ff; --ok: #5fcf95; --warn: #f0b35a; --bad: #ff8a80; --add: #173a26; --del: #4a1f1c;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: baseline; padding: 12px 16px; border-bottom: 1px solid var(--line); background: var(--panel); position: sticky; top: 0; z-index: 1; }
header h1 { font-size: 16px; margin: 0; }
header a.home { color: inherit; text-decoration: none; }
.grow { flex: 1; }
main { max-width: 1200px; margin: 0 auto; padding: 16px 16px 48px; }
a { color: var(--accent); }
code { font-family: var(--mono); font-size: 12px; }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.nowrap { white-space: nowrap; }
.err { color: var(--bad); padding: 0 16px; }
.warn { padding: 8px 10px; border: 1px solid var(--warn); color: var(--warn); border-radius: 6px; margin: 10px 0; }
.wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; font-size: 12px; color: var(--muted); }
th.sort { cursor: pointer; }
tr.click { cursor: pointer; }
tr.click:hover td, tr.click:focus td { background: var(--bg); }
tr.orch td { background: var(--bg); }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.badge { display: inline-block; padding: 0 8px; border-radius: 999px; font-size: 12px; border: 1px solid currentColor; white-space: nowrap; }
.s-running { color: var(--accent); } .s-waiting { color: var(--warn); } .s-finished { color: var(--ok); }
.s-stopped { color: var(--muted); } .s-interrupted, .s-error { color: var(--bad); }
.tag { margin-left: 6px; font-size: 11px; padding: 0 6px; border-radius: 4px; background: var(--warn); color: var(--panel); }
section { margin-top: 22px; }
h2 { font-size: 14px; margin: 0 0 8px; }
h2.title { font-size: 18px; margin-top: 4px; }
h3 { font-size: 13px; margin: 12px 0 4px; }
.timeline { display: flex; flex-wrap: wrap; gap: 6px; }
.stage { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); font-size: 12px; min-width: 110px; }
.stage.done { border-color: var(--ok); }
.stage.in-progress { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
.stage.skipped { opacity: .55; border-style: dashed; }
.stage.not-reached { opacity: .45; }
.stage.cp { min-width: 0; border-color: var(--warn); }
.stage.cp.pending { box-shadow: inset 0 0 0 1px var(--warn); }
ol.cps { padding-left: 20px; margin: 0; }
ol.cps li { margin: 0 0 10px; }
ul.commits, ul.files { list-style: none; padding: 0; margin: 0; }
ul.commits li, ul.files li { margin: 6px 0; }
button { font: inherit; font-size: 12px; padding: 2px 10px; border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 6px; cursor: pointer; }
pre { font: 12px/1.4 var(--mono); white-space: pre-wrap; word-break: break-word; margin: 8px 0 0; padding: 10px; background: var(--panel); border: 1px solid var(--line); border-radius: 6px; max-height: 520px; overflow: auto; }
pre .add { background: var(--add); } pre .del { background: var(--del); }
.empty { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }
@media (max-width: 700px) { .hide-sm { display: none; } th, td { padding: 6px; } }
</style>
</head>
<body>
<header>
  <h1><a class="home" href="#">Pipeline runs</a></h1>
  <span id="project" class="muted small"></span>
  <span class="grow"></span>
  <span id="updated" class="muted small"></span>
</header>
<div id="err" class="err" role="status"></div>
<main id="main"><p class="muted">Loading&hellip;</p></main>
<script>
"use strict";
const state = { timer: null, updated: 0, sort: "start", diffs: new Map(), file: null };
const $ = (selector) => document.querySelector(selector);

// Build DOM with text nodes only: transcript text can never become markup.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const STATUS_LABEL = { running: "running", waiting: "waiting for you", finished: "finished",
  stopped: "stopped", interrupted: "interrupted", error: "error" };

function ago(epochSeconds) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (s < 60) return s + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  if (s < 86400) return Math.round(s / 3600) + " h";
  return Math.round(s / 86400) + " d";
}
function badge(status, since) {
  const label = (STATUS_LABEL[status] || status) + (status === "waiting" && since ? " \u00b7 " + ago(since) : "");
  return h("span", { class: "badge s-" + status }, label);
}
function fmtTokens(n) {
  if (n === null || n === undefined) return "\u2014";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}
function fmtCost(cost, complete) {
  if (cost === null || cost === undefined || (!cost && !complete)) return "\u2014";
  return "$" + cost.toFixed(cost < 1 ? 3 : 2) + (complete ? "" : "+");
}
function fmtDur(seconds) {
  if (seconds === null || seconds === undefined) return "\u2014";
  const s = Math.round(seconds);
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + "m " + (s % 60) + "s";
  return Math.floor(m / 60) + "h " + (m % 60) + "m";
}
function fmtTime(iso) {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return isNaN(d) ? String(iso) : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function isLive(status) { return status === "running" || status === "waiting"; }
function route() { const m = location.hash.match(/^#run=(.+)$/); return m ? decodeURIComponent(m[1]) : null; }
function openRun(id) { location.hash = "run=" + encodeURIComponent(id); }
async function getJSON(url) { const r = await fetch(url, { cache: "no-store" }); if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.json(); }
async function getText(url) { const r = await fetch(url, { cache: "no-store" }); if (!r.ok) throw new Error(r.status + " " + r.statusText); return r.text(); }
function show(node) { $("#main").replaceChildren(node); }

async function refresh() {
  clearTimeout(state.timer);
  const id = route();
  let live = false;
  try {
    if (id) {
      const d = await getJSON("/api/runs/" + encodeURIComponent(id));
      show(renderRun(d));
      live = isLive(d.status);
      document.title = d.title + " \u00b7 Pipeline runs";
    } else {
      const d = await getJSON("/api/runs");
      $("#project").textContent = d.project;
      show(renderList(d));
      live = d.runs.some((r) => isLive(r.status));
      document.title = "Pipeline runs";
    }
    state.updated = Date.now();
    $("#err").textContent = "";
  } catch (e) {
    $("#err").textContent = "Could not load from the dashboard server (" + e.message + "). If it stopped, run /sdlc-pipeline:pipeline-ui again.";
  }
  state.timer = setTimeout(refresh, live ? 3000 : 30000);
}

function renderList(d) {
  if (!d.runs.length) {
    return h("div", { class: "empty" },
      h("p", {}, "No pipeline runs found for ", h("code", {}, d.project), "."),
      h("p", { class: "muted" }, "Looked in:"),
      h("ul", {}, (d.folders.length ? d.folders : ["(no transcript folder for this project yet)"]).map((f) => h("li", {}, h("code", {}, f)))),
      h("p", { class: "muted" }, "Start a run with /sdlc-pipeline:pipeline-ui and it appears here."));
  }
  const head = [["Started", ""], ["Flow", ""], ["Feature", ""], ["Branch", "hide-sm"], ["Status", ""],
    ["Duration", "num hide-sm"], ["Tokens", "num"], ["Est. cost", "num"]];
  const rows = d.runs.map((r) => h("tr", { class: "click", tabindex: 0, onclick: () => openRun(r.id),
      onkeydown: (e) => { if (e.key === "Enter") openRun(r.id); } },
    h("td", { class: "nowrap" }, fmtTime(r.started)),
    h("td", {}, r.flow),
    h("td", {}, r.title,
      r.resumed_from ? h("div", { class: "muted small" }, "resumed from an earlier run on this branch") : null,
      r.errors ? h("div", { class: "err small" }, Object.values(r.errors).join("; ")) : null),
    h("td", { class: "hide-sm" }, h("code", {}, r.branch || "\u2014")),
    h("td", {}, badge(r.status, r.waiting_since)),
    h("td", { class: "num hide-sm" }, fmtDur(r.duration_s)),
    h("td", { class: "num" }, fmtTokens(r.tokens && r.tokens.total)),
    h("td", { class: "num" }, fmtCost(r.cost, r.cost_complete))));
  return h("div", { class: "wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map(([label, cls]) => h("th", { class: cls || null }, label)))),
    h("tbody", {}, rows)));
}

function part(title, error, build) {
  return h("section", {}, h("h2", {}, title),
    error ? h("p", { class: "err" }, "Could not read this part: " + error) : build());
}

function renderRun(d) {
  const byId = {};
  (d.agents || []).forEach((a) => { byId[a.id] = a; });
  const errs = d.errors || {};
  return h("div", {},
    h("p", {}, h("a", { href: "#" }, "\u2190 All runs")),
    h("h2", { class: "title" }, d.title),
    h("p", { class: "muted" }, d.flow, " \u00b7 ", h("code", {}, d.branch || "\u2014"), " \u00b7 started ",
      fmtTime(d.started), " \u00b7 ", fmtDur(d.duration_s), " \u00b7 ", fmtTokens(d.tokens && d.tokens.total),
      " tokens \u00b7 ", fmtCost(d.cost, d.cost_complete), " (estimate) ", badge(d.status, d.waiting_since)),
    (d.warnings || []).map((w) => h("div", { class: "warn" }, w)),
    errs.run ? h("div", { class: "warn" }, "This run could not be read fully: " + errs.run) : null,
    part("Stages", errs.stages, () => timeline(d.stages || [], d.checkpoints || [], byId)),
    part("Agents", errs.agents, () => agentsTable(d.agents || [])),
    part("Questions", errs.checkpoints, () => checkpointList(d.checkpoints || [])),
    part("Tasks and changes", errs.tasks, () => tasksView(d.id, d.tasks)),
    part("Files", errs.artifacts, () => artifactsView(d.id, d.artifacts || [])));
}

function timeline(stages, checkpoints, byId) {
  const cps = checkpoints.slice().sort((a, b) => String(a.time || "").localeCompare(String(b.time || "")));
  const items = [];
  let next = 0;
  for (const s of stages) {
    const starts = s.agents.map((id) => byId[id] && byId[id].started).filter(Boolean).sort();
    if (starts.length) while (next < cps.length && String(cps[next].time || "") < starts[0]) items.push(cpChip(cps[next++]));
    items.push(h("div", { class: "stage " + s.state.replace(/\s+/g, "-"), title: s.state },
      h("div", {}, s.key + " \u00b7 " + s.label),
      h("div", { class: "muted small" }, s.state + (s.agents.length ? " \u00b7 " + s.agents.length + (s.agents.length === 1 ? " agent" : " agents") : ""))));
  }
  while (next < cps.length) items.push(cpChip(cps[next++]));
  return h("div", { class: "timeline" }, items);
}
function cpChip(cp) {
  const first = cp.questions[0] || {};
  return h("div", { class: "stage cp" + (cp.pending ? " pending" : ""), title: cp.questions.map((q) => q.question).join("\n") },
    h("div", {}, "? " + (first.header || "Question")),
    h("div", { class: "muted small" }, cp.pending ? "waiting for you" : "answered"));
}

const SORTS = {
  start: (a, b) => String(a.started || "").localeCompare(String(b.started || "")),
  cost: (a, b) => (b.cost || 0) - (a.cost || 0),
  duration: (a, b) => (b.duration_s || 0) - (a.duration_s || 0),
};
function agentsTable(rows) {
  const sorted = rows.slice().sort(SORTS[state.sort] || SORTS.start);
  const sortHead = (label, key) => h("th", { class: "num sort", title: "Sort by " + label.toLowerCase(),
    onclick: () => { state.sort = state.sort === key ? "start" : key; refresh(); } }, label + (state.sort === key ? " \u25be" : ""));
  return h("div", { class: "wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Stage"), h("th", {}, "Agent"), h("th", { class: "hide-sm" }, "Model"),
      h("th", { class: "hide-sm" }, "Started"), sortHead("Duration", "duration"), h("th", { class: "num hide-sm" }, "Input"),
      h("th", { class: "num hide-sm" }, "Output"), h("th", { class: "num hide-sm" }, "Cache write"),
      h("th", { class: "num hide-sm" }, "Cache read"), sortHead("Est. cost", "cost"), h("th", {}, "State"))),
    h("tbody", {}, sorted.map((a) => h("tr", { class: a.type === "orchestrator" ? "orch" : null },
      h("td", { class: "nowrap" }, a.stage_label, a.fix ? h("span", { class: "tag" }, "fix") : null),
      h("td", {}, h("div", {}, (a.parent ? "\u21b3 " : "") + a.type), h("div", { class: "muted small" }, a.description)),
      h("td", { class: "hide-sm" }, a.model || "\u2014"),
      h("td", { class: "hide-sm nowrap" }, fmtTime(a.started)),
      h("td", { class: "num" }, fmtDur(a.duration_s)),
      h("td", { class: "num hide-sm" }, fmtTokens(a.tokens.input)),
      h("td", { class: "num hide-sm" }, fmtTokens(a.tokens.output)),
      h("td", { class: "num hide-sm" }, fmtTokens(a.tokens.cache_write)),
      h("td", { class: "num hide-sm" }, fmtTokens(a.tokens.cache_read)),
      h("td", { class: "num" }, fmtCost(a.cost, a.cost_complete)),
      h("td", {}, badge(a.status || "stopped")))))));
}

function checkpointList(cps) {
  if (!cps.length) return h("p", { class: "muted" }, "No questions asked yet.");
  return h("ol", { class: "cps" }, cps.map((cp) => h("li", {},
    h("div", { class: "muted small" }, fmtTime(cp.time)),
    cp.questions.map((q) => h("div", {}, q.header ? h("strong", {}, q.header + ": ") : null, q.question)),
    h("div", {}, cp.pending ? badge("waiting")
      : h("span", {}, "\u2192 ", cp.answer || "(no answer text)",
          cp.answered_in_chat ? h("span", { class: "muted small" }, " (answered in chat)") : null)))));
}

function tasksView(runId, t) {
  if (!t) return h("p", { class: "muted" }, "\u2014");
  const blocks = [];
  if (!t.git) blocks.push(h("p", { class: "muted" }, "Git is not available here, so commits and diffs are hidden."));
  if (t.tasks.length) {
    for (const task of t.tasks) {
      blocks.push(h("div", {}, h("h3", {}, "Task " + task.id + " \u2014 " + task.name),
        commitList(runId, task.commits, t.git, "No commit mentions this task yet.")));
    }
  } else if (t.bug_plans.length) {
    blocks.push(h("p", {}, "Bug plan: ", t.bug_plans.map((p) => h("code", {}, p + " "))));
  } else {
    blocks.push(h("p", { class: "muted" }, "No plan yet" + (t.slug ? " (looked in docs/plans/" + t.slug + "/)." : ".")));
  }
  if (t.other_commits.length) {
    blocks.push(h("div", {}, h("h3", {}, t.tasks.length ? "Other commits" : "Commits"), commitList(runId, t.other_commits, t.git, "")));
  }
  return h("div", {}, blocks);
}
function commitList(runId, commits, git, empty) {
  if (!commits.length) return empty ? h("p", { class: "muted small" }, empty) : null;
  return h("ul", { class: "commits" }, commits.map((c) => h("li", {},
    h("code", {}, c.sha.slice(0, 8)), " ", c.subject, " ", h("span", { class: "muted small" }, fmtTime(c.time)), " ",
    git ? h("button", { onclick: () => toggleDiff(runId, c.sha) }, state.diffs.has(c.sha) ? "hide diff" : "show diff") : null,
    state.diffs.has(c.sha) ? diffView(state.diffs.get(c.sha)) : null)));
}
async function toggleDiff(runId, sha) {
  if (state.diffs.has(sha)) { state.diffs.delete(sha); refresh(); return; }
  state.diffs.set(sha, "Loading\u2026");
  refresh();
  try {
    state.diffs.set(sha, await getText("/api/diff?run=" + encodeURIComponent(runId) + "&commit=" + encodeURIComponent(sha)));
  } catch (e) {
    state.diffs.set(sha, "Could not load this diff: " + e.message);
  }
  refresh();
}
function diffView(text) {
  return h("pre", {}, text.split("\n").map((line) => h("span", {
    class: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : null,
  }, line + "\n")));
}

function artifactsView(runId, items) {
  if (!items.length) return h("p", { class: "muted" }, "No plan, requirements or reports found for this run yet.");
  const url = (key) => "/api/file?run=" + encodeURIComponent(runId) + "&key=" + encodeURIComponent(key);
  return h("div", {},
    h("ul", { class: "files" }, items.map((a) => h("li", {},
      a.kind === "html"
        ? h("a", { href: url(a.key), target: "_blank", rel: "noopener" }, a.label)
        : h("button", { onclick: () => toggleFile(url(a.key), a.key) }, (state.file && state.file.key === a.key ? "hide " : "") + a.label),
      " ", h("code", { class: "muted" }, a.path)))),
    state.file ? h("pre", {}, state.file.text) : null);
}
async function toggleFile(url, key) {
  if (state.file && state.file.key === key) { state.file = null; refresh(); return; }
  state.file = { key: key, text: "Loading\u2026" };
  refresh();
  try { state.file = { key: key, text: await getText(url) }; }
  catch (e) { state.file = { key: key, text: "Could not load this file: " + e.message }; }
  refresh();
}

setInterval(() => {
  if (state.updated) $("#updated").textContent = "updated " + Math.round((Date.now() - state.updated) / 1000) + " s ago";
}, 1000);
window.addEventListener("hashchange", () => { state.diffs.clear(); state.file = null; refresh(); });
refresh();
</script>
</body>
</html>
```

- [ ] **Step 4: Add the demo server for manual checks**

`tests/pipeline-ui/demo_server.py`:

```python
"""Serve the EMI-shaped fixture so the page can be checked in a browser.

    python -I tests/pipeline-ui/demo_server.py      (Ctrl+C to stop)
"""
import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixture_builder as fb  # noqa: E402

spec = importlib.util.spec_from_file_location("pipeline_ui_cli", os.path.join(fb.SCRIPTS, "pipeline-ui.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def main():
    tmp = tempfile.mkdtemp(prefix="pipeline-ui-demo-")
    repo = fb.make_git_repo(os.path.join(tmp, "repo"))
    cfg = os.path.join(tmp, "cfg")
    fb.emi_like(cfg, repo)
    port = cli.free_port()
    server = cli.make_server(repo, port, cfg=cfg)
    print("Demo dashboard: http://127.0.0.1:%d/  (fixture in %s)" % (port, tmp), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_page.py`
Expected: `OK` (4 tests). Then `python -I -m unittest discover -s tests/pipeline-ui -p test_server.py` → `OK`.

- [ ] **Step 6: Check the page in a browser**

Run `python -I tests/pipeline-ui/demo_server.py` in the background and open the printed URL in the built-in browser. Check, and fix the page if any fails:
1. The runs list shows two runs: *Fix rounding* (waiting for you) above *Add calculate_emi…* (finished), with tokens and an estimated cost ending in `+`.
2. Opening the first run shows the stage timeline (R … 6, with 0.8/2.7/4/4.5/5.5/5.8 dashed as skipped) and two question chips placed before Q and before Build.
3. The agents table has 15 rows; `implementer` with a `fix` tag under Acceptance; `↳ Explore` under Plan; sorting by cost and duration works.
4. Questions show "→ Approve" and "→ Approve it (answered in chat)".
5. Tasks 01–03 each list one commit; "show diff" expands a coloured diff of `emi.py`.
6. Files: Markdown opens as text below the list; `phase3.html` opens in a new tab.
7. The warning "1 line could not be read · Claude Code 2.1.312" is shown.
8. At 375 px wide (mobile preset) there is no horizontal page scroll (tables scroll inside their box).
9. Dark mode (colorScheme dark) is readable.
Stop the demo server afterwards.

- [ ] **Step 7: Commit**

```bash
git add scripts/pipeline-ui.html tests/pipeline-ui/demo_server.py tests/pipeline-ui/test_page.py
git commit -m "feat: pipeline-ui dashboard page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The `/pipeline-ui` command, README and version

**Files:**
- Create: `commands/pipeline-ui.md`
- Modify: `README.md` (new section before `## Workflow`)
- Modify: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json` (`3.4.1` → `3.5.0`)
- Test: `tests/pipeline-ui/test_command.py`

**Interfaces:**
- Consumes: `scripts/pipeline-ui.py start` JSON (Task 8).
- Produces: the user-facing command `/sdlc-pipeline:pipeline-ui`.

- [ ] **Step 1: Record the validator baseline**

Run: `claude plugin validate . 2>&1 | tail -5` and note the warning count, so Step 7 can compare.

- [ ] **Step 2: Write the failing test**

`tests/pipeline-ui/test_command.py`:

```python
"""Checks for commands/pipeline-ui.md and the version bump."""
import json
import os
import unittest

import fixture_builder as fb

COMMAND = os.path.join(fb.REPO_ROOT, "commands", "pipeline-ui.md")


class CommandTest(unittest.TestCase):
    def setUp(self):
        with open(COMMAND, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\ndescription: "))
        self.assertIn("\nargument-hint: ", self.text.split("\n---\n", 1)[0])

    def test_starts_the_dashboard_then_hands_off(self):
        self.assertIn('scripts/pipeline-ui.py" start --project', self.text)
        for flow in ("pipeline-all", "pipeline", "pipeline-parallel"):
            self.assertIn("`%s`" % flow, self.text)
        self.assertIn("sdlc-pipeline:<flow>", self.text)

    def test_versions(self):
        for relative in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"):
            with open(os.path.join(fb.REPO_ROOT, relative), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], "3.5.0", relative)
        with open(os.path.join(fb.REPO_ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["plugins"][0]["version"], "3.5.0")


if __name__ == "__main__":
    unittest.main()
```

Run: `python -I -m unittest discover -s tests/pipeline-ui -p test_command.py`
Expected: ERROR — `FileNotFoundError` for `commands/pipeline-ui.md`.

- [ ] **Step 3: Write `commands/pipeline-ui.md`**

````markdown
---
description: Open the local run dashboard, then run /pipeline-all, /pipeline or /pipeline-parallel unchanged. The dashboard is read-only and shows stages, agents, token usage, questions and each task's changes live.
argument-hint: [--flow pipeline-all|pipeline|pipeline-parallel] <request, as for the chosen flow>
---

# /pipeline-ui — dashboard + pipeline

You are the **orchestrator**. This command puts a dashboard in front of an existing flow and
nothing else. After Step 4 you follow the chosen flow's own instructions exactly; this file adds
no stages, rules or questions after the hand-off.

Arguments: $ARGUMENTS

## Step 1 — Start the dashboard (one Bash call)

If the arguments contain `--flow <name>`, remember `<name>` and remove `--flow <name>`; what is
left is `<request>`.

Run exactly this one command:

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then python "${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-ui.py" start --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" --open; else echo '{"error":"needs-claude-code"}'; fi
```

It prints one JSON line and returns at once; the dashboard keeps running in the background.

## Step 2 — Tell the client (one line, in the same turn as Step 3)

- `{"url": ...}` → `Dashboard: <url>`, adding ` (already running)` when `reused` is true.
- `{"error": "needs-claude-code"}` → `The dashboard needs Claude Code; continuing without it.`
- any other `{"error": ...}` → `Dashboard not started: <error> — continuing without it.`

A failed start never stops the run.

## Step 3 — Choose the flow

If `--flow` named `pipeline-all`, `pipeline` or `pipeline-parallel`, use it. If it named
anything else, say `Unknown flow "<name>".` and ask as below. Otherwise ask once with
`AskUserQuestion` — question "Which flow should run?", header "Flow":

- `pipeline-all (Recommended)` — New features, requirements first: requirements document, BA analysis, plan, build, reviews, acceptance gate, PR.
- `pipeline` — Features or bugs, built one task at a time.
- `pipeline-parallel` — Features or bugs, independent tasks built in parallel waves.

Drop ` (Recommended)` from the answer to get `<flow>`.

## Step 4 — Hand off

Invoke the Skill tool with skill `sdlc-pipeline:<flow>` and args `<request>` exactly as given
(empty if there is none). From then on, follow that skill's instructions exactly, as if the
client had typed `/sdlc-pipeline:<flow> <request>`.

## Stopping the dashboard

It stops by itself after two hours with nobody viewing it. Only if the client asks to stop it
now, run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-ui.py" stop --project "$(git rev-parse --show-toplevel)"
```
````

- [ ] **Step 4: Add the README section**

Insert this immediately before the `## Workflow` heading in `README.md` (find it with Grep for `^## Workflow`):

````markdown
## Watching a run

`/sdlc-pipeline:pipeline-ui <request>` opens a dashboard in your browser, asks which flow to run
(`pipeline-all`, `pipeline` or `pipeline-parallel`), then runs that flow exactly as if you had
typed it. Add `--flow pipeline-all` to skip the question.

The dashboard refreshes every few seconds and shows:

- every pipeline run in this repository, newest first, with its status (*running*, *waiting for
  you*, *finished*, *stopped*), duration, tokens and estimated cost;
- for one run: the stage timeline with the questions asked, every agent with its model, time and
  tokens, your answers, each task's commits with their diffs, and links to the plan,
  requirements, stories and reports.

It is read-only and local. It reads the transcripts Claude Code already keeps under
`~/.claude/projects/` (or `$CLAUDE_CONFIG_DIR`), your git history and `docs/plans/`. It listens
on `127.0.0.1` only, and nothing leaves your machine. Runs started with the other pipeline
commands appear too. Costs are estimates from `scripts/pipeline-ui-prices.json`, which you can
edit.

It stops by itself after two hours with nobody viewing it. To stop it sooner, ask Claude to stop
the pipeline dashboard, or run:

```bash
python "<plugin folder>/scripts/pipeline-ui.py" stop --project "$(git rev-parse --show-toplevel)"
```

Cursor does not write Claude Code transcripts, so in Cursor `/pipeline-ui` skips the dashboard
and runs the flow as normal. The transcript format is not a published contract: if a Claude
Code update changes it, the dashboard shows a warning instead of failing.

````

- [ ] **Step 5: Bump the version**

In `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json` and `.claude-plugin/marketplace.json`, change `"version": "3.4.1"` to `"version": "3.5.0"` (one occurrence in each file; use Edit, not sed).

- [ ] **Step 6: Run every test suite**

Run each and expect `OK`:
- `python -I -m unittest discover -s tests/pipeline-ui`
- `python -I -m unittest discover -s tests/acceptance`
- `python -m unittest discover -s hooks/tests`

- [ ] **Step 7: Validate the plugin**

Run: `claude plugin validate . 2>&1 | tail -5`
Expected: the same warning count as Step 1. If there is a new warning, report it and its cause; fix it if it comes from `commands/pipeline-ui.md`.

- [ ] **Step 8: Commit**

```bash
git add commands/pipeline-ui.md README.md .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json tests/pipeline-ui/test_command.py
git commit -m "feat: /pipeline-ui command, README and version 3.5.0" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Reinstall and a real run (client)

Done by the client, not an agent.

- [ ] Reinstall the plugin from this branch (README → Updating).
- [ ] In a small throwaway repository (the EMI demo is ideal), run `/sdlc-pipeline:pipeline-ui Add a Python function calculate_emi(...)` in the Claude Code CLI, choose `pipeline-all`, and keep the dashboard open through the whole run.
- [ ] Check while it runs: the stage moves forward, agents appear as they start and turn *finished*, *waiting for you* shows at every question, tokens grow, and each task's commit and diff appear after Build.
- [ ] Repeat the start in the desktop app (Code tab) and confirm the second start says `(already running)`.
- [ ] Report anything that looks wrong, with a screenshot and the run's `Claude Code` version from the agents' transcripts.
