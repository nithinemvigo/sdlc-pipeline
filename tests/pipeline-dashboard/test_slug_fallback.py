"""A run whose transcripts carry no branch: the plan slug comes from the run's own evidence."""
import os
import shutil
import tempfile
import time
import unittest

import fixture_builder as fb
from pipeline_dashboard import agents as agents_mod
from pipeline_dashboard import artifacts, gitinfo, usage
from pipeline_dashboard.dashboard import Dashboard
from pipeline_dashboard.timeutil import parse_ts


NL, TAB, BS = chr(10), chr(9), chr(92)


def _agent(agent_type, transcript):
    return agents_mod.Agent(transcript.agent_id, {"agentType": "sdlc-pipeline:" + agent_type},
                            fb.parsed(transcript), 0.0)


def _sub(agent_id="ag-1"):
    return fb.Transcript(branch="HEAD", sidechain=True, agent_id=agent_id)


def _bash(command, tool="Bash"):
    t = fb.Transcript(branch="HEAD")
    t.tool_use(1, tool, {"command": command}, "tu-b")
    return fb.parsed(t)


class DeriveSlugTest(unittest.TestCase):
    def test_planner_write_of_the_overview(self):
        t = _sub()
        t.tool_use(1, "Write", {"file_path": "C:\\repo\\docs\\plans\\calculate-emi\\00-overview.md"}, "tu-w")
        self.assertEqual(artifacts.derive_slug([], [_agent("planner", t)]), "calculate-emi")

    def test_write_by_any_agent_or_the_orchestrator(self):
        t = _sub()
        t.tool_use(1, "Write", {"file_path": "/repo/docs/plans/add-login/00-overview.md"}, "tu-w")
        self.assertEqual(artifacts.derive_slug([], [_agent("implementer", t)]), "add-login")
        main = fb.Transcript(branch="HEAD")
        main.tool_use(1, "Write", {"file_path": "docs/plans/add-login/00-overview.md"}, "tu-w")
        self.assertEqual(artifacts.derive_slug(fb.parsed(main), []), "add-login")

    def test_planner_output_text(self):
        t = _sub()
        t.tool_use(1, "Read", {"file_path": "docs/plans/old-plan/00-overview.md"}, "tu-r")  # a read is not output
        t.tool_use(2, "SubagentHandback", {"message": "Plan at docs/plans/calculate-emi/00-overview.md."}, "tu-h")
        self.assertEqual(artifacts.derive_slug([], [_agent("planner", t)]), "calculate-emi")
        other = _sub("ag-2")
        other.text(1, "See docs/plans/elsewhere/00-overview.md")  # only a planner's text counts
        self.assertIsNone(artifacts.derive_slug([], [_agent("code-reviewer", other)]))

    def test_a_write_wins_over_planner_text_and_a_branch_command(self):
        t = _sub()
        t.text(1, "Like docs/plans/older/00-overview.md")
        t.tool_use(2, "Write", {"file_path": "docs/plans/calculate-emi/00-overview.md"}, "tu-w")
        window = _bash("git checkout -b feature/something-else")
        self.assertEqual(artifacts.derive_slug(window, [_agent("planner", t)]), "calculate-emi")

    def test_other_plan_files_do_not_count(self):
        t = _sub()
        t.tool_use(1, "Write", {"file_path": "docs/plans/calculate-emi/task-01-x.md"}, "tu-w")
        t.tool_use(2, "Edit", {"file_path": "docs/plans/calculate-emi/00-overview.md"}, "tu-e")
        self.assertIsNone(artifacts.derive_slug([], [_agent("planner", t)]))

    def test_branch_command(self):
        for command in ("git checkout -q -b feature/calculate-emi",
                        "cd x\ngit add -A && git switch -c feature/calculate-emi",
                        "git switch --create 'feature/calculate-emi'",
                        "git -C /r checkout -B \"feature/calculate-emi\"",
                        "git checkout -b feature/calculate-emi master; git status"):
            self.assertEqual(artifacts.derive_slug(_bash(command), []), "calculate-emi", command)
        self.assertEqual(artifacts.derive_slug(_bash("git switch -c feature/x", tool="PowerShell"), []), "x")

    def test_branch_command_in_an_agent(self):
        t = _sub()
        t.tool_use(1, "Bash", {"command": "git checkout -b feature/calculate-emi"}, "tu-b")
        self.assertEqual(artifacts.derive_slug([], [_agent("implementer", t)]), "calculate-emi")

    def test_commands_that_do_not_name_a_new_feature_branch(self):
        for command in ("git init -q -b master", "git checkout feature/calculate-emi",
                        "git checkout -b fix/rounding", "git switch -c feature/../evil",
                        "git switch -c feature/-x", "git status && echo -b feature/x"):
            self.assertIsNone(artifacts.derive_slug(_bash(command), []), command)

    def test_text_that_only_looks_like_a_branch_command(self):
        heredoc = NL.join(["git commit -F - <<'EOF'", "fix: stuff", "git switch -c feature/from-heredoc", "EOF"])
        dashed = NL.join(["cat <<-END", TAB + "git checkout -b feature/dash", TAB + "END"])
        quoted = NL.join(["echo 'a", "git switch -c feature/in-quotes'"])
        for command in ('echo "next: ; git checkout -b feature/quoted"', quoted, heredoc, dashed):
            self.assertIsNone(artifacts.derive_slug(_bash(command), []), command)
        after = NL.join([heredoc, "git switch -c feature/real"])
        self.assertEqual(artifacts.derive_slug(_bash(after), []), "real")

    def test_branch_command_with_global_git_options(self):
        for command, slug in (('git -C "C:/a b" switch -c feature/x', "x"),
                              ("git --no-pager checkout -b feature/y", "y"),
                              ("git switch --create=feature/z", "z"),
                              ("git -c user.name=a -C /r --git-dir=/r/.git switch -c feature/w", "w"),
                              ("git -C C:" + BS + "a" + BS + "b checkout -B feature/win", "win")):
            self.assertEqual(artifacts.derive_slug(_bash(command), []), slug, command)

    def test_overview_path_must_end_with_the_file_name(self):
        t = _sub()
        t.tool_use(1, "Write", {"file_path": "docs/plans/calculate-emi/00-overview.md.bak"}, "tu-w")
        self.assertIsNone(artifacts.derive_slug([], [_agent("planner", t)]))
        self.assertIsNone(artifacts.SAFE_SLUG_RE.match("ok" + NL))

    def test_unsafe_slugs_are_ignored(self):
        for path in ("docs/plans/../00-overview.md", "docs/plans/-x/00-overview.md",
                     "docs/plans/a b/00-overview.md", "docs/plans/../../x/00-overview.md"):
            t = _sub()
            t.tool_use(1, "Write", {"file_path": path}, "tu-w")
            self.assertIsNone(artifacts.derive_slug([], [_agent("planner", t)]), path)

    def test_no_evidence(self):
        self.assertIsNone(artifacts.derive_slug(_bash("git status"), []))


