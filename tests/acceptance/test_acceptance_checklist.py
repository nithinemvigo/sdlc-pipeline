"""Tests for scripts/acceptance-checklist.py (standard library only).

Run from the repo root:
    python -I -m unittest discover -s tests/acceptance
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts", "acceptance-checklist.py")
EXPORT = os.path.join(FIXTURES, "export.json")
REQUIREMENTS = os.path.join(FIXTURES, "requirements.md")
PLAN = os.path.join(FIXTURES, "plan")

EVIDENCE = [{"type": "test", "ref": "tests/x.test.ts::rejects unknown email", "detail": "passed"}]


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def write_json(self, name, data):
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return path

    def run_script(self, *argv):
        proc = subprocess.run([sys.executable, "-I", SCRIPT, *argv], capture_output=True, text=True, encoding="utf-8")
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = {"stdout": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, data

    def read_json(self, path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def build(self, *argv):
        out = self.path("checklist.json")
        code, result = self.run_script("build", *argv, "--out", out)
        return code, result, out

    def full_checklist(self):
        code, result, out = self.build("--export", EXPORT, "--requirements", REQUIREMENTS)
        self.assertEqual(code, 0, result)
        return out

    def met_verdicts(self, checklist):
        return {"verdicts": [{"id": item["id"], "status": "met", "evidence": EVIDENCE, "fix_hint": "", "note": ""}
                             for item in self.read_json(checklist)["items"]]}

    def render(self, checklist, verdicts, out_dir=None):
        out_dir = out_dir or self.path("report")
        code, result = self.run_script("render", "--checklist", checklist, "--verdicts",
                                       self.write_json("verdicts.json", verdicts), "--out-dir", out_dir)
        return code, result, out_dir


class BuildTests(Case):
    def test_story_and_requirement_items(self):
        out = self.full_checklist()
        items = self.read_json(out)["items"]
        self.assertEqual([i["id"] for i in items], ["US-001.1", "US-001.2", "US-002.1", "AC-001", "AC-002"])
        first = items[0]
        self.assertEqual(first["kind"], "story")
        self.assertEqual(first["story_id"], "US-001")
        self.assertEqual(first["summary"], "Reset password by email")
        self.assertEqual(first["text"], "Unknown email addresses are rejected with a generic message")
        self.assertEqual(first["source_requirement_ids"], ["REQ-001", "REQ-002"])
        self.assertEqual(items[2]["story_id"], "US-002")
        self.assertEqual(items[2]["source_requirement_ids"], ["REQ-003"])
        ac1, ac2 = items[3], items[4]
        self.assertEqual(ac1["kind"], "requirement")
        self.assertEqual(ac1["name"], "Reset by email")
        self.assertEqual(ac1["covers"], ["BR-001"])
        self.assertEqual(ac1["text"], "Given a registered user who forgot the password "
                                      "When they request a reset Then they receive a link | valid for 30 minutes")
        self.assertEqual(ac2["covers"], ["BR-002", "BR-003"])
        self.assertEqual(ac2["text"], "Given an address that is not registered When a reset is requested "
                                      "Then the response is identical to the success response")

    def test_build_prints_summary(self):
        code, result, out = self.build("--export", EXPORT, "--requirements", REQUIREMENTS)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 5)
        self.assertEqual(os.path.abspath(result["checklist"]), os.path.abspath(out))

    def test_story_without_detailed_exits_2_naming_story(self):
        export = self.read_json(EXPORT)
        export["stories"][1]["detailed"] = None
        path = self.write_json("export-null.json", export)
        code, result, out = self.build("--export", path)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertIn("US-002", result["error"])
        self.assertIn("sync", result["error"].lower())
        self.assertFalse(os.path.exists(out))

    def test_task_items(self):
        code, result, out = self.build("--tasks", PLAN)
        self.assertEqual(code, 0, result)
        items = self.read_json(out)["items"]
        self.assertEqual([i["id"] for i in items], ["T01.1", "T01.2", "T02.1"])
        self.assertTrue(all(i["kind"] == "task" for i in items))
        self.assertEqual(items[0]["text"], "US-001.1 — Unknown email is rejected")
        self.assertEqual(items[2]["text"], "Every reset writes an audit record")

    def test_no_source_exits_2(self):
        code, result, out = self.build()
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertFalse(os.path.exists(out))

    def test_sources_with_no_criteria_exit_2(self):
        empty = self.path("empty-plan")
        os.makedirs(empty)
        code, result, _ = self.build("--tasks", empty)
        self.assertEqual(code, 2)
        self.assertIn("no acceptance criteria", result["error"].lower())

    def test_duplicate_ids_exit_2(self):
        dup = self.path("dup.md")
        with open(dup, "w", encoding="utf-8") as handle:
            handle.write("### AC-001 — a\n\n**Given** x\n\n### AC-001 — b\n\n**Given** y\n")
        code, result, _ = self.build("--requirements", dup)
        self.assertEqual(code, 2)
        self.assertIn("AC-001", result["error"])


class RenderTests(Case):
    def test_all_met_writes_reports(self):
        checklist = self.full_checklist()
        code, result, out_dir = self.render(checklist, self.met_verdicts(checklist))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["met"], 5)
        self.assertEqual(result["not_met"], 0)
        self.assertEqual(result["cannot_verify"], 0)
        self.assertEqual(result["accepted_followup"], 0)
        self.assertEqual(result["open"], [])
        report = self.read_json(os.path.join(out_dir, "acceptance-report.json"))
        self.assertEqual(report["summary"]["met"], 5)
        self.assertEqual([i["id"] for i in report["items"]], ["US-001.1", "US-001.2", "US-002.1", "AC-001", "AC-002"])
        merged = report["items"][0]
        self.assertEqual(merged["text"], "Unknown email addresses are rejected with a generic message")
        self.assertEqual(merged["status"], "met")
        self.assertEqual(merged["evidence"], EVIDENCE)
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "acceptance-report.md")))

    def assert_invalid(self, checklist, verdicts, *needles):
        code, result, out_dir = self.render(checklist, verdicts)
        self.assertEqual(code, 2, result)
        self.assertFalse(result["ok"])
        problems = "\n".join(result["problems"])
        for needle in needles:
            self.assertIn(needle, problems)
        self.assertFalse(os.path.exists(os.path.join(out_dir, "acceptance-report.md")))
        return result

    def test_invalid_verdicts_list_every_problem(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)["verdicts"]
        by_id = {v["id"]: v for v in verdicts}
        verdicts = [v for v in verdicts if v["id"] != "US-001.1"]              # missing verdict
        verdicts.append({"id": "ZZ-9", "status": "met", "evidence": EVIDENCE})  # unknown id
        verdicts.append(copy.deepcopy(by_id["US-001.2"]))                      # duplicate id
        for v in verdicts:
            if v["id"] == "US-002.1":
                v["status"] = "great"                                          # bad status
            if v["id"] == "AC-001":
                v["evidence"] = []                                             # met without evidence
            if v["id"] == "AC-002":
                v["evidence"] = [{"type": "docs", "ref": "README.md"}]        # bad evidence type
        result = self.assert_invalid(checklist, {"verdicts": verdicts},
                                     "US-001.1", "ZZ-9", "US-001.2", "US-002.1", "AC-001", "AC-002")
        self.assertGreaterEqual(len(result["problems"]), 6)

    def test_accepted_followup_needs_note(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)
        verdicts["verdicts"][0] = {"id": "US-001.1", "status": "accepted_followup", "evidence": [], "note": "  "}
        self.assert_invalid(checklist, verdicts, "US-001.1", "note")

    def test_accepted_followup_with_note_is_ok_and_counted(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)
        verdicts["verdicts"][0] = {"id": "US-001.1", "status": "accepted_followup", "evidence": [],
                                   "note": "Client: ship now, fix next sprint"}
        code, result, out_dir = self.render(checklist, verdicts)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["accepted_followup"], 1)
        self.assertEqual(result["met"], 4)
        self.assertEqual(result["open"], [])
        with open(os.path.join(out_dir, "acceptance-report.md"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("4/5 met · 1 follow-ups · 0 open", text)
        self.assertIn("Client: ship now, fix next sprint", text)

    def test_not_met_and_cannot_verify_exit_1(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)
        verdicts["verdicts"][0] = {"id": "US-001.1", "status": "not_met", "evidence": [],
                                   "fix_hint": "validate email before lookup"}
        verdicts["verdicts"][4] = {"id": "AC-002", "status": "cannot_verify", "evidence": [],
                                   "note": "needs a real mailbox"}
        code, result, out_dir = self.render(checklist, verdicts)
        self.assertEqual(code, 1, result)
        self.assertEqual(result["not_met"], 1)
        self.assertEqual(result["cannot_verify"], 1)
        self.assertEqual(result["open"], ["US-001.1", "AC-002"])
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "acceptance-report.md")))
        self.assertTrue(os.path.isfile(os.path.join(out_dir, "acceptance-report.json")))

    def test_markdown_layout_and_escaping(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)
        verdicts["verdicts"][3]["evidence"] = [{"type": "code", "ref": "src/a.ts:10", "detail": "line one\nline | two"}]
        code, result, out_dir = self.render(checklist, verdicts, out_dir=self.path("nested", "deeper"))
        self.assertEqual(code, 0, result)
        with open(os.path.join(out_dir, "acceptance-report.md"), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertEqual(lines[0], "# Acceptance report")
        self.assertIn("5/5 met · 0 follow-ups · 0 open", lines)
        self.assertIn("| ID | Criterion | Status | Evidence |", lines)
        row = next(line for line in lines if line.startswith("| AC-001 |"))
        self.assertIn("link \\| valid for 30 minutes", row)
        self.assertIn("line one line \\| two", row)
        # an escaped pipe never changes the number of columns
        self.assertEqual(row.replace("\\|", "").count("|"), 5)
        for line in lines:
            if line.startswith("| US-001.1 |"):
                self.assertIn("test: tests/x.test.ts::rejects unknown email", line)

    def test_render_missing_input_exits_2(self):
        code, result = self.run_script("render", "--checklist", self.path("nope.json"), "--verdicts",
                                       self.path("nope2.json"), "--out-dir", self.path("r"))
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])


class InputValidationTests(Case):
    """Malformed input exits 2 with a message, never a traceback."""

    def assert_exit2(self, code, result):
        self.assertEqual(code, 2, result)
        self.assertFalse(result.get("ok"), result)
        self.assertNotIn("Traceback", json.dumps(result))

    def write_text(self, name, text):
        path = self.path(name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_malformed_evidence_on_any_status_exits_2(self):
        checklist = self.full_checklist()
        for bad in ("oops", ["oops"], [{"type": "test"}], [{"type": 1, "ref": "x"}], [None]):
            for status in ("met", "not_met", "cannot_verify", "accepted_followup"):
                verdicts = self.met_verdicts(checklist)
                verdicts["verdicts"][0] = {"id": "US-001.1", "status": status, "evidence": bad, "note": "n"}
                code, result, _ = self.render(checklist, verdicts)
                self.assert_exit2(code, result)
                self.assertIn("US-001.1", "\n".join(result["problems"]))

    def test_non_string_id_in_verdict_or_checklist_exits_2(self):
        checklist = self.full_checklist()
        verdicts = self.met_verdicts(checklist)
        verdicts["verdicts"][0]["id"] = 7
        code, result, _ = self.render(checklist, verdicts)
        self.assert_exit2(code, result)
        bad_list = self.write_json("bad-checklist.json", {"items": [{"id": 5, "text": "x"}]})
        code, result, _ = self.render(bad_list, {"verdicts": []})
        self.assert_exit2(code, result)

    def test_verdicts_without_list_exits_2(self):
        checklist = self.full_checklist()
        for data in ({"nope": []}, {"verdicts": "x"}, []):
            code, result, _ = self.render(checklist, data)
            self.assert_exit2(code, result)

    def test_checklist_without_item_list_exits_2(self):
        for data in ({"nope": []}, {"items": "x"}, [], {"items": ["x"]}):
            bad = self.write_json("bad.json", data)
            code, result, _ = self.render(bad, {"verdicts": []})
            self.assert_exit2(code, result)

    def test_export_without_stories_list_exits_2(self):
        for data in ({"nope": []}, {"stories": "x"}, []):
            code, result, _ = self.build("--export", self.write_json("e.json", data))
            self.assert_exit2(code, result)

    def test_story_shape_errors_exit_2(self):
        good = self.read_json(EXPORT)["stories"][0]

        def story(**changes):
            copy_ = copy.deepcopy(good)
            copy_.update(changes)
            return copy_

        def bad_detail(value):
            copy_ = copy.deepcopy(good)
            copy_["detailed"]["acceptance_criteria"] = value
            return copy_

        cases = [
            ("not-an-object", ["x"], "#1"),
            ("no id", [{k: v for k, v in good.items() if k != "story_id"}], "story_id"),
            ("criteria not a list", [bad_detail("nope")], "US-001"),
            ("blank criterion", [bad_detail(["ok", "  ", "later"])], "US-001"),
            ("non-text criterion", [bad_detail(["ok", 5])], "US-001"),
            ("sources not a list", [story(source_requirement_ids=5)], "US-001"),
        ]
        for label, stories, needle in cases:
            code, result, _ = self.build("--export", self.write_json("e.json", {"stories": stories}))
            self.assert_exit2(code, result)
            self.assertIn(needle, result["error"], label)

    def test_requirements_repeated_labels_append(self):
        path = self.write_text("r.md", "### AC-001 — a\n\n**Covers:** BR-001\n\n**Covers:** BR-002\n\n"
                                       "**Given** one\n\n**Given** two\n\n**When** w\n\n**Then** t\n")
        code, result, out = self.build("--requirements", path)
        self.assertEqual(code, 0, result)
        item = self.read_json(out)["items"][0]
        self.assertEqual(item["text"], "Given one two When w Then t")
        self.assertEqual(item["covers"], ["BR-001", "BR-002"])

    def test_requirements_html_comments_are_skipped(self):
        path = self.write_text("r.md", "<!-- ### AC-009 — hidden\n**Given** hidden\n-->\n"
                                       "### AC-001 — a\n\n<!-- single line -->\n**Given** g <!-- inline --> more\n"
                                       "<!-- multi\nline\ncomment -->\n**When** w\n\n**Then** t\n")
        code, result, out = self.build("--requirements", path)
        self.assertEqual(code, 0, result)
        items = self.read_json(out)["items"]
        self.assertEqual([i["id"] for i in items], ["AC-001"])
        self.assertEqual(items[0]["text"], "Given g more When w Then t")

    def test_requirement_without_gwt_text_exits_2_naming_ac(self):
        path = self.write_text("r.md", "### AC-001 — ok\n\n**Given** g\n\n### AC-002 — empty\n\n"
                                       "**Covers:** BR-001\n\n**Given**\n\n**When**\n\n**Then**\n")
        code, result, out = self.build("--requirements", path)
        self.assert_exit2(code, result)
        self.assertIn("AC-002", result["error"])
        self.assertFalse(os.path.exists(out))

    def test_story_numbers_follow_list_position(self):
        # a blank criterion is an error, so numbering can never silently skip a position
        export = {"stories": [{"story_id": "US-009", "summary": "s", "source_requirement_ids": [],
                               "detailed": {"acceptance_criteria": ["a", "b", "c"]}}]}
        code, result, out = self.build("--export", self.write_json("e.json", export))
        self.assertEqual(code, 0, result)
        self.assertEqual([i["id"] for i in self.read_json(out)["items"]], ["US-009.1", "US-009.2", "US-009.3"])

    def test_task_parsing_rules(self):
        plan = self.path("plan")
        os.makedirs(plan)
        self.write_text(os.path.join("plan", "task-10-last.md"), "## ACCEPTANCE CRITERIA (draft)\n- ten one\n")
        self.write_text(os.path.join("plan", "task-02-mid.md"),
                        "## Acceptance criteria\n- [ ] open box\n- [x] ticked box\n  - nested detail\n"
                        "\t- tab nested\n* star bullet\n\n## Tests\n- not a criterion\n")
        self.write_text(os.path.join("plan", "task-01-first.md"), "## Acceptance criteria\n- one\n")
        self.write_text(os.path.join("plan", "task-03-none.md"), "## Acceptance criteria extra\n\n")
        code, result, out = self.build("--tasks", plan)
        self.assertEqual(code, 0, result)
        items = self.read_json(out)["items"]
        self.assertEqual([(i["id"], i["text"]) for i in items], [
            ("T01.1", "one"),
            ("T02.1", "open box"), ("T02.2", "ticked box"), ("T02.3", "star bullet"),
            ("T10.1", "ten one"),
        ])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_written_files_are_world_readable(self):
        out = self.full_checklist()
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o644)


if __name__ == "__main__":
    unittest.main()
