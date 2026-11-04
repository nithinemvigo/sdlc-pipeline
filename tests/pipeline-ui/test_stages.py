"""Tests for pipeline_ui.stages and pipeline_ui.status."""
import os
import unittest

import fixture_builder as fb
from pipeline_ui import agents, stages, status
from pipeline_ui import runs as runs_mod
from pipeline_ui.timeutil import parse_ts

NOW = parse_ts(fb.ts(30))
AGENTS_DIR = os.path.join(fb.REPO_ROOT, "agents")


def make(agent_id, agent_type, minute, state="finished"):
    agent_kind = agent_type if agent_type == "general-purpose" else "sdlc-pipeline:" + agent_type
    agent = agents.Agent(agent_id, {"agentType": agent_kind}, fb.parsed(fb.finished_agent(agent_id, minute)), 0)
    agent.status = state
    return agent


class PlaceTest(unittest.TestCase):
    def test_mapping_fix_round_and_other(self):
        seq = [make("a1", "requirements-writer", 1), make("a2", "planner", 2), make("a3", "implementer", 3),
               make("a4", "acceptance-verifier", 5), make("a5", "implementer", 7), make("a6", "general-purpose", 8)]
        stages.place_agents(seq)
        self.assertEqual([(a.stage, a.fix, a.other) for a in seq],
                         [("R", False, False), ("1", False, False), ("3", False, False),
                          ("5.85", False, False), ("5.85", True, False), ("5.85", False, True)])

    def test_every_plugin_agent_has_a_stage(self):
        names = [f[:-3] for f in os.listdir(AGENTS_DIR) if f.endswith(".md")]
        self.assertTrue(names)
        for name in names:
            self.assertIn(name, stages.AGENT_STAGE, name)


class BuildStagesTest(unittest.TestCase):
    def states(self, flow, seq, run_status):
        stages.place_agents(seq)
        return dict((s["key"], s["state"]) for s in stages.build_stages(flow, seq, run_status))

    def test_waiting_at_plan_approval(self):
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "ceo-reviewer", 2),
                                       make("a3", "eng-reviewer", 2)], "waiting")
        self.assertEqual((out["0.8"], out["1"], out["2"], out["3"]), ("skipped", "done", "done", "not reached"))
        self.assertNotIn("1-B", out)

    def test_in_progress(self):
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "implementer", 3, "running")], "running")
        self.assertEqual((out["1"], out["3"]), ("done", "in progress"))
        out = self.states("pipeline", [make("a1", "planner", 1), make("a2", "implementer", 3)], "running")
        self.assertEqual(out["3"], "in progress")

    def test_bug_track_shows_investigate_not_plan(self):
        out = self.states("pipeline", [make("a1", "investigator", 1)], "running")
        self.assertIn("1-B", out)
        self.assertNotIn("1", out)

    def test_pipeline_all_stage_list(self):
        keys = [s["key"] for s in stages.build_stages("pipeline-all", [], "running")]
        self.assertEqual(keys, stages.FLOW_STAGES["pipeline-all"])


class StatusTest(unittest.TestCase):
    def run_of(self, t):
        return runs_mod.find_runs("s", fb.parsed(t))[0]

    def base(self):
        t = fb.Transcript()
        t.command(0, "pipeline", "x")
        return t

    def test_finished_when_ship_pr_finished(self):
        self.assertEqual(status.run_status(self.run_of(self.base()), [make("a", "ship-pr", 1)], [], 0, NOW),
                         ("finished", None))

    def test_superseded_run_is_stopped(self):
        t = self.base()
        t.command(5, "pipeline", "y")
        self.assertEqual(status.run_status(runs_mod.find_runs("s", fb.parsed(t))[0], [], [], NOW, NOW),
                         ("stopped", None))

    def test_pending_question_waits(self):
        cps = [{"pending": True, "time": fb.ts(5)}]
        self.assertEqual(status.run_status(self.run_of(self.base()), [], cps, NOW, NOW),
                         ("waiting", parse_ts(fb.ts(5))))

    def test_running_agent_wins_over_ended_turn(self):
        t = self.base()
        t.text(1, "Dispatched the planner.")
        self.assertEqual(status.run_status(self.run_of(t), [make("a", "planner", 1, "running")], [], 0, NOW),
                         ("running", None))

    def test_recent_activity_mid_turn(self):
        t = self.base()
        t.tool_use(1, "Bash", {}, "tu")
        self.assertEqual(status.run_status(self.run_of(t), [], [], NOW - 30, NOW), ("running", None))
        self.assertEqual(status.run_status(self.run_of(t), [], [], NOW - 600, NOW), ("stopped", None))

    def test_ended_turn_waits(self):
        t = self.base()
        t.text(1, "Type Continue now.")
        self.assertEqual(status.run_status(self.run_of(t), [], [], 0, NOW), ("waiting", parse_ts(fb.ts(1))))


if __name__ == "__main__":
    unittest.main()
