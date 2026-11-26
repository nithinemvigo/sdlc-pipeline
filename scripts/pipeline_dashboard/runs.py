"""Find pipeline runs in a main-session transcript."""
import re

from .entries import message_text, tool_uses

CMD_RE = re.compile(
    r"<command-name>/?(?:sdlc-pipeline:)?(pipeline-all|pipeline-parallel|pipeline-dashboard|pipeline-ui|pipeline)</command-name>")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
FLOWS = ("pipeline-all", "pipeline", "pipeline-parallel")
# Commands that open the dashboard and then hand off to a flow. "pipeline-ui" is the name before the
# rename; keep it so runs started under it still show.
DASHBOARD_COMMANDS = ("pipeline-dashboard", "pipeline-ui")
BASE_BRANCHES = ("main", "master")
CHOOSING = "choosing…"
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
    """The flow that runs: the command itself, or for pipeline-dashboard the flow it handed off to."""
    if command not in DASHBOARD_COMMANDS:
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
