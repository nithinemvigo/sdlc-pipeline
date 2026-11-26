"""Tests for pipeline_dashboard.runs and pipeline_dashboard.checkpoints."""
import unittest

import fixture_builder as fb
from pipeline_dashboard import checkpoints
from pipeline_dashboard import runs as runs_mod

ASK = {"questions": [{"header": "Plan", "question": "Approve the plan?",
                      "options": [{"label": "Approve"}, {"label": "Change"}]}]}


class FindRunsTest(unittest.TestCase):
    def test_two_runs_in_one_session(self):
        t = fb.Transcript(session_id="s1")
        t.command(0, "pipeline-dashboard", "Add calculate_emi\nwith details")
        t.tool_use(1, "Skill", {"skill": "sdlc-pipeline:pipeline-all", "args": "Add calculate_emi"}, "tu-skill")
        t.tool_result(1, "tu-skill", "Launching skill: sdlc-pipeline:pipeline-all")
        t.branch = "feature/calculate-emi"
        t.text(5, "Building.")
        t.branch = "master"
        t.text(6, "Back on master.")
        t.command(10, "pipeline", "")
        first, second = runs_mod.find_runs("s1", fb.parsed(t))
        self.assertEqual((first.command, first.flow, first.title, first.branch, first.superseded),
                         ("pipeline-dashboard", "pipeline-all", "Add calculate_emi", "feature/calculate-emi", True))
        self.assertEqual((second.flow, second.title, second.branch, second.superseded),
                         ("pipeline", "(no request text)", "master", False))
        self.assertEqual(first.run_id, "s1:0")
        self.assertEqual(first.started_at, fb.ts(0))
        self.assertEqual(len(first.entries), 5)

    def test_pipeline_dashboard_before_the_flow_is_chosen(self):
        t = fb.Transcript()
        t.command(0, "pipeline-dashboard", "x")
        [run] = runs_mod.find_runs("s", fb.parsed(t))
        self.assertEqual(run.flow, runs_mod.CHOOSING)

    def test_legacy_pipeline_ui_run_still_shows_with_its_flow(self):
        t = fb.Transcript(session_id="s1")
        t.command(0, "pipeline-ui", "Old name")
        t.tool_use(1, "Skill", {"skill": "sdlc-pipeline:pipeline-parallel", "args": "Old name"}, "tu-skill")
        t.tool_result(1, "tu-skill", "Launching skill: sdlc-pipeline:pipeline-parallel")
        [run] = runs_mod.find_runs("s1", fb.parsed(t))
        self.assertEqual((run.command, run.flow, run.title), ("pipeline-ui", "pipeline-parallel", "Old name"))

    def test_quoted_command_is_not_a_run(self):
        t = fb.Transcript()
        t.command(0, "pipeline", "x")
        t.user(3, "Another Claude session sent a message: <command-name>/sdlc-pipeline:pipeline-all</command-name>")
        t.user(4, "<command-message>x</command-message><command-name>/sdlc-pipeline:pipeline-all</command-name>",
               isMeta=True)
        self.assertEqual(len(runs_mod.find_runs("s", fb.parsed(t))), 1)

    def test_other_commands_and_sidechains_ignored(self):
        t = fb.Transcript()
        t.command(0, "verify-acceptance", "")
        side = fb.Transcript(sidechain=True)
        side.command(1, "pipeline", "")
        self.assertEqual(runs_mod.find_runs("s", fb.parsed(t) + fb.parsed(side)), [])


class CheckpointsTest(unittest.TestCase):
    def test_answer_from_tool_result(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_result(1, "q1", 'User has answered your questions: "Approve the plan?"="Approve". '
                               "You can now continue with the user's answers in mind.")
        [cp] = checkpoints.find_checkpoints(fb.parsed(t))
        self.assertEqual(cp["answer"], "Approve")
        self.assertFalse(cp["pending"])
        self.assertFalse(cp["answered_in_chat"])
        self.assertEqual(cp["questions"], [{"header": "Plan", "question": "Approve the plan?",
                                            "options": ["Approve", "Change"]}])
        self.assertEqual(cp["time"], fb.ts(0))

    def test_answer_typed_in_chat_after_an_error_result(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_result(0, "q1", "Tool result missing due to internal error", is_error=True)
        t.user(1, "<task-notification>\n<task-id>a1</task-id>", origin={"kind": "task-notification"})
        t.user(2, "<system-reminder>ctx</system-reminder>Approve it")
        [cp] = checkpoints.find_checkpoints(fb.parsed(t))
        self.assertEqual(cp["answer"], "Approve it")
        self.assertTrue(cp["answered_in_chat"])
        self.assertFalse(cp["pending"])

    def test_pending(self):
        t = fb.Transcript()
        t.tool_use(0, "AskUserQuestion", ASK, "q1")
        t.tool_use(1, "AskUserQuestion", ASK, "q2")
        t.tool_result(1, "q2", "Tool result missing due to internal error", is_error=True)
        self.assertEqual([cp["pending"] for cp in checkpoints.find_checkpoints(fb.parsed(t))], [True, True])

    def test_unrecognised_result_text_kept(self):
        self.assertEqual(checkpoints.answer_text("  The user declined.  "), "The user declined.")
        self.assertEqual(checkpoints.answer_text('"A?"="x". "B?"="y".'), "x; y")


if __name__ == "__main__":
    unittest.main()
