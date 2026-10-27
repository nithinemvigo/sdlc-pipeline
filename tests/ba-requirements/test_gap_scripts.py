"""Tests for the Phase 2 scripts (standard library only).

Run from the plugin root:
    python -m unittest discover -s tests -v

Scenarios 1, 5 and 14 of the specification (agent-quality analysis, consolidating
duplicate candidates, asking for clarification) depend on the model and cannot be
unit-tested; everything the scripts enforce is covered here.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")


def load(filename, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load("validate-gap-register.py", "t_validator")
store = load("gap-register-store.py", "t_store")
reporter = load("generate-gap-report.py", "t_reporter")

REQUIREMENTS = [
    {"requirement_id": "REQ-001", "title": "User Login", "description": "The system shall authenticate users using their registered email address and password."},
    {"requirement_id": "REQ-002", "title": "Password Reset", "description": "The system shall allow users to reset their password by email."},
    {"requirement_id": "REQ-003", "title": "Session Timeout", "description": "The system shall end inactive user sessions."},
    {"requirement_id": "REQ-004", "title": "Audit Log", "description": "The system shall record security-relevant events."},
    {"requirement_id": "REQ-005", "title": "Report Export", "description": "The system shall let managers export reports."},
    {"requirement_id": "REQ-006", "title": "Profile Update", "description": "The system shall let users update their profile."},
]


def read_file(path):
    with open(path, "rb") as handle:
        return handle.read()


def descr(requirements, req_id):
    return next(r["description"] for r in requirements if r["requirement_id"] == req_id)


def make_gap(gap_id, priority, definition, req_ids, status="open", decisions=None, requirements=REQUIREMENTS):
    return {
        "gap_id": gap_id,
        "priority": priority,
        "status": status,
        "gap_definition": definition,
        "decisions_recorded": decisions or [],
        "affected_requirements": [{"requirement_id": r, "description": descr(requirements, r)} for r in req_ids],
    }


def base_gaps():
    return [
        make_gap("GAP-001", "Critical", "Should the account lock after repeated failed logins, and for how long?", ["REQ-001", "REQ-003"]),
        make_gap("GAP-002", "High", "How long may a password reset link remain valid?", ["REQ-002"]),
        make_gap("GAP-003", "Medium", "Which events must the audit log record?", ["REQ-004"]),
        make_gap("GAP-004", "Low", "Which file formats may reports be exported in?", ["REQ-005"]),
        make_gap("GAP-005", "Critical", "What is the inactivity period that ends a session?", ["REQ-003"]),
    ]


class ProjectCase(unittest.TestCase):
    """Creates a throw-away project with atomic requirements."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ba-gap-test-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.requirements = copy.deepcopy(REQUIREMENTS)
        self.write_requirements(self.requirements)
        self.scratch = tempfile.mkdtemp(prefix="ba-gap-draft-")
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    # -- file helpers
    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def write_requirements(self, requirements):
        os.makedirs(self.p("atomic_requirements"), exist_ok=True)
        with open(self.p("atomic_requirements", "atomic_requirements.json"), "w", encoding="utf-8") as handle:
            json.dump(requirements, handle, indent=2)
        self.requirements = requirements

    def draft(self, gaps, name="draft.json"):
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(gaps, handle, indent=2)
        return path

    def register(self):
        with open(self.p("gaps", "gaps.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def register_bytes(self):
        with open(self.p("gaps", "gaps.json"), "rb") as handle:
            return handle.read()

    def html(self):
        with open(self.p("gaps", "gap-analysis.html"), encoding="utf-8") as handle:
            return handle.read()

    def state(self):
        with open(self.p("gaps", "gap-analysis-state.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def decision_file(self, text):
        path = os.path.join(self.scratch, "decision.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    # -- CLI helper (in-process)
    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = store.main([args[0], "--project-root", self.root, *args[1:]])
        return code, json.loads(out.getvalue())

    def save_new(self, gaps=None):
        code, result = self.cli("save", "--draft", self.draft(gaps if gaps is not None else base_gaps()), "--mode", "new")
        self.assertEqual(code, 0, result)
        return result

    def resolve(self, gap_id, text="Lock after five failed attempts for 30 minutes.", *extra):
        return self.cli("resolve", "--gap-id", gap_id, "--decision-file", self.decision_file(text), *extra)


class ValidatorTests(ProjectCase):
    def check(self, gaps, **kwargs):
        reqs = {r["requirement_id"]: r["description"] for r in self.requirements}
        return validator.validate_register(gaps, [], reqs, **kwargs)

    def test_valid_register_passes(self):
        errors, warnings = self.check(base_gaps())
        self.assertEqual((errors, warnings), ([], []))

    def test_empty_register_is_valid(self):  # scenario 2
        self.assertEqual(self.check([])[0], [])

    def test_one_gap_many_requirements_and_many_gaps_one_requirement(self):  # scenarios 3, 4
        gaps = [
            make_gap("GAP-001", "High", "Which roles may perform sensitive actions?", ["REQ-001", "REQ-002", "REQ-004"]),
            make_gap("GAP-002", "Low", "Is the login page branded per tenant?", ["REQ-001"]),
            make_gap("GAP-003", "Medium", "Is multi-factor authentication needed at login?", ["REQ-001"]),
        ]
        self.assertEqual(self.check(gaps)[0], [])

    def test_all_priorities_accepted_and_bad_priority_rejected(self):  # scenario 6
        gaps = base_gaps()
        self.assertEqual({g["priority"] for g in gaps}, {"Critical", "High", "Medium", "Low"})
        self.assertEqual(self.check(gaps)[0], [])
        gaps[0]["priority"] = "Urgent"
        self.assertTrue(any("priority" in e for e in self.check(gaps)[0]))

    def test_duplicate_gap_ids_rejected(self):  # scenario 9
        gaps = base_gaps()
        gaps[1]["gap_id"] = "GAP-001"
        self.assertTrue(any("duplicate gap_id" in e for e in self.check(gaps)[0]))

    def test_unknown_requirement_rejected(self):  # scenario 10
        gaps = base_gaps()
        gaps[0]["affected_requirements"].append({"requirement_id": "REQ-099", "description": "x"})
        errors = self.check(gaps)[0]
        self.assertTrue(any("REQ-099" in e and "does not exist" in e for e in errors))

    def test_resolved_without_decision_rejected(self):  # scenario 11
        gaps = base_gaps()
        gaps[0]["status"] = "resolved"
        self.assertTrue(any("no decision is recorded" in e for e in self.check(gaps)[0]))

    def test_invalid_timestamp_rejected(self):  # scenario 12
        for bad in ("yesterday", "2026-13-40T10:00:00", "2026-10-26", "2026-10-26T25:00:00+05:30"):
            gaps = base_gaps()
            gaps[0]["status"] = "resolved"
            gaps[0]["decisions_recorded"] = [{"decision": "Five attempts.", "recorded_at": bad}]
            self.assertTrue(any("ISO 8601" in e for e in self.check(gaps)[0]), bad)
        gaps = base_gaps()
        gaps[0]["decisions_recorded"] = [{"decision": "x", "recorded_at": "2026-10-26T18:30:00+05:30"}]
        self.assertEqual(self.check(gaps)[0], [])

    def test_structure_errors(self):  # scenario 8
        gaps = base_gaps()
        gaps[0]["extra"] = 1
        del gaps[1]["status"]
        gaps[2]["decisions_recorded"] = "none"
        gaps[3]["affected_requirements"][0]["note"] = "x"
        gaps[4]["gap_definition"] = "   "
        errors = self.check(gaps)[0]
        for fragment in ("unexpected property: extra", "missing required property: status", "must be an array", "note", "must not be empty"):
            self.assertTrue(any(fragment in e for e in errors), fragment)
        self.assertTrue(validator.validate_register({"gaps": []}, [], None)[0])

    def test_duplicate_definition_and_duplicate_affected_requirement_rejected(self):
        gaps = base_gaps()
        gaps[1]["gap_definition"] = "  " + gaps[0]["gap_definition"].upper()
        gaps[2]["affected_requirements"].append(gaps[2]["affected_requirements"][0])
        errors = self.check(gaps)[0]
        self.assertTrue(any("duplicates GAP-001" in e for e in errors))
        self.assertTrue(any("more than once" in e for e in errors))

    def test_gap_without_affected_requirement_rejected(self):
        gaps = base_gaps()
        gaps[0]["affected_requirements"] = []
        self.assertTrue(any("at least one affected requirement" in e for e in self.check(gaps)[0]))

    def test_stale_description_is_error_unless_allowed(self):
        gaps = base_gaps()
        gaps[1]["affected_requirements"][0]["description"] = "old wording"
        self.assertTrue(any("does not match" in e for e in self.check(gaps)[0]))
        errors, warnings = self.check(gaps, allow_stale=True)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)

    def test_cli_exit_codes(self):
        self.save_new()
        script = os.path.join(SCRIPTS, "validate-gap-register.py")
        good = subprocess.run([sys.executable, script, self.p("gaps", "gaps.json")], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stderr)
        bad_path = os.path.join(self.scratch, "bad.json")
        with open(bad_path, "w", encoding="utf-8") as handle:
            handle.write("[{")
        bad = subprocess.run([sys.executable, script, bad_path, "--structure-only"], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)
        missing = subprocess.run([sys.executable, script, os.path.join(self.scratch, "nope.json"), "--structure-only"], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)


class InputAndSaveTests(ProjectCase):
    def test_invalid_atomic_json_stops_everything(self):  # scenario 7
        with open(self.p("atomic_requirements", "atomic_requirements.json"), "w", encoding="utf-8") as handle:
            handle.write('{"not": "an array"}')
        code, result = self.cli("inspect")
        self.assertEqual(result["status"], "INPUT_INVALID")
        code, result = self.cli("save", "--draft", self.draft(base_gaps()), "--mode", "new")
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.p("gaps", "gaps.json")))

    def test_missing_and_empty_input(self):
        os.unlink(self.p("atomic_requirements", "atomic_requirements.json"))
        self.assertEqual(self.cli("inspect")[1]["status"], "INPUT_MISSING")
        self.write_requirements([])
        self.assertEqual(self.cli("inspect")[1]["status"], "INPUT_EMPTY")

    def test_new_register_creates_all_artifacts(self):
        before = self.cli("inspect")[1]
        self.assertEqual(before["status"], "NO_REGISTER")
        result = self.save_new()
        self.assertTrue(result["html_generated"])
        for name in ("gaps.json", "gap-analysis.html", "gap-analysis-state.json"):
            self.assertTrue(os.path.isfile(self.p("gaps", name)), name)
        self.assertEqual(len(self.register()), 5)
        state = self.state()
        self.assertEqual(state["highest_gap_number"], 5)
        self.assertEqual(len(state["input_sha256"]), 64)
        self.assertEqual(self.cli("inspect")[1]["status"], "UNCHANGED")

    def test_no_gaps_saves_empty_array_and_empty_state_page(self):  # scenario 2
        self.save_new([])
        self.assertEqual(self.register(), [])
        self.assertIn("No gaps were identified", self.html())

    def test_existing_register_never_overwritten_by_new_analysis(self):
        self.save_new()
        original = self.register_bytes()
        code, result = self.cli("save", "--draft", self.draft(base_gaps()[:2]), "--mode", "new")
        self.assertEqual(code, 1)
        self.assertEqual(self.register_bytes(), original)

    def test_new_mode_rejects_decisions_and_non_sequential_ids(self):
        gaps = base_gaps()
        gaps[3]["gap_id"] = "GAP-009"
        self.assertEqual(self.cli("save", "--draft", self.draft(gaps), "--mode", "new")[0], 1)
        gaps = base_gaps()
        gaps[0].update(status="resolved", decisions_recorded=[{"decision": "x", "recorded_at": "2026-10-26T10:00:00+00:00"}])
        self.assertEqual(self.cli("save", "--draft", self.draft(gaps), "--mode", "new")[0], 1)

    def test_atomic_requirements_file_is_never_modified(self):
        path = self.p("atomic_requirements", "atomic_requirements.json")
        before = read_file(path)
        self.save_new()
        self.resolve("GAP-001")
        self.cli("skip", "--gap-id", "GAP-002")
        self.assertEqual(read_file(path), before)

    def test_unchanged_input_is_detected_and_adds_no_gaps(self):  # scenario 22
        self.save_new()
        before = self.register_bytes()
        info = self.cli("inspect")[1]
        self.assertEqual(info["status"], "UNCHANGED")
        self.assertEqual(self.register_bytes(), before)

    def test_reset_requires_confirmation_and_backs_up(self):
        self.save_new()
        self.resolve("GAP-001")
        draft = self.draft(base_gaps()[:2])
        code, _ = self.cli("save", "--draft", draft, "--mode", "reset")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.register()), 5)
        code, result = self.cli("save", "--draft", draft, "--mode", "reset", "--confirm-reset")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(self.register()), 2)
        backups = [d for d in os.listdir(self.p("gaps")) if d.startswith("backup-")]
        self.assertEqual(len(backups), 1)
        saved = json.loads(read_file(self.p("gaps", backups[0], "gaps.json")))
        self.assertEqual(saved[0]["status"], "resolved")


class TriageTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.save_new()

    def test_queue_order_is_priority_then_id(self):  # section 10.1
        code, result = self.cli("list")
        ids = [g["gap_id"] for g in result["queue"]]
        self.assertEqual(ids, ["GAP-001", "GAP-005", "GAP-002", "GAP-003", "GAP-004"])

    def test_resolve_records_decision_with_timestamp(self):  # scenario 13
        code, result = self.resolve("GAP-001")
        self.assertEqual(code, 0, result)
        gap = next(g for g in self.register() if g["gap_id"] == "GAP-001")
        self.assertEqual(gap["status"], "resolved")
        self.assertEqual(len(gap["decisions_recorded"]), 1)
        self.assertIsNotNone(validator.parse_timestamp(gap["decisions_recorded"][0]["recorded_at"]))
        self.assertTrue(result["html_generated"])
        self.assertIn("Lock after five failed attempts", self.html())

    def test_empty_decision_refused(self):
        code, result = self.resolve("GAP-001", "   \n")
        self.assertEqual(code, 1)
        self.assertEqual(next(g for g in self.register() if g["gap_id"] == "GAP-001")["status"], "open")

    def test_skip_one_gap_and_continue(self):  # scenario 15
        self.cli("skip", "--gap-id", "GAP-001")
        statuses = {g["gap_id"]: g["status"] for g in self.register()}
        self.assertEqual(statuses["GAP-001"], "skipped")
        self.assertEqual(statuses["GAP-002"], "open")
        self.assertEqual(next(g for g in self.register() if g["gap_id"] == "GAP-001")["decisions_recorded"], [])
        self.assertEqual(self.resolve("GAP-005")[0], 0)

    def test_skip_all_leaves_register_untouched_and_statuses_preserved(self):  # scenario 16
        self.cli("skip", "--gap-id", "GAP-001")
        self.resolve("GAP-005")
        before = self.register_bytes()
        self.cli("list")  # skip-all is a session control: no write command is issued
        self.assertEqual(self.register_bytes(), before)
        statuses = {g["gap_id"]: g["status"] for g in self.register()}
        self.assertEqual(statuses, {"GAP-001": "skipped", "GAP-002": "open", "GAP-003": "open", "GAP-004": "open", "GAP-005": "resolved"})

    def test_resume_includes_skipped_and_excludes_resolved(self):  # scenario 17
        self.cli("skip", "--gap-id", "GAP-001")
        self.resolve("GAP-005")
        queue = [g["gap_id"] for g in self.cli("list")[1]["queue"]]
        self.assertEqual(queue, ["GAP-001", "GAP-002", "GAP-003", "GAP-004"])
        self.assertNotIn("GAP-005", queue)

    def test_skipped_gap_can_be_resolved_later(self):
        self.cli("skip", "--gap-id", "GAP-001")
        self.assertEqual(self.resolve("GAP-001")[0], 0)

    def test_reopen_keeps_decision_history_and_revision_appends(self):  # scenario 18
        self.resolve("GAP-001", "First decision.")
        code, result = self.resolve("GAP-001", "Second decision.")
        self.assertEqual(code, 1)  # needs --revise
        self.assertEqual(self.resolve("GAP-001", "Revised decision.", "--revise")[0], 0)
        code, result = self.cli("reopen", "--gap-id", "GAP-001")
        self.assertEqual(code, 0, result)
        gap = next(g for g in self.register() if g["gap_id"] == "GAP-001")
        self.assertEqual(gap["status"], "open")
        self.assertEqual([d["decision"] for d in gap["decisions_recorded"]], ["First decision.", "Revised decision."])
        self.assertIn("GAP-001", [g["gap_id"] for g in self.cli("list")[1]["queue"]])
        self.assertEqual(self.resolve("GAP-001", "Third decision.")[0], 0)
        gap = next(g for g in self.register() if g["gap_id"] == "GAP-001")
        self.assertEqual(len(gap["decisions_recorded"]), 3)
        self.assertEqual(gap["decisions_recorded"][0]["decision"], "First decision.")

    def test_cannot_skip_resolved_gap(self):
        self.resolve("GAP-001")
        self.assertEqual(self.cli("skip", "--gap-id", "GAP-001")[0], 1)

    def test_unknown_gap_refused(self):
        self.assertEqual(self.cli("skip", "--gap-id", "GAP-099")[0], 1)

    def test_failed_replace_preserves_last_valid_register(self):  # scenario 19
        before = self.register_bytes()
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            code, result = self.resolve("GAP-001")
        self.assertEqual(code, 2)
        self.assertEqual(self.register_bytes(), before)
        leftovers = [n for n in os.listdir(self.p("gaps")) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertEqual(self.resolve("GAP-001")[0], 0)

    def test_failed_readback_restores_previous_register(self):  # scenario 19
        before = self.register_bytes()
        original = store.atomic_write_bytes
        calls = []

        def corrupt_first_write(path, payload):
            calls.append(path)
            original(path, payload[:-5] if len(calls) == 1 else payload)

        with mock.patch.object(store, "atomic_write_bytes", side_effect=corrupt_first_write):
            code, result = self.resolve("GAP-001")
        self.assertEqual(code, 1)
        self.assertEqual(self.register_bytes(), before)

    def test_html_failure_keeps_json(self):
        with mock.patch.object(store.reporter, "atomic_write_text", side_effect=OSError("locked")):
            code, result = self.resolve("GAP-001")
        self.assertEqual(code, 3)
        self.assertTrue(result["ok"])
        self.assertFalse(result["html_generated"])
        self.assertEqual(next(g for g in self.register() if g["gap_id"] == "GAP-001")["status"], "resolved")
        code, _ = self.cli("regenerate-report")
        self.assertEqual(code, 0)

    def test_triage_refuses_when_requirements_changed(self):
        changed = copy.deepcopy(REQUIREMENTS)
        changed[0]["description"] = "The system shall authenticate users with a one-time code."
        self.write_requirements(changed)
        code, result = self.cli("list")
        self.assertEqual(code, 1)
        self.assertIn("analyse-gaps", result["error"])

    def test_triage_refuses_invalid_register(self):
        gaps = self.register()
        gaps[1]["gap_id"] = "GAP-001"
        with open(self.p("gaps", "gaps.json"), "w", encoding="utf-8") as handle:
            json.dump(gaps, handle)
        code, result = self.cli("list")
        self.assertEqual(code, 1)
        self.assertTrue(any("duplicate gap_id" in d for d in result["details"]))


class ReportTests(ProjectCase):
    def test_html_reflects_every_status_decision_and_count(self):  # scenario 20
        self.save_new()
        self.resolve("GAP-001", "Decision <one>.")
        self.resolve("GAP-001", "Decision two.", "--revise")
        self.cli("skip", "--gap-id", "GAP-002")
        page = self.html()
        self.assertIn('data-status="resolved"', page)
        self.assertIn('data-status="skipped"', page)
        self.assertEqual(page.count('data-status="open"'), 3)
        self.assertIn("Current decision", page)
        self.assertIn("Earlier decision", page)
        self.assertIn("Decision two.", page)
        self.assertIn('<div class="stat resolved"><b>1</b>', page)
        self.assertIn('<div class="stat skipped"><b>1</b>', page)
        self.assertIn('<div class="stat open"><b>3</b>', page)
        self.assertIn('<div class="stat"><b>5</b>', page)
        self.assertIn("Skipped gaps (unresolved)", page)
        for req_id in ("REQ-001", "REQ-003", "REQ-004"):
            self.assertIn(req_id, page)
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", page)

    def test_html_escapes_untrusted_content(self):  # scenario 21
        evil = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        self.requirements = copy.deepcopy(REQUIREMENTS)
        self.requirements[0]["description"] = evil
        self.write_requirements(self.requirements)
        gaps = [make_gap("GAP-001", "High", evil + " definition", ["REQ-001"], requirements=self.requirements)]
        self.save_new(gaps)
        self.resolve("GAP-001", evil)
        page = self.html()
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", page)
        self.assertEqual(page.count("<script>"), 1)  # only the report's own script block

    def test_invalid_register_produces_no_report(self):
        self.save_new()
        os.unlink(self.p("gaps", "gap-analysis.html"))
        gaps = self.register()
        gaps[0]["status"] = "resolved"
        with open(self.p("gaps", "gaps.json"), "w", encoding="utf-8") as handle:
            json.dump(gaps, handle)
        code, result = self.cli("regenerate-report")
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.p("gaps", "gap-analysis.html")))


class ReconciliationTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.save_new()
        self.resolve("GAP-001", "Lock after five attempts for 30 minutes.")
        self.resolve("GAP-002", "Reset links expire after 24 hours.")
        self.cli("skip", "--gap-id", "GAP-003")

    def reconcile(self, gaps, *extra):
        return self.cli("save", "--draft", self.draft(gaps, "recon.json"), "--mode", "reconcile", *extra)

    def current(self):
        return copy.deepcopy(self.register())

    def refresh_refs(self, gap):
        for ref in gap["affected_requirements"]:
            ref["description"] = descr(self.requirements, ref["requirement_id"])

    def test_added_requirement_with_new_gap_gets_new_id(self):  # scenario 23
        new_reqs = copy.deepcopy(REQUIREMENTS) + [
            {"requirement_id": "REQ-007", "title": "Data Retention", "description": "The system shall retain records."}
        ]
        self.write_requirements(new_reqs)
        info = self.cli("inspect")[1]
        self.assertEqual(info["status"], "CHANGED")
        self.assertEqual(info["changes"], {"added": ["REQ-007"], "changed": [], "removed": []})
        gaps = self.current()
        gaps.append(make_gap("GAP-006", "High", "For how long must records be retained?", ["REQ-007"], requirements=new_reqs))
        code, result = self.reconcile(gaps)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["reconciliation"]["new"], ["GAP-006"])
        self.assertEqual(self.cli("inspect")[1]["status"], "UNCHANGED")
        self.assertEqual(self.state()["highest_gap_number"], 6)

    def test_edited_requirement_forces_confirmation_of_resolved_gap(self):  # scenarios 23, 24
        new_reqs = copy.deepcopy(REQUIREMENTS)
        new_reqs[1]["description"] = "The system shall allow users to reset their password by SMS."
        self.write_requirements(new_reqs)
        info = self.cli("inspect")[1]
        self.assertEqual(info["changes"]["changed"], ["REQ-002"])
        gaps = self.current()
        for gap in gaps:
            for ref in gap["affected_requirements"]:
                ref["description"] = descr(new_reqs, ref["requirement_id"])
        before = self.register_bytes()
        code, result = self.reconcile(gaps)
        self.assertEqual(code, 1)
        self.assertIn("GAP-002", " ".join(result["details"]))
        self.assertEqual(self.register_bytes(), before)

        code, result = self.reconcile(gaps, "--confirmed", "GAP-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["reconciliation"]["modified"].count("GAP-002"), 1)
        gap2 = next(g for g in self.register() if g["gap_id"] == "GAP-002")
        self.assertEqual(gap2["status"], "resolved")
        self.assertEqual(gap2["decisions_recorded"][0]["decision"], "Reset links expire after 24 hours.")

    def test_edited_requirement_reopening_keeps_decision_history(self):  # scenario 24
        new_reqs = copy.deepcopy(REQUIREMENTS)
        new_reqs[1]["description"] = "The system shall allow users to reset their password by SMS."
        self.write_requirements(new_reqs)
        gaps = self.current()
        for gap in gaps:
            for ref in gap["affected_requirements"]:
                ref["description"] = descr(new_reqs, ref["requirement_id"])
        next(g for g in gaps if g["gap_id"] == "GAP-002")["status"] = "open"
        code, result = self.reconcile(gaps)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["reconciliation"]["reopened"], ["GAP-002"])
        gap2 = next(g for g in self.register() if g["gap_id"] == "GAP-002")
        self.assertEqual(gap2["status"], "open")
        self.assertEqual(len(gap2["decisions_recorded"]), 1)

    def test_reconcile_cannot_alter_or_drop_decisions(self):  # scenario 24
        for mutate in (
            lambda g: g[0]["decisions_recorded"].clear(),
            lambda g: g[0]["decisions_recorded"].append({"decision": "sneaky", "recorded_at": "2026-10-26T10:00:00+00:00"}),
            lambda g: g[0]["decisions_recorded"][0].update(decision="rewritten"),
        ):
            gaps = self.current()
            mutate(gaps)
            if not gaps[0]["decisions_recorded"]:
                gaps[0]["status"] = "open"
            before = self.register_bytes()
            code, result = self.reconcile(gaps)
            self.assertEqual(code, 1, result)
            self.assertEqual(self.register_bytes(), before)

    def test_reconcile_cannot_silently_resolve_or_downgrade(self):
        gaps = self.current()
        next(g for g in gaps if g["gap_id"] == "GAP-004")["status"] = "skipped"
        self.assertEqual(self.reconcile(gaps)[0], 1)  # skipping is a triage action, not an analysis outcome
        gaps = self.current()
        next(g for g in gaps if g["gap_id"] == "GAP-004")["status"] = "resolved"
        self.assertEqual(self.reconcile(gaps)[0], 1)  # analysis cannot resolve without a decision
        gaps = self.current()
        next(g for g in gaps if g["gap_id"] == "GAP-001")["status"] = "skipped"
        self.assertEqual(self.reconcile(gaps)[0], 1)

    def test_removed_requirement_gap_cannot_vanish_without_approval(self):  # scenario 23
        new_reqs = [r for r in REQUIREMENTS if r["requirement_id"] != "REQ-005"]
        self.write_requirements(new_reqs)
        self.assertEqual(self.cli("inspect")[1]["changes"]["removed"], ["REQ-005"])
        gaps = [g for g in self.current() if g["gap_id"] != "GAP-004"]
        for gap in gaps:
            self.refresh_refs(gap)
        before = self.register_bytes()
        self.assertEqual(self.reconcile(gaps)[0], 1)  # dropped silently
        self.assertEqual(self.reconcile(gaps, "--retire", "GAP-004")[0], 1)  # no approval flag
        self.assertEqual(self.register_bytes(), before)
        code, result = self.reconcile(gaps, "--retire", "GAP-004", "--approve-retirement", "--retire-reason", "REQ-005 was removed.")
        self.assertEqual(code, 0, result)
        self.assertEqual([g["gap_id"] for g in self.register()], ["GAP-001", "GAP-002", "GAP-003", "GAP-005"])
        archive = json.loads(read_file(self.p("gaps", "retired-gaps.json")))
        self.assertEqual(archive[0]["gap"]["gap_id"], "GAP-004")
        self.assertEqual(archive[0]["reason"], "REQ-005 was removed.")

    def test_retired_ids_are_never_reused(self):
        new_reqs = [r for r in REQUIREMENTS if r["requirement_id"] != "REQ-005"]
        self.write_requirements(new_reqs)
        gaps = [g for g in self.current() if g["gap_id"] != "GAP-004"]
        for gap in gaps:
            self.refresh_refs(gap)
        self.reconcile(gaps, "--retire", "GAP-004", "--approve-retirement", "--retire-reason", "removed")
        self.assertEqual(self.state()["highest_gap_number"], 5)
        gaps = self.current()
        gaps.append(make_gap("GAP-004", "Low", "Reused ID?", ["REQ-006"], requirements=new_reqs))
        self.assertEqual(self.reconcile(gaps)[0], 1)
        gaps[-1]["gap_id"] = "GAP-006"
        self.assertEqual(self.reconcile(gaps)[0], 0)

    def test_missing_state_forces_confirmation_of_every_resolved_gap(self):
        os.unlink(self.p("gaps", "gap-analysis-state.json"))
        self.assertEqual(self.cli("inspect")[1]["status"], "NO_STATE")
        self.assertEqual(self.cli("list")[0], 1)
        code, result = self.reconcile(self.current())
        self.assertEqual(code, 1)
        code, result = self.reconcile(self.current(), "--confirmed", "GAP-001,GAP-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.cli("inspect")[1]["status"], "UNCHANGED")


if __name__ == "__main__":
    unittest.main()
