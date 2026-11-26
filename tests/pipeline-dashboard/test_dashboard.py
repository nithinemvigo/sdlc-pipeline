"""Tests for pipeline_dashboard.dashboard against the EMI-shaped fixture."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fixture_builder as fb
from pipeline_dashboard import agents as agents_mod
from pipeline_dashboard import gitinfo, usage
from pipeline_dashboard import runs as runs_mod
from pipeline_dashboard.dashboard import Dashboard
from pipeline_dashboard.timeutil import parse_ts


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
                         (self.ids["run1"], "pipeline-dashboard", "pipeline-all",
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
        self.assertEqual(d["warnings"], ["1 line could not be read · Claude Code 2.1.312"])

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
        with mock.patch("pipeline_dashboard.artifacts.artifact_list", side_effect=RuntimeError("boom")):
            d = self.dash.run(self.ids["run1"])
        self.assertIsNone(d["artifacts"])
        self.assertEqual(d["errors"], {"artifacts": "RuntimeError: boom"})
        self.assertTrue(d["stages"])

    def test_empty_project(self):
        other = os.path.join(self.tmp, "empty")
        os.makedirs(other, exist_ok=True)
        data = Dashboard(other, cfg=os.path.join(self.tmp, "nocfg")).runs()
        self.assertEqual(data, {"project": os.path.abspath(other), "folders": [], "runs": []})


def _session(session_id, branch, minute, version="2.1.312", name="pipeline", args="Do it"):
    t = fb.Transcript(session_id=session_id, cwd="C:/plain", branch=branch, version=version)
    t.command(minute, name, args)
    return t


class DashboardRobustnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.cfg = os.path.join(cls.tmp, "cfg")
        cls.ids = fb.emi_like(cls.cfg, cls.repo)
        fb.write_session(cls.cfg, cls.repo, _session("sess-bad", "master", 60))
        cls.now = parse_ts(fb.ts(70))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def dash(self):
        return Dashboard(self.repo, cfg=self.cfg, prices=usage.load_prices(), clock=lambda: self.now)

    def _find_runs_failing_for_bad(self):
        real = runs_mod.find_runs

        def find_runs(session_id, entries):
            if session_id == "sess-bad":
                raise ValueError("corrupt")
            return real(session_id, entries)
        return mock.patch("pipeline_dashboard.runs.find_runs", side_effect=find_runs)

    def test_one_unreadable_subagent_is_skipped_and_reported(self):
        real = agents_mod.Agent

        def agent(agent_id, *args, **kwargs):
            if agent_id == "a-pl":
                raise RuntimeError("bad agent")
            return real(agent_id, *args, **kwargs)
        with mock.patch("pipeline_dashboard.agents.Agent", side_effect=agent):
            dash = self.dash()
            by_id = dict((r["id"], r) for r in dash.runs()["runs"])
            detail = dash.run(self.ids["run1"])
        message = "1 subagent file(s) could not be read: a-pl: RuntimeError: bad agent"
        self.assertEqual(by_id[self.ids["run1"]]["errors"], {"agents": message})
        self.assertEqual(by_id[self.ids["run2"]]["errors"], {"agents": message})
        self.assertEqual(by_id[self.ids["run1"]]["status"], "finished")
        rows = dict((r["id"], r) for r in detail["agents"])
        self.assertEqual(len(rows), 14)  # the other agents and the orchestrator are kept
        self.assertNotIn("a-pl", rows)
        self.assertEqual(detail["errors"], {"agents": message})
        self.assertTrue(detail["stages"])

    def test_unreadable_session_becomes_a_placeholder(self):
        with self._find_runs_failing_for_bad():
            dash = self.dash()
            data = dash.runs()
            ids = [r["id"] for r in data["runs"]]
            self.assertEqual(sorted(ids), sorted([self.ids["run1"], self.ids["run2"], "sess-bad:error"]))
            self.assertEqual(ids[-1], "sess-bad:error")  # started None sorts last
            placeholder = data["runs"][-1]
            self.assertEqual(placeholder, {
                "id": "sess-bad:error", "session": "sess-bad", "command": None, "flow": "",
                "title": "Could not read session sess-bad", "branch": "", "started": None, "status": "error",
                "waiting_since": None, "duration_s": None, "tokens": usage.Usage().to_dict(), "cost": None,
                "cost_complete": False, "linked": [], "resumed_from": None,
                "errors": {"session": "ValueError: corrupt"}})
            run1 = [r for r in data["runs"] if r["id"] == self.ids["run1"]][0]
            self.assertEqual((run1["status"], run1["flow"]), ("finished", "pipeline-all"))
            self.assertEqual(dash.run("sess-bad:error"), placeholder)
            self.assertIsNone(dash.diff("sess-bad:error", "abc"))
            self.assertIsNone(dash.file("sess-bad:error", "plan-overview"))
            self.assertTrue(dash.run(self.ids["run1"])["stages"])

    def test_failing_agent_assignment_builds_runs_without_agents(self):
        with mock.patch("pipeline_dashboard.agents.assign_agents", side_effect=RuntimeError("nope")):
            dash = self.dash()
            summary = [r for r in dash.runs()["runs"] if r["id"] == self.ids["run1"]][0]
            detail = dash.run(self.ids["run1"])
        self.assertEqual(summary["errors"], {"agents": "RuntimeError: nope"})
        self.assertEqual([r["id"] for r in detail["agents"]], ["orchestrator"])
        self.assertEqual(detail["errors"], {"agents": "RuntimeError: nope"})
        self.assertTrue(detail["stages"])


class DashboardScenarioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "cfg")
        self.plain = os.path.join(self.tmp, "plain")
        os.makedirs(self.plain)
        self.now = parse_ts(fb.ts(90))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def dash(self, repo=None):
        return Dashboard(repo or self.plain, cfg=self.cfg, prices=usage.load_prices(), clock=lambda: self.now)

    def test_runs_on_the_same_branch_are_linked(self):
        for session_id, branch, minute in (("s-a", "feature/calculate-emi", 0), ("s-b", "feature/calculate-emi", 10),
                                           ("s-c", "master", 20)):
            fb.write_session(self.cfg, self.plain, _session(session_id, branch, minute))
        by_session = dict((r["session"], r) for r in self.dash().runs()["runs"])
        first, second, base = by_session["s-a"], by_session["s-b"], by_session["s-c"]
        self.assertEqual((first["resumed_from"], first["linked"]), (None, [second["id"]]))
        self.assertEqual((second["resumed_from"], second["linked"]), (first["id"], [first["id"]]))
        self.assertEqual((base["resumed_from"], base["linked"]), (None, []))

    def test_an_empty_folder_list_is_retried(self):
        dash = self.dash()
        self.assertEqual(dash.runs(), {"project": os.path.abspath(self.plain), "folders": [], "runs": []})
        fb.write_session(self.cfg, self.plain, _session("s-late", "feature/x", 0))
        data = dash.runs()
        self.assertEqual(data["folders"], [fb.project_folder(self.cfg, self.plain)])
        self.assertEqual([r["session"] for r in data["runs"]], ["s-late"])

    def test_without_git_the_tasks_say_so(self):
        fb.write_session(self.cfg, self.plain, _session("s-nogit", "feature/x", 0))
        dash = self.dash()
        tasks = dash.run(dash.runs()["runs"][0]["id"])["tasks"]
        self.assertFalse(tasks["git"])
        self.assertEqual((tasks["tasks"], tasks["other_commits"]), ([], []))

    def test_git_results_are_cached_for_five_seconds(self):
        repo = fb.make_git_repo(os.path.join(self.tmp, "repo"))
        fb.write_session(self.cfg, repo, _session("s-git", "feature/calculate-emi", 0))
        dash = self.dash(repo)
        run_id = dash.runs()["runs"][0]["id"]

        def commit_count():
            tasks = dash.run(run_id)["tasks"]
            return sum(len(t["commits"]) for t in tasks["tasks"]) + len(tasks["other_commits"])
        with mock.patch("pipeline_dashboard.dashboard.time.monotonic") as clock:
            clock.return_value = 1000.0
            self.assertEqual(commit_count(), 5)
            fb.write_file(repo, "extra.py", "e = 1\n")
            fb.git(repo, "add", "-A")
            fb.git(repo, "commit", "-q", "-m", "feat: extra")
            clock.return_value = 1004.0
            self.assertEqual(commit_count(), 5)  # still inside the 5 s window
            clock.return_value = 1006.0
            self.assertEqual(commit_count(), 6)

    def test_warning_without_a_version(self):
        t = _session("s-nover", "master", 0, version=None)
        t.raw("{not json")
        fb.write_session(self.cfg, self.plain, t)
        dash = self.dash()
        d = dash.run(dash.runs()["runs"][0]["id"])
        self.assertEqual(d["warnings"], ["1 line could not be read \u00b7 Claude Code version unknown"])


if __name__ == "__main__":
    unittest.main()