def _derive(command, tool="Bash"):
    return artifacts.derive_slug(_bash(command, tool=tool), [])


class ShellParsingTest(unittest.TestCase):
    """The branch fallback reads each command with its own shell's quote and heredoc rules."""

    def test_powershell_quotes(self):
        repo = '"C:' + BS + 'repo' + BS + '"'  # a trailing backslash does not escape in PowerShell
        for command, slug in (("git -C " + repo + ' switch -c feature/ps2; echo "x"', "ps2"),
                              ("Set-Location " + repo + '; git switch -c feature/ps; Write-Output "done"', "ps"),
                              ('echo "a `" b"; git switch -c feature/bt', "bt"),
                              ("echo 'it''s'; git switch -c feature/psq", "psq"),
                              ("git switch -c 'feature/sq'", "sq")):
            self.assertEqual(_derive(command, "PowerShell"), slug, command)

    def test_powershell_here_strings_are_data(self):
        single = NL.join(["$m = @'", "don't", "git switch -c feature/hs2", "'@"])
        double = NL.join(['$m = @"', 'he said "hi', "git switch -c feature/hs", '"@'])
        for command in (single, double):
            self.assertIsNone(_derive(command, "PowerShell"), command)
            after = NL.join([command + " | Out-File x", "git switch -c feature/real"])
            self.assertEqual(_derive(after, "PowerShell"), "real", after)

    def test_an_unclosed_quote_runs_to_the_end(self):
        self.assertIsNone(_derive('echo "abc' + NL + "git switch -c feature/unq"))
        self.assertIsNone(_derive("echo 'abc" + NL + "git switch -c feature/unq", "PowerShell"))

    def test_unclosed_quotes_take_linear_time(self):
        for tool, command in (("Bash", 'echo "' + (BS + '"') * 20000),
                              ("Bash", 'echo "' + (BS + '"') * 20000 + BS),
                              ("PowerShell", 'echo "' + '`"' * 20000),
                              ("PowerShell", 'echo "' + '`"' * 20000 + "`")):
            started = time.time()
            self.assertIsNone(_derive(command, tool))
            self.assertLess(time.time() - started, 1.0, "%s, %d characters" % (tool, len(command)))

    def test_claude_commit_heredoc_inside_a_quoted_subshell(self):
        command = NL.join(['git commit -m "$(cat <<' + "'EOF'", "fix: it's",
                           "git switch -c feature/hd", "EOF", ')" && git switch -c feature/ok'])
        self.assertEqual(_derive(command), "ok")

    def test_heredoc_delimiter_with_a_dash(self):
        self.assertIsNone(_derive(NL.join(["cat <<'END-MSG'", "git switch -c feature/dd", "END-MSG", ""])))

    def test_heredoc_delimiter_escaped_with_a_backslash(self):
        self.assertIsNone(_derive(NL.join(["cat <<" + BS + "EOF", "git switch -c feature/bs", "EOF", ""])))

    def test_here_string_is_not_a_heredoc(self):
        self.assertEqual(_derive(NL.join(['grep x <<< "y"', "git switch -c feature/hstr"])), "hstr")

    def test_bit_shift_is_not_a_heredoc(self):
        self.assertEqual(_derive(NL.join(["echo $((1<<2))", "git switch -c feature/shift"])), "shift")

    def test_plain_heredoc_ends_only_at_the_exact_delimiter(self):
        for line in ("  EOF", TAB + "EOF", "EOF "):
            command = NL.join(["cat <<EOF", line, "git switch -c feature/early", "EOF"])
            self.assertIsNone(_derive(command), command)

    def test_dash_heredoc_ends_at_a_tab_indented_delimiter_only(self):
        spaced = NL.join(["cat <<-END", "  END", "git switch -c feature/sp", TAB + TAB + "END"])
        self.assertIsNone(_derive(spaced))
        self.assertEqual(_derive(NL.join([spaced, "git switch -c feature/after"])), "after")

    def test_an_unclosed_heredoc_runs_to_the_end(self):
        self.assertIsNone(_derive(NL.join(["cat <<EOF", "git switch -c feature/unterm"])))

    def test_mask_character_in_the_command(self):
        mask = chr(0xE000)
        self.assertIsNone(_derive("git switch -c " + mask + "7" + mask))
        self.assertIsNone(_derive("echo 'feature/forged'; git switch -c " + mask + "0" + mask))
        self.assertIsNone(_derive("echo 'feature/forged'; git switch -c " + mask + "0" + mask, "PowerShell"))

    def test_short_options(self):
        for command in ("git checkout -b=feature/eq", "git switch -c=feature/eq",
                        "git switch -b feature/x", "git checkout -c feature/x"):
            self.assertIsNone(_derive(command), command)
        for command, slug in (("git switch -C feature/fc", "fc"),
                              ("git switch --force-create=feature/ff", "ff")):
            self.assertEqual(_derive(command), slug, command)

    def test_command_after_a_shell_keyword_or_brace(self):
        for command, slug in (("if true; then git switch -c feature/th; fi", "th"),
                              ("for x in a; do git switch -c feature/lp; done", "lp"),
                              ("{ git switch -c feature/br; }", "br"),
                              ("git fetch && git switch -c feature/and", "and")):
            self.assertEqual(_derive(command), slug, command)
        self.assertIsNone(_derive("echo then git switch -c feature/no"))


class NoBranchDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.prices = usage.load_prices()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def board(self, name, **kw):
        cfg = os.path.join(self.tmp, name)
        run_id = fb.no_branch_run(cfg, self.repo, **kw)
        now = parse_ts(fb.ts(56))
        return Dashboard(self.repo, cfg=cfg, prices=self.prices, clock=lambda: now), run_id

    def test_branch_exists(self):
        self.assertTrue(gitinfo.branch_exists(self.repo, "feature/calculate-emi"))
        self.assertFalse(gitinfo.branch_exists(self.repo, "feature/nope"))
        self.assertFalse(gitinfo.branch_exists(self.repo, "-x"))
        self.assertFalse(gitinfo.branch_exists(self.repo, ""))

    def test_plan_tasks_and_commits_from_the_planner_write(self):
        dash, run_id = self.board("cfg-write", checkout=False)
        summary = dash.runs()["runs"][0]
        self.assertEqual((summary["id"], summary["branch"]), (run_id, "feature/calculate-emi"))
        d = dash.run(run_id)
        self.assertEqual(d["branch"], "feature/calculate-emi")
        tasks = d["tasks"]
        self.assertEqual(tasks["slug"], "calculate-emi")
        self.assertEqual([(t["id"], [c["subject"] for c in t["commits"]]) for t in tasks["tasks"]],
                         [("01", ["feat: task 01 scaffolding"]), ("02", ["feat(Task-02): validation"]),
                          ("03", ["feat: implement task 3 calculation"])])
        self.assertEqual([a["key"] for a in d["artifacts"]][:4], ["plan-overview", "task-01", "task-02", "task-03"])
        good = tasks["tasks"][0]["commits"][0]["sha"]
        self.assertIn("emi.py", dash.diff(run_id, good))
        self.assertTrue(dash.file(run_id, "plan-overview")[0].endswith("00-overview.md"))

    def test_branch_command_when_no_plan_was_written(self):
        dash, run_id = self.board("cfg-checkout", planner_write=False)
        tasks = dash.run(run_id)["tasks"]
        self.assertEqual((tasks["slug"], len(tasks["tasks"]), len(tasks["tasks"][2]["commits"])),
                         ("calculate-emi", 3, 1))

    def test_slug_without_a_git_branch_shows_the_plan_only(self):
        fb.write_file(self.repo, "docs/plans/orphan/00-overview.md", "# Plan\n")
        fb.write_file(self.repo, "docs/plans/orphan/task-01-only.md", "# Task 01\n")
        try:
            dash, run_id = self.board("cfg-orphan", slug="orphan", checkout=False)
            d = dash.run(run_id)
            self.assertEqual(d["branch"], "")
            self.assertEqual(d["tasks"]["slug"], "orphan")
            self.assertEqual([(t["id"], t["commits"]) for t in d["tasks"]["tasks"]], [("01", [])])
            self.assertEqual(d["tasks"]["other_commits"], [])
            keys = [a["key"] for a in d["artifacts"]]  # the plan files are still artifacts
            self.assertIn("plan-overview", keys)
            self.assertIn("task-01", keys)
        finally:
            shutil.rmtree(os.path.join(self.repo, "docs", "plans", "orphan"), ignore_errors=True)

    def test_branchless_runs_deriving_the_same_branch_are_linked(self):
        # the session whose file name sorts last started first: the order must come from start times
        cfg = os.path.join(self.tmp, "cfg-link")
        first = fb.no_branch_run(cfg, self.repo, session_id="sess-l2", checkout=False, start=46)
        second = fb.no_branch_run(cfg, self.repo, session_id="sess-l1", checkout=False, start=48)
        now = parse_ts(fb.ts(58))
        dash = Dashboard(self.repo, cfg=cfg, prices=self.prices, clock=lambda: now)
        by_id = dict((r["id"], r) for r in dash.runs()["runs"])
        self.assertEqual(set(by_id), {first, second})
        self.assertEqual(set(r["branch"] for r in by_id.values()), {"feature/calculate-emi"})
        a, b = by_id[first], by_id[second]
        self.assertEqual((a["resumed_from"], a["linked"]), (None, [second]))
        self.assertEqual((b["resumed_from"], b["linked"]), (first, [first]))

    def test_derived_slug_cache_sees_a_planner_write_that_arrives_later(self):
        cfg = os.path.join(self.tmp, "cfg-late")
        run_id = fb.no_branch_run(cfg, self.repo, session_id="sess-late", planner_write=False, checkout=False)
        now = parse_ts(fb.ts(56))
        dash = Dashboard(self.repo, cfg=cfg, prices=self.prices, clock=lambda: now)
        self.assertEqual(dash.runs()["runs"][0]["branch"], "")
        self.assertEqual(dash.run(run_id)["tasks"]["slug"], None)
        late = fb.Transcript(session_id="sess-late", cwd=self.repo, branch="HEAD", sidechain=True, agent_id="nb-pl")
        overview = os.path.join(self.repo, "docs", "plans", "calculate-emi", "00-overview.md")
        late.tool_use(52, "Write", {"file_path": overview, "content": "x"}, "tu-late-w")
        path = os.path.join(fb.project_folder(cfg, self.repo), "sess-late", "subagents", "agent-nb-pl.jsonl")
        with open(path, "a", encoding="utf-8", newline="") as fh:  # the planner's Write arrives later
            fh.write(late.lines[-1] + NL)
        d = dash.run(run_id)
        self.assertEqual((d["branch"], d["tasks"]["slug"]), ("feature/calculate-emi", "calculate-emi"))

    def test_no_evidence_keeps_todays_behaviour(self):
        dash, run_id = self.board("cfg-none", planner_write=False, checkout=False)
        d = dash.run(run_id)
        self.assertEqual((d["branch"], d["tasks"]["slug"], d["tasks"]["tasks"]), ("", None, []))


if __name__ == "__main__":
    unittest.main()
