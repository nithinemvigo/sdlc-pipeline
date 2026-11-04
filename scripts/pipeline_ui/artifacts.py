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
