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


def branch_exists(repo, branch):
    """True when refs/heads/<branch> exists. An empty or option-like name is never looked up."""
    if not branch or branch.startswith("-"):
        return False
    return git(repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch) is not None


def branch_commits(repo, branch, base):
    """Commits on branch since it left base, oldest first."""
    if not branch or not base or branch == base or branch.startswith("-"):
        return []
    merge_base = git(repo, "merge-base", base, branch)
    if merge_base is None:
        return []
    out = git(repo, "log", "--reverse", "--format=%H%x09%aI%x09%s", "%s..%s" % (merge_base.strip(), branch), "--")
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
    out = git(repo, "show", "--stat", "--patch", "--no-color", "--no-ext-diff", "--no-textconv", sha, timeout=30)
    if out is None:
        return None
    if len(out) > DIFF_LIMIT:
        return out[:DIFF_LIMIT] + "\n\n[truncated at 1 MB]\n"
    return out
