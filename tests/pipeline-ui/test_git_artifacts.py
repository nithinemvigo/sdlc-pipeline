"""Tests for pipeline_ui.gitinfo and pipeline_ui.artifacts."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import fixture_builder as fb
from pipeline_ui import artifacts, dashboard, gitinfo

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

    def test_git_calls_are_hardened(self):
        calls = []
        real = gitinfo.git

        def record(repo, *args, **kwargs):
            calls.append(args)
            return real(repo, *args, **kwargs)

        with mock.patch.object(gitinfo, "git", side_effect=record):
            commits = gitinfo.branch_commits(self.repo, BRANCH, "master")
            self.assertEqual(len(commits), 5)
            self.assertIn("emi.py", gitinfo.commit_diff(self.repo, commits[1]["sha"]))
        log = [c for c in calls if c[0] == "log"][0]
        self.assertEqual(log[-1], "--")  # the range can never be read as a path
        show = [c for c in calls if c[0] == "show"][0]
        self.assertIn("--no-textconv", show)
        self.assertLess(show.index("--no-textconv"), show.index(commits[1]["sha"]))

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
        keys = [i["key"] for i in artifacts.artifact_list(self.repo, "rounding", [], bug_track=True)]
        self.assertEqual(keys, ["bug-1"])

    def test_bug_plans_only_on_the_bug_track(self):
        self.assertTrue(artifacts.bug_track("fix/rounding"))
        self.assertTrue(artifacts.bug_track("hotfix/rounding"))
        self.assertFalse(artifacts.bug_track("feature/rounding"))
        self.assertFalse(artifacts.bug_track(None))
        self.assertEqual(artifacts.artifact_list(self.repo, "rounding", []), [])
        board = dashboard.Dashboard(self.repo, cfg=os.path.join(self.tmp, "cfg"), prices={})
        self.assertEqual(board._tasks("feature/rounding")["bug_plans"], [])
        self.assertEqual(board._tasks("fix/rounding")["bug_plans"], ["docs/bugs/rounding-mini-plan.md"])

    def test_ba_folders_outside_the_repo_are_ignored(self):
        top = "C:/" if os.name == "nt" else "/"
        with mock.patch("pipeline_ui.artifacts.glob.glob") as fake_glob:
            self.assertEqual(artifacts.ba_paths(self.repo, self.window("--artifact-root " + top)), (None, None))
            self.assertEqual(artifacts.artifact_list(self.repo, None, self.window("--artifact-root " + top)), [])
            outside = self.window("--requirements ../outside.md")
            self.assertEqual(artifacts.ba_paths(self.repo, outside), (None, None))
            self.assertEqual(artifacts.artifact_list(self.repo, None, outside), [])
            requirements, root = artifacts.ba_paths(
                self.repo, self.window("--requirements docs/features/calculate-emi.requirements.md --artifact-root " + top))
            self.assertTrue(requirements.endswith("calculate-emi.requirements.md"))
            self.assertIsNone(root)
            fake_glob.assert_not_called()

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
