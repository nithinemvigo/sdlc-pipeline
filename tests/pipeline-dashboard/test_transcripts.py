"""Tests for pipeline_dashboard.transcripts, entries and timeutil."""
import json
import os
import shutil
import tempfile
import unittest

import fixture_builder as fb
from pipeline_dashboard import entries, timeutil, transcripts


class EncodeTest(unittest.TestCase):
    def test_every_non_alphanumeric_becomes_dash(self):
        if os.name == "nt":
            self.assertEqual(
                transcripts.encode_project_path(r"C:\Users\EMVIGO-USER\Muhassin\workspace\claude-investigation\emi"),
                "C--Users-EMVIGO-USER-Muhassin-workspace-claude-investigation-emi")
        else:
            self.assertEqual(transcripts.encode_project_path("/home/dev/my_repo.v2"), "-home-dev-my-repo-v2")

    def test_config_dir_prefers_env(self):
        self.assertEqual(transcripts.config_dir({"CLAUDE_CONFIG_DIR": "/x/cfg"}), "/x/cfg")
        self.assertTrue(transcripts.config_dir({}).endswith(".claude"))


class FoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cfg = os.path.join(self.tmp, "cfg")
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_direct_folder(self):
        t = fb.Transcript(cwd=self.repo)
        t.user(0, "hi")
        fb.write_session(self.cfg, self.repo, t)
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [fb.project_folder(self.cfg, self.repo)])

    def test_fallback_scan_matches_cwd(self):
        other = os.path.join(self.cfg, "projects", "shortened-name")
        t = fb.Transcript(cwd=self.repo)
        t.user(0, "hi")
        t.write(os.path.join(other, "s.jsonl"))
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [other])

    def test_no_folders(self):
        self.assertEqual(transcripts.transcript_folders(self.repo, self.cfg), [])

    def test_lists_sessions_and_subagents(self):
        folder = fb.project_folder(self.cfg, self.repo)
        main = fb.Transcript(session_id="s1", cwd=self.repo)
        main.user(0, "hi")
        fb.write_session(self.cfg, self.repo, main)
        with_meta = fb.Transcript(session_id="s1", cwd=self.repo, sidechain=True, agent_id="a1")
        with_meta.user(0, "go")
        fb.write_agent(self.cfg, self.repo, "s1", with_meta, "sdlc-pipeline:planner", "Plan it", "tu-1")
        no_meta = fb.Transcript(session_id="s1", cwd=self.repo, sidechain=True, agent_id="a2")
        no_meta.user(0, "go")
        fb.write_agent(self.cfg, self.repo, "s1", no_meta, "x", "y", "tu-2", meta=False)

        self.assertEqual(transcripts.list_sessions(folder), [("s1", os.path.join(folder, "s1.jsonl"))])
        files = transcripts.subagent_files(folder, "s1")
        self.assertEqual([f[0] for f in files], ["a1", "a2"])
        self.assertEqual(transcripts.read_meta(files[0][2])["agentType"], "sdlc-pipeline:planner")
        self.assertIsNone(files[1][2])
        self.assertEqual(transcripts.read_meta(None), {})


class JsonlFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "s.jsonl")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _append(self, text):
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def test_reads_only_new_complete_lines(self):
        self._append(json.dumps({"type": "user", "version": "2.1.312"}) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        self.assertEqual(len(f.entries), 1)
        self._append(json.dumps({"type": "assistant"}) + "\n" + '{"type": "user"')
        f.refresh()
        self.assertEqual(len(f.entries), 2)
        self._append("}\n")
        f.refresh()
        self.assertEqual([e["_line"] for e in f.entries], [1, 2, 3])
        self.assertEqual(f.versions, {"2.1.312"})

    def test_counts_bad_lines_and_skips_other_types(self):
        self._append("{not json\n" + json.dumps({"type": "queue-operation", "version": "2.1.400"}) + "\n"
                     + json.dumps([1, 2]) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        self.assertEqual(f.entries, [])
        self.assertEqual(f.bad_lines, 2)
        self.assertEqual(f.versions, {"2.1.400"})

    def test_shrunk_file_is_reread(self):
        self._append(json.dumps({"type": "user"}) + "\n" + json.dumps({"type": "user"}) + "\n")
        f = transcripts.JsonlFile(self.path)
        f.refresh()
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"type": "assistant"}) + "\n")
        f.refresh()
        self.assertEqual([e["type"] for e in f.entries], ["assistant"])

    def test_cache_returns_refreshed_file(self):
        self._append(json.dumps({"type": "user"}) + "\n")
        cache = transcripts.FileCache()
        self.assertEqual(len(cache.get(self.path).entries), 1)
        self._append(json.dumps({"type": "user"}) + "\n")
        self.assertEqual(len(cache.get(self.path).entries), 2)


class EntriesTest(unittest.TestCase):
    def test_text_and_tools(self):
        t = fb.Transcript()
        use = t.tool_use(0, "Skill", {"skill": "x"}, "tu-1")
        self.assertEqual(entries.tool_uses(use), [("tu-1", "Skill", {"skill": "x"})])
        result = t.tool_result(0, "tu-1", "done", is_error=True)
        self.assertEqual(entries.tool_results(result), [("tu-1", "done", True)])
        self.assertEqual(entries.message_text(t.user(0, "hello")), "hello")
        self.assertEqual(entries.stop_reason(use), "tool_use")
        self.assertEqual(entries.model_of(use), "claude-opus-5-5")

    def test_typed_by_client(self):
        t = fb.Transcript()
        self.assertTrue(entries.is_typed_by_client(t.user(0, "Approve it")))
        self.assertFalse(entries.is_typed_by_client(
            t.user(0, "<task-notification>\n<task-id>a1</task-id>", origin={"kind": "task-notification"})))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "report", isMeta=True)))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "<system-reminder>x</system-reminder>")))
        self.assertFalse(entries.is_typed_by_client(t.user(0, "Another Claude session sent a message: hi")))
        self.assertFalse(entries.is_typed_by_client(t.tool_result(0, "tu", "x")))

    def test_parse_ts(self):
        a = timeutil.parse_ts("2026-10-29T05:36:11.892Z")
        b = timeutil.parse_ts("2026-10-29T05:36:10.892Z")
        self.assertAlmostEqual(a - b, 1.0)
        self.assertIsNone(timeutil.parse_ts("nope"))
        self.assertIsNone(timeutil.parse_ts(None))


if __name__ == "__main__":
    unittest.main()
