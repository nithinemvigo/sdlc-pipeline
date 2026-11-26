"""Plan, requirements and report files a run produced. Only known files inside the repo."""
import glob
import os
import re

from .entries import message_text, tool_uses

_VALUE = r"(?:\"([^\"]+)\"|'([^']+)'|(\S+))"
REQ_RE = re.compile(r"--requirements\s+" + _VALUE)
ROOT_RE = re.compile(r"--artifact-root\s+" + _VALUE)
TASK_RE = re.compile(r"^task-(\d+)-(.+)\.md$")
# a slug read from transcript text: one plain path segment, never '..' or an option
SAFE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_PATH_PREFIX = r"(?:^|[\\/\s\"'`(])docs[\\/]plans[\\/]([^\\/\s\"'`]+)[\\/]00-overview\.md"
OVERVIEW_RE = re.compile(_PATH_PREFIX + r"\b")  # prose: the file name may be followed by punctuation
OVERVIEW_PATH_RE = re.compile(_PATH_PREFIX + r"\Z")  # a Write's file_path ends with the file name
# a git command that creates a feature branch, after heredoc bodies and quoted strings were masked
_MASK = "\uE000"
# Spaces within one command: blanks, or a line continuation (Bash `\`+newline, PowerShell backtick+newline).
# A bare newline ends the command, so nothing here may cross one; that also keeps the scan linear.
_SP = r"(?:[ \t]|\\\r?\n|`\r?\n)"
_WORD = r"[^\s;&|]+"
_GIT_OPTION = (r"(?:-[Cc]" + _SP + r"+" + _WORD + r"|--(?:git-dir|work-tree|namespace)(?:=|" + _SP + r"+)"
               + _WORD + r"|--[a-z][\w-]*(?:=" + _WORD + r")?|-[pP])" + _SP + r"+")
_COMMAND_START = r"(?:^|[\n;&|({])[ \t]*(?:(?:then|do)" + _SP + r"+)?"
_OPTIONS = r"(?:-[\w-]+" + _SP + r"+)*?"
_CREATE = (r"(?:switch" + _SP + r"+" + _OPTIONS + r"(?:-[cC]" + _SP + r"+|--(?:force-)?create(?:" + _SP + r"+|=))"
           r"|checkout" + _SP + r"+" + _OPTIONS + r"-[bB]" + _SP + r"+)")
NEW_BRANCH_RE = re.compile(
    _COMMAND_START + r"git" + _SP + r"+(?:" + _GIT_OPTION + r")*" + _CREATE
    + r"(?:feature/([^\s\"';&|)" + _MASK + r"]+)|" + _MASK + r"(\d+)" + _MASK + r")")
