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
