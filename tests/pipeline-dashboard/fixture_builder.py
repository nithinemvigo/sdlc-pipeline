"""Hand-built Claude Code transcripts for the pipeline-dashboard tests. No real session content."""
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(REPO_ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from pipeline_dashboard import transcripts  # noqa: E402
from pipeline_dashboard.timeutil import parse_ts  # noqa: E402

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


def emi_like(cfg, repo, mtime=None):
    """Two runs in one session, shaped like the 2026-10-29 EMI run.

    Run 1: /pipeline-dashboard -> pipeline-all, an agent for every stage it reaches, a fix round after the
    acceptance verifier, an unknown agent without meta, a nested agent, a notification-only finish,
    two questions (one answered in chat), a duplicated response, one invalid line. Shipped.
    Run 2: /pipeline on master, one pending question.
    Every file gets mtime = ts(45) unless given.
    """
    mtime = parse_ts(ts(45)) if mtime is None else mtime
    s = Transcript(session_id="sess-emi", cwd=repo, branch="master")
    s.command(0, "pipeline-dashboard", "Add calculate_emi(principal, annual_rate, months)\nRound half up.")
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


def no_branch_run(cfg, repo, session_id="sess-nob", planner_write=True, checkout=True, slug="calculate-emi",
                  start=46):
    """One /pipeline-dashboard run whose entries carry gitBranch "HEAD" (the repo had no commit yet), shaped
    like the 2026-11-05 EMI demo: the planner Writes docs/plans/<slug>/00-overview.md and the
    orchestrator later runs `git checkout -q -b feature/<slug>`. Minutes start to start+9 (46-55 by
    default); every file's mtime is the last of them. Returns the run id."""
    mtime = parse_ts(ts(start + 9))
    s = Transcript(session_id=session_id, cwd=repo, branch="HEAD")
    s.command(start, "pipeline-dashboard", "Add calculate_emi without a branch")
    run_line = len(s.lines)
    s.tool_use(start, "Skill", {"skill": "sdlc-pipeline:pipeline-all", "args": "Add calculate_emi"}, "tu-nb-skill")
    s.tool_result(start, "tu-nb-skill", "Launching skill: sdlc-pipeline:pipeline-all")
    s.tool_use(start + 1, "Bash", {"command": "git init -q -b master && git commit -q --allow-empty -m base"},
               "tu-nb-init")
    s.tool_result(start + 1, "tu-nb-init", "")
    s.tool_use(start + 2, "Agent", {"subagent_type": "sdlc-pipeline:planner", "description": "Plan EMI feature"},
               "tu-nb-pl")
    s.tool_result(start + 2, "tu-nb-pl", "Async agent launched successfully.\nagentId: nb-pl")
    if checkout:
        s.tool_use(start + 4, "Bash",
                   {"command": "cd %s\ngit add -A && git checkout -q -b feature/%s" % (repo, slug)}, "tu-nb-co")
        s.tool_result(start + 4, "tu-nb-co", "")
    s.text(start + 8, "Shipped.")
    write_session(cfg, repo, s, mtime=mtime)

    t = Transcript(session_id=session_id, cwd=repo, branch="HEAD", sidechain=True, agent_id="nb-pl")
    t.user(start + 2, "Plan the feature.")
    if planner_write:
        overview = os.path.join(repo, "docs", "plans", slug, "00-overview.md")
        t.tool_use(start + 3, "Write", {"file_path": overview, "content": "# Plan\n"}, "tu-nb-pl-w")
        t.tool_result(start + 3, "tu-nb-pl-w", "File created successfully")
    t.tool_use(start + 3, "SubagentHandback", {"message": "Plan ready."}, "tu-nb-pl-h", second=30)
    t.tool_result(start + 3, "tu-nb-pl-h", '{"success":true}', second=31)
    write_agent(cfg, repo, session_id, t, "sdlc-pipeline:planner", "Plan EMI feature", "tu-nb-pl", mtime=mtime)
    return "%s:%d" % (session_id, run_line)