# Bash: `<<DELIM`, `<<-DELIM`, `<<'DELIM'`, `<<"DELIM"` or `<<\DELIM`; not `<<<` and not `1<<2`
BASH_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(?:\\|(['\"]?))(?!\d)([\w.-]+)(?(2)\2)")
POWERSHELL_HERE_STRING_RE = re.compile(r"@(['\"])[ \t]*\r?\n.*?(?:^\1@|\Z)", re.DOTALL | re.MULTILINE)
# A quote left open runs to the end of the command. The only groups are the closing quotes.
BASH_QUOTED_RE = re.compile(r"'[^']*(?:(')|\Z)|\"(?:[^\"\\]|\\.?)*(?:(\")|\Z)", re.DOTALL)
POWERSHELL_QUOTED_RE = re.compile(r"'(?:[^']|'')*(?:(')|\Z)|\"(?:[^\"`]|`.?|\"\")*(?:(\")|\Z)",
                                  re.DOTALL)
PLANNER = "planner"
WRITE_TOOLS = ("Write",)


def slug_of(branch):
    """'feature/calculate-emi' -> 'calculate-emi'; None for a branch without '/' or a bad slug."""
    if not branch or "/" not in branch:
        return None
    slug = branch.split("/", 1)[1]
    if not slug or ".." in slug or slug.startswith(("/", "\\")):
        return None
    return slug


def _safe(slug):
    return slug if slug and ".." not in slug and SAFE_SLUG_RE.match(slug) else None


def _written_overviews(entries):
    for entry in entries:
        for _tid, name, tool_input in tool_uses(entry):
            path = tool_input.get("file_path")
            if name in WRITE_TOOLS and isinstance(path, str):
                match = OVERVIEW_PATH_RE.search(path)
                if match:
                    yield match.group(1)


def _output_overviews(entries):
    """Overview paths a planner names in its own words: its text and its hand-back message."""
    for entry in entries:
        texts = [message_text(entry)] if entry.get("type") == "assistant" else []
        texts += [tool_input.get("message") for _tid, name, tool_input in tool_uses(entry)
                  if name == "SubagentHandback"]
        for text in texts:
            if isinstance(text, str):
                for match in OVERVIEW_RE.finditer(text):
                    yield match.group(1)


def _strip_bash_heredocs(command):
    """The command without heredoc bodies: each body, from the line after `<<DELIM` through the
    line that is exactly DELIM (tab-indented for `<<-`), or to the end when that line never comes."""
    parts, pos = [], 0
    while True:
        match = BASH_HEREDOC_RE.search(command, pos)
        newline = command.find("\n", match.end()) if match else -1
        if newline < 0:  # no more heredocs, or one without a body
            break
        body = newline + 1
        indent = r"\t*" if match.group(1) else ""
        end = re.compile(r"^" + indent + re.escape(match.group(3)) + r"\r?$", re.MULTILINE).search(command, body)
        parts.append(command[pos:match.start()] + " " + command[match.end():body])
        pos = end.end() if end else len(command)
    parts.append(command[pos:])
    return "".join(parts)


def _strip_powershell_here_strings(command):
    """The command without here-strings: `@'` or `@"` ending a line, through a line starting `'@` or `"@`."""
    return POWERSHELL_HERE_STRING_RE.sub(" ", command)


# per shell tool: how to drop multi-line data, and what a quoted string is
SHELLS = {"Bash": (_strip_bash_heredocs, BASH_QUOTED_RE),
          "PowerShell": (_strip_powershell_here_strings, POWERSHELL_QUOTED_RE)}


def _mask_quotes(command, shell):
    """The command without heredoc bodies and with every quoted string replaced by a token; the
    strings come back in order as (text, closed). Text that only looks like a command then does not
    match. Best effort: heredocs and quotes are handled in separate passes, and comments are not
    parsed, so a contrived command can still expose quoted text. Any slug found must still pass
    SAFE_SLUG_RE, so the worst case is the wrong plan on a run that names no branch."""
    strip_data, quoted_re = SHELLS[shell]
    command = strip_data(command.replace(_MASK, ""))  # a mask character in the input is not a token
    strings = []

    def keep(match):
        closed = any(match.groups())
        strings.append((match.group(0)[1:-1] if closed else match.group(0)[1:], closed))
        return "%s%d%s" % (_MASK, len(strings) - 1, _MASK)

    return quoted_re.sub(keep, command), strings


def _new_branches(entries):
    for entry in entries:
        for _tid, name, tool_input in tool_uses(entry):
            command = tool_input.get("command")
            if name in SHELLS and isinstance(command, str):
                masked, strings = _mask_quotes(command, name)
                for match in NEW_BRANCH_RE.finditer(masked):
                    slug = match.group(1)
                    if slug is None:  # the branch name was quoted
                        index = int(match.group(2))
                        quoted, closed = strings[index] if index < len(strings) else ("", False)
                        if not closed or not quoted.startswith("feature/"):  # unclosed: a syntax error
                            continue
                        slug = quoted[len("feature/"):]
                    yield slug


def derive_slug(window, run_agents):
    """The plan slug of a run whose transcripts name no branch, from the run's own evidence:
    1. a Write of docs/plans/<slug>/00-overview.md (planners first, then any agent, then the
       orchestrator), else a planner's output text naming that file;
    2. else the feature/<slug> branch a `git switch -c` / `git checkout -b` call created.
    Only a slug that is one plain path segment counts. None when nothing qualifies."""
    planners = [a for a in run_agents if a.agent_type == PLANNER]
    others = [a for a in run_agents if a.agent_type != PLANNER]
    sources = [_written_overviews(a.entries) for a in planners]
    sources += [_written_overviews(a.entries) for a in others]
    sources.append(_written_overviews(window))
    sources += [_output_overviews(a.entries) for a in planners]
    sources.append(_new_branches(window))
    sources += [_new_branches(a.entries) for a in run_agents]
    for source in sources:
        for slug in source:
            if _safe(slug):
                return slug
    return None


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


def bug_track(branch):
    """Bug plans (docs/bugs/) belong to fix/ and hotfix/ branches only."""
    return bool(branch) and branch.startswith(("fix/", "hotfix/"))


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
            # transcript text decides these paths: anything outside the repo is ignored before any glob
            if requirements and not inside(repo, requirements):
                requirements = None
            if root and not inside(repo, root):
                root = None
            return requirements, root
    return None, None


def inside(repo, path):
    try:
        real_repo = os.path.normcase(os.path.realpath(repo))
        real_path = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([real_repo, real_path]) == real_repo
    except ValueError:  # different drives on Windows
        return False


def artifact_list(repo, slug, window, bug_track=False):
    """bug_track: list docs/bugs/<slug>*.md too (true only for fix/ and hotfix/ branches)."""
    items = []

    def add(key, label, path):
        if path and os.path.isfile(path) and inside(repo, path):
            items.append({"key": key, "label": label, "path": _rel(repo, path),
                          "kind": os.path.splitext(path)[1].lower().lstrip(".")})

    if slug:
        add("plan-overview", "Plan overview", os.path.join(repo, "docs", "plans", slug, "00-overview.md"))
        for task in plan_tasks(repo, slug):
            add("task-" + task["id"], "Task " + task["id"], os.path.join(repo, task["path"]))
        for number, path in enumerate(bug_plans(repo, slug) if bug_track else [], 1):
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
