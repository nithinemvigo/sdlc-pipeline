"""Tests for pipeline_ui.agents."""
import unittest

import fixture_builder as fb
from pipeline_ui import agents
from pipeline_ui import runs as runs_mod
from pipeline_ui.timeutil import parse_ts

NOW = parse_ts(fb.ts(30))


class AgentStateTest(unittest.TestCase):
    def test_handback_means_finished(self):
        self.assertEqual(agents.agent_state(fb.parsed(fb.finished_agent("a1", 0)), 0, NOW), "finished")

    def test_work_after_handback_is_running_again(self):
        t = fb.finished_agent("a1", 0)
        t.user(5, "One more thing")
        t.tool_use(6, "Read", {}, "tu-x")
        self.assertEqual(agents.agent_state(fb.parsed(t), NOW - 30, NOW), "running")

    def test_without_handback(self):
        t = fb.Transcript(sidechain=True, agent_id="a1")
        t.user(0, "go")
        t.tool_use(1, "Read", {}, "tu-1")
        entries = fb.parsed(t)
        self.assertEqual(agents.agent_state(entries, 0, NOW, notified=True), "finished")
        self.assertEqual(agents.agent_state(entries, NOW - 60, NOW), "running")
        self.assertEqual(agents.agent_state(entries, NOW - 3600, NOW), "interrupted")

    def test_end_turn_is_finished(self):
        t = fb.Transcript(sidechain=True, agent_id="a1")
        t.user(0, "go")
        t.text(1, "All done.")
        self.assertEqual(agents.agent_state(fb.parsed(t), NOW - 3600, NOW), "finished")

    def test_notified_ids(self):
        t = fb.Transcript()
        t.user(0, "<task-notification>\n<task-id>a1</task-id>\n<status>completed</status>\n</task-notification>",
               origin={"kind": "task-notification"})
        t.user(1, "<task-id>a2</task-id> without the notification wrapper")
        self.assertEqual(agents.notified_ids(fb.parsed(t)), {"a1"})


class AgentFieldsTest(unittest.TestCase):
    def test_fields(self):
        t = fb.finished_agent("a1", 3, model="claude-sonnet-5-5", usage=fb.tokens(100, 50), synthetic=True)
        a = agents.Agent("a1", {"agentType": "sdlc-pipeline:planner", "description": "Plan EMI",
                                "toolUseId": "tu-pl", "spawnDepth": 1}, fb.parsed(t), mtime=0, path="p")
        self.assertEqual((a.agent_type, a.description, a.tool_use_id, a.spawn_depth, a.model, a.path),
                         ("planner", "Plan EMI", "tu-pl", 1, "claude-sonnet-5-5", "p"))
        self.assertEqual((a.first_ts, a.last_ts), (fb.ts(3), fb.ts(4)))
        self.assertIn("<synthetic>", a.usage_by_model)
        self.assertIn("tu-a1-2", a.own_tool_use_ids)

    def test_missing_meta(self):
        a = agents.Agent("a2", {}, [], 0)
        self.assertEqual((a.agent_type, a.tool_use_id, a.first_ts, a.model, a.spawn_depth),
                         ("unknown", None, None, None, 1))


class AssignTest(unittest.TestCase):
    def test_by_tool_use_id_parent_and_time(self):
        main = fb.Transcript(session_id="s1")
        main.command(0, "pipeline", "one")
        main.tool_use(1, "Agent", {"subagent_type": "sdlc-pipeline:planner"}, "tu-pl")
        main.command(10, "pipeline", "two")
        main.tool_use(11, "Agent", {}, "tu-cr")
        run1, run2 = runs_mod.find_runs("s1", fb.parsed(main))

        planner = agents.Agent("a-pl", {"agentType": "sdlc-pipeline:planner", "toolUseId": "tu-pl"},
                               fb.parsed(fb.finished_agent("a-pl", 2, spawn="tu-nested")), 0)
        nested = agents.Agent("a-n", {"agentType": "Explore", "toolUseId": "tu-nested", "spawnDepth": 2},
                              fb.parsed(fb.finished_agent("a-n", 3)), 0)
        reviewer = agents.Agent("a-cr", {"agentType": "sdlc-pipeline:code-reviewer", "toolUseId": "tu-cr"},
                                fb.parsed(fb.finished_agent("a-cr", 12)), 0)
        orphan = agents.Agent("a-o", {}, fb.parsed(fb.finished_agent("a-o", 15)), 0)

        by_run = agents.assign_agents([run1, run2], [reviewer, nested, planner, orphan])
        self.assertEqual([a.agent_id for a in by_run[run1.run_id]], ["a-pl", "a-n"])
        self.assertEqual([a.agent_id for a in by_run[run2.run_id]], ["a-cr", "a-o"])
        self.assertEqual(nested.parent_id, "a-pl")
        self.assertIsNone(planner.parent_id)


if __name__ == "__main__":
    unittest.main()
