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


if __name__ == "__main__":
    unittest.main()
