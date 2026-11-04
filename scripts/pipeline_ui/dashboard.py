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
        return ["%d line%s could not be read · Claude Code %s"
                % (bad, "" if bad == 1 else "s", ", ".join(versions) or "version unknown")]
