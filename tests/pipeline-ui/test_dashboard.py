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
