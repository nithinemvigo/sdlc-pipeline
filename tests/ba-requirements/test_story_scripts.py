"""Tests for the Phase 3 scripts (standard library only).

Run from the plugin root:
    python -m unittest discover -s tests -v

Judgements that depend on the model (story decomposition, wording, whether a decision changes a
story) are specified in the agent, skills and rules and cannot be unit-tested. Everything the
scripts enforce is covered here; scenario numbers refer to section 21 of the Phase 3 specification.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")


def load(filename, name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = load("story_common.py", "ba_story_common")
validator = load("validate-development-stories.py", "ba_validate_stories")
reporter = load("generate-phase3-report.py", "ba_phase3_report")
sync = load("sync-development-stories.py", "ba_sync_stories")

REQUIREMENTS = [
    {"requirement_id": "REQ-001", "title": "User Login", "description": "The system shall authenticate users using their registered email address and password."},
    {"requirement_id": "REQ-002", "title": "Password Reset", "description": "The system shall allow users to reset their password by email."},
    {"requirement_id": "REQ-003", "title": "Session Timeout", "description": "The system shall end inactive user sessions."},
    {"requirement_id": "REQ-004", "title": "Audit Log", "description": "The system shall record security-relevant events."},
    {"requirement_id": "REQ-005", "title": "Report Export", "description": "The system shall let managers export reports."},
    {"requirement_id": "REQ-006", "title": "Profile Update", "description": "The system shall let users update their profile."},
]

DOCUMENT = """# Business Requirements

## Login

Users log in with email and password.

| Field | Rule |
|-------|------|
| Email | required |

```
# Development Stories
this heading is inside a code block and must be ignored
```

## Reports

Managers export reports.
"""


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def read_binary(path):
    with open(path, "rb") as handle:
        return handle.read()


def flat(text):
    return " ".join(text.split())


def descr(req_id):
    return next(r["description"] for r in REQUIREMENTS if r["requirement_id"] == req_id)


def make_gap(gap_id, priority, definition, req_ids, status="open", decisions=None):
    return {
        "gap_id": gap_id, "priority": priority, "status": status, "gap_definition": definition,
        "decisions_recorded": decisions or [],
        "affected_requirements": [{"requirement_id": r, "description": descr(r)} for r in req_ids],
    }


def make_story(summary, description, criteria, sources, story_id=None, applied=None):
    return {
        "story_id": story_id, "summary": summary, "description": description,
        "acceptance_criteria": criteria, "source_requirement_ids": sources, "applied_decisions": applied or [],
    }


def standard_stories():
    return [
        make_story("User authentication with registered credentials",
                   "As a registered user, I want to log in using my registered email address and password so that I can access my account.",
                   ["Given a registered user provides valid credentials, when the user submits the login form, then the system authenticates the user.",
                    "Given a user provides invalid credentials, when the user submits the login form, then the system rejects the login attempt."],
                   ["REQ-001"]),
        make_story("Password reset by email",
                   "As a registered user, I want to reset my password by email so that I can regain access to my account.",
                   ["Given a registered user requests a reset, when the request is submitted, then the system sends a reset message to the registered email address."],
                   ["REQ-002"]),
        make_story("Inactive session ends",
                   "As a registered user, I want inactive sessions to end so that my account stays protected.",
                   ["Given a session is inactive, when the inactivity limit is reached, then the system ends the session."],
                   ["REQ-003"]),
        make_story("Security events are recorded",
                   "As an administrator, I want security-relevant events recorded so that I can review them.",
                   ["Given a security-relevant event occurs, when it is processed, then the system records the event."],
                   ["REQ-004"]),
        make_story("Managers export reports",
                   "As a manager, I want to export reports so that I can share them.",
                   ["Given a manager views a report, when the manager requests an export, then the system provides the report as a file."],
                   ["REQ-005"]),
        make_story("Users update their profile",
                   "As a user, I want to update my profile so that my details stay correct.",
                   ["Given a user edits profile details, when the user saves them, then the system stores the changes."],
                   ["REQ-006"]),
    ]


class ProjectCase(unittest.TestCase):
    """A throw-away project with atomic requirements, a requirements document and a scratch directory."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ba-story-test-")
        self.root = os.path.join(self.tmp, "project")
        self.scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(self.scratch)
        os.makedirs(os.path.join(self.root, "atomic_requirements"))
        os.makedirs(os.path.join(self.root, "requirements"))
        self.write_requirements(REQUIREMENTS)
        self.doc = os.path.join(self.root, "requirements", "business-requirements.md")
        self.write_doc(DOCUMENT)
        self.paths = common.Paths(self.root)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- files
    def write_requirements(self, items):
        with open(os.path.join(self.root, "atomic_requirements", "atomic_requirements.json"), "w", encoding="utf-8") as h:
            json.dump(items, h, indent=2)

    def write_doc(self, text, newline=""):
        with open(self.doc, "w", encoding="utf-8", newline=newline) as h:
            h.write(text)

    def read_doc_bytes(self):
        with open(self.doc, "rb") as h:
            return h.read()

    def write_gaps(self, gaps):
        os.makedirs(os.path.join(self.root, "gaps"), exist_ok=True)
        with open(os.path.join(self.root, "gaps", "gaps.json"), "w", encoding="utf-8") as h:
            json.dump(gaps, h, indent=2)

    def read_state(self):
        with open(self.paths.state, "r", encoding="utf-8") as h:
            return json.load(h)

    def write_draft(self, stories, extra=None, name="draft.json"):
        draft = {"stories": stories}
        draft.update(extra or {})
        path = os.path.join(self.scratch, name)
        with open(path, "w", encoding="utf-8") as h:
            json.dump(draft, h)
        return path

    # --- running the store
    def run_sync(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync.main(list(argv) + ["--project-root", self.root] if "--project-root" not in argv else list(argv))
        return code, json.loads(out.getvalue())

    def apply(self, stories, extra=None, *flags, target=True):
        draft = self.write_draft(stories, extra)
        args = ["apply", "--draft", draft]
        if target and not os.path.exists(self.paths.state):
            args += ["--target", self.doc]
        return self.run_sync(*args, *flags)

    def generate(self, stories=None, extra=None, *flags):
        code, result = self.apply(stories or standard_stories(), extra, *flags)
        self.assertEqual(code, 0, result)
        return result

    def export_draft(self):
        code, result = self.run_sync("export")
        self.assertEqual(code, 0, result)
        return result["draft"], result

    def section_of(self):
        text = self.read_doc_bytes().decode("utf-8")
        return text[text.rindex("\n# Development Stories") + 1:]


class GenerationTests(ProjectCase):
    def test_01_generate_without_gap_register(self):
        result = self.generate()
        self.assertEqual(result["created"], ["US-001", "US-002", "US-003", "US-004", "US-005", "US-006"])
        self.assertTrue(result["report"]["generated"])
        page = read_text(self.paths.report)
        self.assertIn("Gap data is unavailable", page)
        self.assertNotIn("GAP-", page)
        self.assertEqual(self.read_state()["gap_register_hash"], None)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["gaps"]["status"], "MISSING")

    def test_02_03_04_open_skipped_resolved_gaps_do_not_block(self):
        decision = [{"decision": "Lock after five failed attempts for 30 minutes.", "recorded_at": "2026-10-26T10:00:00+05:30"}]
        self.write_gaps([
            make_gap("GAP-001", "Critical", "How long is an account locked?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "How long is a reset link valid?", ["REQ-002"], status="skipped"),
            make_gap("GAP-003", "Medium", "Which events are logged?", ["REQ-004"], status="resolved", decisions=decision),
        ])
        self.generate()
        by_id = {e["story_id"]: e for e in self.read_state()["stories"]}
        self.assertEqual(by_id["US-001"]["related_gap_ids"], ["GAP-001"])
        self.assertEqual(by_id["US-002"]["related_gap_ids"], ["GAP-002"])
        self.assertEqual(by_id["US-004"]["related_gap_ids"], ["GAP-003"])
        self.assertEqual(by_id["US-005"]["related_gap_ids"], [])
        code, info = self.run_sync("inspect")
        self.assertEqual([p["gap_id"] for p in info["pending_decisions"]], ["GAP-003"])

    def test_05_unresolved_decisions_cannot_be_claimed(self):
        self.write_gaps([make_gap("GAP-001", "Critical", "How long is an account locked?", ["REQ-001"])])
        stories = standard_stories()
        stories[0]["applied_decisions"] = ["GAP-001"]
        code, result = self.apply(stories)
        self.assertEqual(code, 1)
        self.assertTrue(any("only a resolved gap" in d for d in result["details"]), result)
        self.assertFalse(os.path.exists(self.paths.state))
        self.assertNotIn("# Development Stories\n\n## US", self.read_doc_bytes().decode())

    def test_06_07_one_story_many_requirements_and_one_requirement_many_stories(self):
        stories = standard_stories()
        stories[0]["source_requirement_ids"] = ["REQ-001", "REQ-003"]
        stories[2]["source_requirement_ids"] = ["REQ-003", "REQ-001"]
        stories[2]["summary"] = "Session ends after inactivity"
        stories[2]["description"] = "As a registered user, I want an inactive session to end so that nobody else can use my session."
        stories[2]["acceptance_criteria"] = ["Given a session is inactive, when the inactivity limit is reached, then the system ends it."]
        self.generate(stories)
        by_id = {e["story_id"]: e for e in self.read_state()["stories"]}
        self.assertEqual(by_id["US-001"]["source_requirement_ids"], ["REQ-001", "REQ-003"])
        self.assertEqual(by_id["US-003"]["source_requirement_ids"], ["REQ-001", "REQ-003"])

    def test_08_09_many_to_many_gap_story_mapping(self):
        self.write_gaps([
            make_gap("GAP-001", "Critical", "Lockout policy?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "Which credential types?", ["REQ-001"]),
        ])
        self.generate()
        by_id = {e["story_id"]: e for e in self.read_state()["stories"]}
        self.assertEqual(by_id["US-001"]["related_gap_ids"], ["GAP-001", "GAP-002"])
        self.assertEqual(by_id["US-003"]["related_gap_ids"], ["GAP-001"])

    def test_10_11_sequential_ids_and_rerun_creates_no_duplicates(self):
        self.generate()
        before = self.read_doc_bytes()
        state_before = self.read_state()
        draft, _ = self.export_draft()
        path = self.write_draft(draft["stories"], name="again.json")
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertFalse(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), before)
        self.assertEqual(self.read_state(), state_before)
        # Re-generating the same stories as 'new' stories is rejected as duplicates.
        again = draft["stories"] + [dict(s, story_id=None) for s in draft["stories"][:1]]
        code, result = self.apply(again)
        self.assertEqual(code, 1)
        self.assertTrue(any("duplicates" in d or "identical" in d for d in result["details"]), result)

    def test_12_13_existing_section_is_updated_not_duplicated_and_outside_is_preserved(self):
        self.write_doc(DOCUMENT.replace("\n", "\r\n"))
        original = self.read_doc_bytes()
        self.generate()
        after = self.read_doc_bytes()
        self.assertTrue(after.startswith(original))
        self.assertIn(b"\r\n# Development Stories\r\n\r\n## US-001\r\n", after)
        self.assertNotIn(b"\n\n## US-001", after.replace(b"\r\n", b"X"))
        draft, _ = self.export_draft()
        draft["stories"][4]["acceptance_criteria"].append("Given a manager requests an export, when the export is large, then the system still completes it.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="upd.json"))
        self.assertEqual(code, 0, result)
        text = self.read_doc_bytes().decode("utf-8")
        self.assertEqual(text.count("\r\n# Development Stories\r\n\r\n## US-001"), 1)
        self.assertEqual(result["updated"], ["US-005"])
        self.assertTrue(text.startswith(original.decode("utf-8")))
        self.assertTrue(os.listdir(self.paths.backups))

    def test_13b_document_without_trailing_newline_and_bom(self):
        with open(self.doc, "wb") as h:
            h.write(b"\xef\xbb\xbf# Title\n\nNo trailing newline")
        self.generate()
        raw = self.read_doc_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf# Title\n\nNo trailing newline\n\n# Development Stories\n"))

    def test_10b_new_stories_get_next_id_and_removed_ids_are_never_reused(self):
        self.generate()
        draft, _ = self.export_draft()
        stories = draft["stories"]
        removed = stories.pop(1)  # US-002 deleted
        stories[0]["source_requirement_ids"] = ["REQ-001", "REQ-002"]
        code, result = self.apply(stories)
        self.assertEqual(code, 1)  # would be removed
        self.assertEqual(result["conflicts"][0]["reason"], "would_be_removed")
        stories[0]["acceptance_criteria"].append("Given a user fails to log in, when the attempt is rejected, then the system shows a generic error.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories, name="rm.json"), "--allow-remove", "US-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"], ["US-002"])
        self.assertIn("US-002", self.read_state()["retired_story_ids"])
        new = make_story("Password reset request", "As a registered user, I want to request a password reset so that I can regain access.",
                         ["Given a registered user requests a reset, when the request is submitted, then the system accepts the request."], ["REQ-002"])
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories + [new], name="add.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["created"], ["US-007"])  # US-002 is retired, US-006 was the highest
        reuse = copy.deepcopy(removed)
        reuse["story_id"] = "US-002"
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories + [new, reuse], name="reuse.json"))
        self.assertEqual(code, 1)
        self.assertIn("never reused", result["error"])

    def test_27_markdown_is_readable_and_matches_the_contract(self):
        self.generate()
        section = self.section_of()
        self.assertTrue(section.startswith("# Development Stories\n\n## US-001\n\n**Summary:** User authentication with registered credentials\n\n**Detailed Description:**\nAs a registered user,"))
        self.assertIn("\n\n**Acceptance Criteria:**\n\n1. Given a registered user provides valid credentials,", section)
        self.assertIn("\n\n2. Given a user provides invalid credentials,", section)
        for field in re.findall(r"^\*\*([^*]+):\*\*", section, re.M):
            self.assertIn(field, ("Summary", "Detailed Description", "Acceptance Criteria"))
        self.assertNotIn("REQ-", section)
        self.assertNotIn("GAP-", section)
        self.assertTrue(all(len(l) <= 80 for l in section.splitlines() if not l.startswith("**Summary")))


class ValidationTests(ProjectCase):
    def check(self, mutate=None, register=None):
        stories = standard_stories()
        draft = {"stories": stories}
        if mutate:
            mutate(draft)
        return validator.validate_draft(draft, {r["requirement_id"]: r for r in REQUIREMENTS}, register)

    def test_26_references_are_checked(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("source_requirement_ids", ["REQ-099"]))
        self.assertTrue(any("REQ-099" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("source_requirement_ids", ["REQ-001", "REQ-001"]))
        self.assertTrue(any("more than once" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("source_requirement_ids", []))
        self.assertTrue(errors)
        register = [make_gap("GAP-001", "High", "x?", ["REQ-001"])]
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("applied_decisions", ["GAP-009"]), register)
        self.assertTrue(any("GAP-009" in e for e in errors))

    def test_structure_ids_and_extra_metadata(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("priority", "High"))
        self.assertTrue(any("unexpected property: priority" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("story_id", "US-1"))
        self.assertTrue(any("story_id" in e for e in errors))
        errors, _ = self.check(lambda d: (d["stories"][0].__setitem__("story_id", "US-001"), d["stories"][1].__setitem__("story_id", "US-001")))
        self.assertTrue(any("duplicate story_id" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("acceptance_criteria", []))
        self.assertTrue(errors)
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("acceptance_criteria", ["a b c", "A B C"]))
        self.assertTrue(any("duplicate acceptance" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("acceptance_criteria", ["1. numbered itself"]))
        self.assertTrue(any("numbering" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("summary", "  "))
        self.assertTrue(errors)

    def test_text_that_cannot_round_trip_as_markdown_is_rejected(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("description", "As a user, I want x.\n\n**Priority:** high"))
        self.assertTrue(any("cannot be written as readable Markdown" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("description", "# Heading inside the description"))
        self.assertTrue(any("cannot be written as readable Markdown" in e for e in errors))

    def test_coverage_requires_a_story_or_a_reason(self):
        errors, _ = self.check(lambda d: d["stories"].pop())
        self.assertTrue(any("REQ-006 is not covered" in e for e in errors))
        errors, _ = self.check(lambda d: (d["stories"].pop(), d.__setitem__("not_covered_requirements", [{"requirement_id": "REQ-006", "reason": "Out of scope for development."}])))
        self.assertEqual(errors, [])
        errors, _ = self.check(lambda d: d.__setitem__("not_covered_requirements", [{"requirement_id": "REQ-006", "reason": "x"}]))
        self.assertTrue(any("also be reported" in e for e in errors))

    def test_vague_wording_is_a_warning_not_an_error(self):
        errors, warnings = self.check(lambda d: d["stories"][0]["acceptance_criteria"].append("The system shall respond as expected."))
        self.assertEqual(errors, [])
        self.assertTrue(any("as expected" in w for w in warnings))

    def test_validator_cli_for_draft_and_document(self):
        path = self.write_draft(standard_stories())
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validator.main([path, "--project-root", self.root])
        self.assertEqual(code, 0, err.getvalue())
        self.generate()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validator.main(["--document", self.doc, "--project-root", self.root])
        self.assertEqual(code, 0, err.getvalue())
        broken = read_text(self.doc).replace("**Summary:**", "**Owner:** Sam\n\n**Summary:**", 1)
        self.write_doc(broken)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = validator.main(["--document", self.doc, "--project-root", self.root])
        self.assertEqual(code, 1)
        self.assertIn("extra story field 'Owner'", err.getvalue())


class BoundaryTests(ProjectCase):
    def test_heading_inside_a_code_block_is_ignored_and_section_appended(self):
        located = common.locate_section(DOCUMENT)
        self.assertEqual(located["state"], "absent")

    def test_content_after_the_section_is_ambiguous(self):
        self.generate()
        self.write_doc(self.read_doc_bytes().decode() + "\n# Appendix\n\nmore\n", newline="")
        before = self.read_doc_bytes()
        code, info = self.run_sync("inspect")
        self.assertEqual(info["status"], "SECTION_AMBIGUOUS")
        self.assertIn("Appendix", info["ambiguity"])
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        self.assertEqual(self.read_doc_bytes(), before)

    def test_duplicate_and_lookalike_headings_are_ambiguous(self):
        for text in (DOCUMENT + "\n# Development Stories\n\n# Development Stories\n", DOCUMENT + "\n# development stories\n",
                     DOCUMENT + "\nDevelopment Stories\n===================\n"):
            with self.assertRaises(common.SectionAmbiguous):
                common.locate_section(text)

    def test_other_top_level_sections_before_the_managed_one_are_untouched(self):
        self.write_doc("# One\n\ntext\n\n# Development Stories\n\n## US-001\n\n**Summary:** x\n\n**Detailed Description:**\ny\n\n**Acceptance Criteria:**\n\n1. z\n")
        located = common.locate_section(read_text(self.doc))
        self.assertEqual(located["prefix"], "# One\n\ntext\n\n")


class EnrichmentTests(ProjectCase):
    DECISION = "Lock the account after five consecutive failed login attempts for 30 minutes."

    def setUp(self):
        super().setUp()
        self.write_gaps([
            make_gap("GAP-001", "Critical", "Should the account lock after failed logins?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "How long is a reset link valid?", ["REQ-002"]),
        ])
        self.generate()

    def resolve(self, gap_id, text, at="2026-10-27T09:00:00+05:30", revise=False):
        with open(os.path.join(self.root, "gaps", "gaps.json"), encoding="utf-8") as h:
            gaps = json.load(h)
        gap = next(g for g in gaps if g["gap_id"] == gap_id)
        gap["decisions_recorded"].append({"decision": text, "recorded_at": at})
        gap["status"] = "resolved"
        self.write_gaps(gaps)

    def set_status(self, gap_id, status):
        with open(os.path.join(self.root, "gaps", "gaps.json"), encoding="utf-8") as h:
            gaps = json.load(h)
        next(g for g in gaps if g["gap_id"] == gap_id)["status"] = status
        self.write_gaps(gaps)

    def enrich_us001(self, reviewed=True):
        draft, _ = self.export_draft()
        draft["stories"][0]["acceptance_criteria"] += [
            "Given a user has five consecutive failed login attempts, when another login attempt is made, then the system locks the account.",
            "Given an account is locked, when 30 minutes have passed, then the account is unlocked.",
        ]
        draft["stories"][0]["applied_decisions"] = ["GAP-001"]
        draft["stories"][2]["applied_decisions"] = []
        draft["decisions_reviewed"] = [{"gap_id": "GAP-001", "outcome": "incorporated"}]
        return draft

    def test_14_15_resolved_gap_enriches_only_the_impacted_stories_and_report_shows_decision(self):
        self.resolve("GAP-001", self.DECISION)
        code, info = self.run_sync("inspect")
        pending = info["pending_decisions"]
        self.assertEqual([(p["gap_id"], p["kind"], p["candidate_story_ids"]) for p in pending], [("GAP-001", "new", ["US-001", "US-003"])])
        self.assertEqual(info["gap_changes"]["newly_resolved"], ["GAP-001"])
        draft = self.enrich_us001()
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name="e.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["updated"], ["US-001"])
        self.assertEqual(len(result["unchanged"]), 5)
        section = self.section_of()
        self.assertIn("3. Given a user has five consecutive failed login attempts,", section)
        self.assertIn("1. Given a registered user provides valid credentials,", section)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["pending_decisions"], [])
        self.assertEqual(self.read_state()["decision_ledger"]["GAP-001"]["outcome"], "incorporated")
        page = read_text(self.paths.report)
        self.assertIn(self.DECISION, page)
        self.assertIn("Incorporated in stories", page)

    def test_16_resolved_gap_without_story_change_still_reaches_the_report(self):
        self.resolve("GAP-002", "A reset link is valid for 24 hours.")
        before = self.read_doc_bytes()
        draft, _ = self.export_draft()
        extra = {"decisions_reviewed": [{"gap_id": "GAP-002", "outcome": "no_change_required"}]}
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], extra, name="n.json"))
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertTrue(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), before)
        page = read_text(self.paths.report)
        self.assertIn("A reset link is valid for 24 hours.", page)
        self.assertIn("Reviewed: no story change required", page)

    def test_17_rerunning_enrichment_changes_nothing(self):
        self.resolve("GAP-001", self.DECISION)
        draft = self.enrich_us001()
        path = self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name="e.json")
        self.assertEqual(self.run_sync("apply", "--draft", path)[0], 0)
        doc, state = self.read_doc_bytes(), self.read_state()
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertFalse(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(self.read_state(), state)

    def test_18_a_revised_decision_is_pending_again(self):
        self.resolve("GAP-001", self.DECISION)
        draft = self.enrich_us001()
        self.run_sync("apply", "--draft", self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name="e.json"))
        self.resolve("GAP-001", "Lock the account after three failed attempts for 15 minutes.", at="2026-10-28T09:00:00+05:30")
        code, info = self.run_sync("inspect")
        self.assertEqual([(p["gap_id"], p["kind"]) for p in info["pending_decisions"]], [("GAP-001", "revised")])
        self.assertIn("three failed attempts", info["pending_decisions"][0]["decision"])

    def test_19_reopening_does_not_delete_criteria_and_needs_acknowledgement(self):
        self.resolve("GAP-001", self.DECISION)
        draft = self.enrich_us001()
        self.run_sync("apply", "--draft", self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name="e.json"))
        self.set_status("GAP-001", "open")
        code, info = self.run_sync("inspect")
        self.assertEqual(info["gap_changes"]["reopened"], ["GAP-001"])
        self.assertEqual(info["pending_decisions"], [])
        self.assertIn("five consecutive failed login attempts", flat(self.section_of()))
        draft, _ = self.export_draft()
        path = self.write_draft(draft["stories"], name="same.json")
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 1)
        self.assertEqual(result["unacknowledged_changes"]["reopened_gaps"], ["GAP-001"])
        code, result = self.run_sync("apply", "--draft", path, "--acknowledge-changes")
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertIn("five consecutive failed login attempts", flat(self.section_of()))
        code, info = self.run_sync("inspect")
        self.assertEqual(info["gap_changes"]["reopened"], [])

    def test_skipped_gap_is_never_a_decision(self):
        self.set_status("GAP-002", "skipped")
        code, info = self.run_sync("inspect")
        self.assertEqual(info["pending_decisions"], [])
        self.assertEqual(info["gap_changes"]["newly_skipped"], ["GAP-002"])

    def test_invalid_gap_register_requires_an_explicit_choice(self):
        with open(os.path.join(self.root, "gaps", "gaps.json"), "w", encoding="utf-8") as h:
            h.write("{not json")
        code, result = self.run_sync("inspect")
        self.assertEqual(result["gaps"]["status"], "INVALID")
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "GAPS_INVALID")
        # Proceeding without gap context preserves the recorded traceability and claims nothing new.
        before = self.read_state()
        code, result = self.run_sync("export", "--ignore-gaps")
        self.assertEqual(code, 0)
        code, result = self.run_sync("apply", "--ignore-gaps", "--draft", self.write_draft(result["draft"]["stories"], name="i.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read_state()["decision_ledger"], before["decision_ledger"])
        self.assertEqual(self.read_state()["stories"][0]["related_gap_ids"], before["stories"][0]["related_gap_ids"])


class ManualEditTests(ProjectCase):
    def setUp(self):
        super().setUp()
        self.generate()

    def edit_section(self, old, new):
        text = self.read_doc_bytes().decode("utf-8")
        self.assertIn(old, text)
        self.write_doc(text.replace(old, new, 1))

    def test_20_manual_edit_is_detected_with_detail(self):
        self.edit_section("**Summary:** Password reset by email", "**Summary:** Password reset by e-mail link")
        text = self.read_doc_bytes().decode("utf-8")
        self.write_doc(text.replace("1. Given a registered user requests a reset,", "1. Given a registered user requests a reset,\n   (edited)\n\n2. A second manual criterion is added.\n\n3. Given a registered user requests a reset,", 1))
        code, info = self.run_sync("inspect")
        changes = info["manual_changes"]
        self.assertTrue(changes["section_modified"])
        self.assertEqual(changes["edited"], ["US-002"])
        self.assertTrue(changes["edited_details"]["US-002"]["summary_changed"])
        self.assertFalse(changes["edited_details"]["US-002"]["description_changed"])
        self.assertIn("A second manual criterion is added.", changes["edited_details"]["US-002"]["criteria_added"])

    def test_deletion_and_id_change_are_detected(self):
        text = self.read_doc_bytes().decode("utf-8")
        start = text.index("## US-004")
        end = text.index("## US-005")
        self.write_doc(text[:start] + text[end:])
        self.edit_section("## US-006", "## US-016")
        code, info = self.run_sync("inspect")
        changes = info["manual_changes"]
        self.assertEqual(changes["removed"], ["US-004", "US-006"])
        self.assertEqual(changes["added"], ["US-016"])
        self.assertEqual(changes["id_changes"], [{"from": "US-006", "to": "US-016"}])

    def test_21_edits_outside_the_section_are_preserved(self):
        text = self.read_doc_bytes().decode("utf-8")
        self.write_doc(text.replace("Managers export reports.", "Managers export reports in CSV.", 1))
        code, info = self.run_sync("inspect")
        self.assertTrue(info["manual_changes"]["outside_section_modified"])
        self.assertFalse(info["manual_changes"]["section_modified"])
        draft, ctx = self.export_draft()
        draft["stories"][5]["acceptance_criteria"].append("Given a user saves an empty name, when the profile is saved, then the system rejects it.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="o.json"))
        self.assertEqual(code, 0, result)
        self.assertIn("Managers export reports in CSV.", self.read_doc_bytes().decode())

    def test_manual_edit_conflicts_are_not_overwritten_without_consent(self):
        draft, _ = self.export_draft()
        self.edit_section("**Summary:** Users update their profile", "**Summary:** Users maintain their profile")
        draft["stories"][5]["acceptance_criteria"].append("Given a user saves an empty name, when the profile is saved, then the system rejects it.")
        path = self.write_draft(draft["stories"], name="c.json")
        before = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 1)
        self.assertEqual(result["conflicts"][0]["story_id"], "US-006")
        self.assertEqual(result["conflicts"][0]["reason"], "manual_edit")
        self.assertEqual(self.read_doc_bytes(), before)
        code, result = self.run_sync("apply", "--draft", path, "--overwrite", "US-006")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["overwritten_manual_edits"], ["US-006"])

    def test_a_draft_built_from_the_edited_document_keeps_the_edit(self):
        self.edit_section("**Summary:** Users update their profile", "**Summary:** Users maintain their profile")
        draft, _ = self.export_draft()
        self.assertEqual(draft["stories"][5]["summary"], "Users maintain their profile")
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in twice, when the second login occurs, then the system keeps one session.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="k.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["updated"], ["US-001"])
        self.assertIn("Users maintain their profile", self.read_doc_bytes().decode())

    def test_extra_metadata_blocks_updates_until_reconciled(self):
        self.edit_section("**Summary:** Password reset by email", "**Priority:** High\n\n**Summary:** Password reset by email")
        code, info = self.run_sync("inspect")
        self.assertTrue(any("extra story field 'Priority'" in p for p in info["section"]["problems"]))
        before = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        code, result = self.run_sync("accept")
        self.assertEqual(code, 1)
        self.assertEqual(self.read_doc_bytes(), before)

    def test_accept_records_manual_edits_without_touching_the_document(self):
        self.edit_section("**Summary:** Password reset by email", "**Summary:** Password reset by e-mail link")
        text = self.read_doc_bytes().decode("utf-8")
        start = text.index("## US-004")
        end = text.index("## US-005")
        self.write_doc(text[:start] + text[end:])
        before = self.read_doc_bytes()
        code, result = self.run_sync("accept")
        self.assertEqual(code, 1)
        self.assertEqual(result["deleted"], ["US-004"])
        code, result = self.run_sync("accept", "--retire", "US-004")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read_doc_bytes(), before)
        state = self.read_state()
        self.assertIn("US-004", state["retired_story_ids"])
        self.assertEqual(len(state["stories"]), 5)
        code, info = self.run_sync("inspect")
        self.assertFalse(info["manual_changes"]["section_modified"])
        self.assertEqual(info["manual_changes"]["edited"], [])
        self.assertIn("e-mail link", read_text(self.paths.report))

    def test_accept_requires_mappings_for_manually_added_stories_and_supports_rename(self):
        text = self.read_doc_bytes().decode("utf-8")
        added = ("\n\n## US-020\n\n**Summary:** Guest checkout\n\n**Detailed Description:**\nAs a guest, I want to check out so that I can buy.\n\n"
                 "**Acceptance Criteria:**\n\n1. Given a guest has items, when the guest checks out, then the system takes the order.\n")
        self.write_doc(text.rstrip("\n") + added)
        code, result = self.run_sync("accept")
        self.assertEqual(code, 1)
        self.assertEqual(result["needs_mapping"], ["US-020"])
        mapping = os.path.join(self.scratch, "map.json")
        with open(mapping, "w") as h:
            json.dump({"US-020": {"source_requirement_ids": ["REQ-006"]}}, h)
        code, result = self.run_sync("accept", "--mappings", mapping)
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read_state()["highest_story_number"], 20)
        # Rename keeps the mapping and retires the old ID.
        self.edit_section("## US-005", "## US-025")
        code, result = self.run_sync("accept", "--rename", "US-005=US-025")
        self.assertEqual(code, 0, result)
        state = self.read_state()
        entry = next(e for e in state["stories"] if e["story_id"] == "US-025")
        self.assertEqual(entry["source_requirement_ids"], ["REQ-005"])
        self.assertIn("US-005", state["retired_story_ids"])

    def test_recovery_from_a_missing_state_file(self):
        os.unlink(self.paths.state)
        code, info = self.run_sync("inspect", "--target", self.doc)
        self.assertEqual(info["state"]["status"], "NONE")
        self.assertTrue(info["recoverable_from_document"])
        code, result = self.run_sync("apply", "--target", self.doc, "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)  # no baseline: stories are not overwritten silently
        self.assertTrue(all(c["reason"] in ("no_baseline",) for c in result["conflicts"][:1]) or result["conflicts"])
        mapping = {f"US-00{i}": {"source_requirement_ids": [f"REQ-00{i}"]} for i in range(1, 7)}
        path = os.path.join(self.scratch, "m.json")
        with open(path, "w") as h:
            json.dump(mapping, h)
        code, result = self.run_sync("accept", "--target", self.doc, "--mappings", path)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["recovered_from_document"])
        self.assertEqual(len(self.read_state()["stories"]), 6)


class SafetyTests(ProjectCase):
    def test_22_target_must_be_chosen_and_be_markdown(self):
        code, info = self.run_sync("inspect")
        self.assertEqual(info["status"], "TARGET_REQUIRED")
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        txt = os.path.join(self.root, "notes.txt")
        with open(txt, "w") as handle:
            handle.write("x")
        code, info = self.run_sync("inspect", "--target", txt)
        self.assertEqual(info["status"], "TARGET_NOT_MARKDOWN")
        code, info = self.run_sync("inspect", "--target", os.path.join(self.root, "missing.md"))
        self.assertEqual(info["status"], "DOCUMENT_MISSING")

    def test_missing_or_invalid_atomic_requirements_stop_everything(self):
        os.unlink(self.paths.requirements)
        code, info = self.run_sync("inspect", "--target", self.doc)
        self.assertEqual(info["status"], "INPUT_MISSING")
        code, result = self.run_sync("apply", "--target", self.doc, "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.paths.state))
        self.write_requirements([{"requirement_id": "REQ-001", "title": "x"}])
        code, info = self.run_sync("inspect", "--target", self.doc)
        self.assertEqual(info["status"], "INPUT_INVALID")

    def test_23_failed_write_keeps_the_original_document_and_state(self):
        self.generate()
        before_doc, before_state = self.read_doc_bytes(), self.read_state()
        draft, _ = self.export_draft()
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in, when the login succeeds, then the system records the time.")
        path = self.write_draft(draft["stories"], name="f.json")
        real = common.atomic_write_bytes

        def failing(target, payload, prefix=".story-"):
            if os.path.normcase(target) == os.path.normcase(self.doc):
                raise PermissionError("simulated failure")
            return real(target, payload, prefix=prefix)

        with mock.patch.object(common, "atomic_write_bytes", failing):
            code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 2)
        self.assertIn("simulated failure", result["error"])
        self.assertEqual(self.read_doc_bytes(), before_doc)
        self.assertEqual(self.read_state(), before_state)

    def test_failed_verification_restores_the_previous_document(self):
        self.generate()
        before = self.read_doc_bytes()
        draft, _ = self.export_draft()
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in, when the login succeeds, then the system records the time.")
        path = self.write_draft(draft["stories"], name="v.json")
        with mock.patch.object(sync, "verify_written", return_value=["simulated read-back mismatch"]):
            code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 1)
        self.assertIn("restored", result["error"])
        self.assertEqual(self.read_doc_bytes(), before)

    def test_24_concurrent_modification_is_never_overwritten(self):
        self.generate()
        draft, result = self.export_draft()
        sha = result["source_sha256"]
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in, when the login succeeds, then the system records the time.")
        path = self.write_draft(draft["stories"], name="cc.json")
        # Changed between inspect and apply.
        text = self.read_doc_bytes().decode()
        self.write_doc(text.replace("Managers export reports.", "Managers export reports daily.", 1))
        changed = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", path, "--expected-source-sha256", sha)
        self.assertEqual(code, 1)
        self.assertIn("concurrent", result["error"])
        self.assertEqual(self.read_doc_bytes(), changed)
        # Changed while the update was being prepared.
        draft, result = self.export_draft()
        sha = result["source_sha256"]
        real_backup = sync.make_backup

        def sneaky(paths, target, raw):
            backup = real_backup(paths, target, raw)
            with open(target, "ab") as handle:
                handle.write(b"\nsneaky edit\n")
            return backup

        draft["stories"][0]["acceptance_criteria"].append("Given a user logs out, when the logout completes, then the system ends the session.")
        with mock.patch.object(sync, "make_backup", sneaky):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="c2.json"), "--expected-source-sha256", sha)
        self.assertEqual(code, 1)
        self.assertIn("concurrent", result["error"])
        self.assertTrue(self.read_doc_bytes().endswith(b"\nsneaky edit\n"))

    def test_25_requirement_changes_are_reported_and_nothing_is_deleted_silently(self):
        self.generate()
        changed = [dict(r) for r in REQUIREMENTS if r["requirement_id"] != "REQ-005"]
        changed[1]["description"] = "The system shall allow users to reset their password by email or SMS."
        changed.append({"requirement_id": "REQ-007", "title": "Dark Mode", "description": "The system shall offer a dark colour theme."})
        self.write_requirements(changed)
        code, info = self.run_sync("inspect")
        changes = info["requirement_changes"]
        self.assertEqual((changes["added"], changes["changed"], changes["removed"]), (["REQ-007"], ["REQ-002"], ["REQ-005"]))
        self.assertEqual(changes["affected_story_ids"], ["US-002", "US-005"])
        self.assertEqual(info["uncovered_requirements"], ["REQ-007"])
        draft, _ = self.export_draft()
        dark = make_story("Dark colour theme", "As a user, I want a dark colour theme so that I can read comfortably at night.",
                          ["Given a user selects the dark theme, when a page loads, then the system shows the dark colours."], ["REQ-007"])
        stories = [s for s in draft["stories"] if s["story_id"] != "US-005"] + [dark]
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories, name="r.json"), "--acknowledge-changes")
        self.assertEqual(code, 1)
        self.assertEqual(result["conflicts"][0]["reason"], "would_be_removed")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"] + [dark], name="r2.json"), "--acknowledge-changes")
        self.assertEqual(code, 1)  # US-005 still points at a removed requirement
        self.assertTrue(any("REQ-005" in d for d in result["details"]), result)
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories, name="r3.json"), "--allow-remove", "US-005", "--acknowledge-changes")
        self.assertEqual(code, 0, result)
        self.assertIn("US-005", self.read_state()["retired_story_ids"])

    def test_state_failure_after_document_write_is_reported(self):
        self.generate()
        draft, _ = self.export_draft()
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in, when the login succeeds, then the system records the time.")
        path = self.write_draft(draft["stories"], name="s.json")
        with mock.patch.object(sync, "save_state", side_effect=common.IOFailure("disk full")):
            code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 4)
        self.assertFalse(result["ok"])
        self.assertIn("accept", result["warning"])
        self.assertIn("records the time", flat(self.read_doc_bytes().decode()))


class SummaryAndCliTests(ProjectCase):
    def test_summary_reports_real_counts(self):
        self.write_gaps([
            make_gap("GAP-001", "Critical", "Lockout?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "Reset validity?", ["REQ-002"], status="skipped"),
        ])
        stories = standard_stories()[:5]
        extra = {"not_covered_requirements": [{"requirement_id": "REQ-006", "reason": "Out of scope for development."}]}
        self.generate(stories, extra)
        code, result = self.run_sync("summary")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["stories"], 5)
        self.assertEqual(result["requirements"]["analysed"], 6)
        self.assertEqual(result["requirements"]["covered"], 5)
        self.assertEqual(result["requirements"]["not_covered"][0]["requirement_id"], "REQ-006")
        self.assertEqual(result["requirements"]["uncovered_unexplained"], [])
        self.assertEqual(result["gaps"]["referenced"], {"open": 1, "skipped": 1, "resolved": 0})
        self.assertTrue(result["validation"]["passed"])
        self.assertTrue(result["in_sync"])
        self.assertTrue(result["report"]["exists"])

    def test_summary_without_stories_is_refused(self):
        code, result = self.run_sync("summary", "--target", self.doc)
        self.assertEqual(code, 1)

    def test_scripts_run_as_commands_from_another_directory(self):
        import subprocess
        draft = self.write_draft(standard_stories())
        base = [sys.executable, "-I"]
        run = lambda *a: subprocess.run(base + list(a), cwd=self.tmp, capture_output=True, text=True, encoding="utf-8")
        checked = run(os.path.join(SCRIPTS, "validate-development-stories.py"), draft, "--project-root", self.root)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        applied = run(os.path.join(SCRIPTS, "sync-development-stories.py"), "apply", "--project-root", self.root, "--target", self.doc, "--draft", draft)
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        self.assertTrue(json.loads(applied.stdout)["report"]["generated"])
        report = run(os.path.join(SCRIPTS, "generate-phase3-report.py"), "--project-root", self.root)
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn("report/phase3-report.html", report.stdout)
        doc = run(os.path.join(SCRIPTS, "validate-development-stories.py"), "--document", self.doc, "--project-root", self.root)
        self.assertEqual(doc.returncode, 0, doc.stderr)


class ReportTests(ProjectCase):
    def setUp(self):
        super().setUp()
        decisions = [{"decision": "Locks after <b>five</b> attempts & 30 minutes.", "recorded_at": "2026-10-26T10:00:00+05:30"},
                     {"decision": "Locks after three attempts.", "recorded_at": "2026-10-27T10:00:00+05:30"}]
        self.write_gaps([
            make_gap("GAP-001", "Critical", "Lockout <script>alert(1)</script> policy?", ["REQ-001"], status="resolved", decisions=decisions),
            make_gap("GAP-002", "High", "Reset validity?", ["REQ-002"]),
            make_gap("GAP-003", "Low", "Export formats?", ["REQ-005"], status="skipped"),
        ])

    def page(self):
        return read_text(self.paths.report)

    def test_report_creates_directory_with_all_sections_and_counts(self):
        self.assertFalse(os.path.exists(self.paths.report_dir))
        result = self.generate()
        self.assertTrue(result["report"]["generated"])
        page = self.page()
        for marker in ("overview", "stories", "gaps-open", "gaps-resolved", "gaps-skipped", "decisions", "traceability"):
            self.assertIn(f'id="{marker}"', page)
        for story_id in ("US-001", "US-006"):
            self.assertIn(f'id="{story_id}"', page)
        self.assertIn("Given a registered user provides valid credentials", page)
        open_section = page.split('id="gaps-open"')[1].split("<section")[0]
        resolved_section = page.split('id="gaps-resolved"')[1].split("<section")[0]
        skipped_section = page.split('id="gaps-skipped"')[1].split("<section")[0]
        self.assertIn("GAP-002", open_section)
        self.assertNotIn("GAP-001", open_section)
        self.assertIn("GAP-001", resolved_section)
        self.assertIn("GAP-003", skipped_section)
        self.assertIn("Current decision", resolved_section)
        self.assertIn("Earlier decision", resolved_section)
        self.assertIn("2026-10-27T10:00:00+05:30", resolved_section)
        decisions = page.split('id="decisions"')[1].split("<section")[0]
        self.assertIn("GAP-001", decisions)
        self.assertNotIn("GAP-002", decisions)  # no decision recorded for it
        self.assertIn("1 open, 1 skipped, 1 resolved", page)
        self.assertIn('data-generated="', page)

    def test_story_entries_contain_only_the_four_fields(self):
        self.generate()
        story = self.page().split('id="US-001"')[1].split("</article>")[0]
        self.assertNotIn("REQ-", story)
        self.assertNotIn("GAP-", story)
        self.assertEqual(re.findall(r"<h4>([^<]+)</h4>", story), ["Detailed Description", "Acceptance Criteria"])

    def test_08_source_text_is_escaped(self):
        self.write_requirements([dict(r) for r in REQUIREMENTS])
        stories = standard_stories()
        stories[0]["summary"] = "Login <img src=x onerror=alert(1)> & more"
        stories[0]["acceptance_criteria"][0] = "Given <script>alert('x')</script> when 1 < 2 then the system responds in 3 seconds."
        self.generate(stories)
        page = self.page()
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", page)
        self.assertNotIn("<b>five</b>", page)
        self.assertIn("&lt;b&gt;five&lt;/b&gt; attempts &amp; 30 minutes.", page)
        self.assertEqual(len(re.findall(r"<script>", page)), 1)  # only the report's own script

    def test_07_missing_register_never_fabricates_gaps(self):
        os.unlink(os.path.join(self.root, "gaps", "gaps.json"))
        self.generate()
        page = self.page()
        self.assertIn("Gap data is unavailable", page)
        self.assertNotIn("GAP-", page)
        self.assertIn("No gaps or decisions are shown", page)

    def test_11_no_external_dependencies(self):
        self.generate()
        page = self.page()
        self.assertNotRegex(page, r"https?://")
        self.assertNotRegex(page, r"<(?:link|img|iframe)\b")
        self.assertNotRegex(page, r"<script[^>]+src=")

    def test_09_report_failure_keeps_the_previous_report_stories_and_state(self):
        self.generate()
        good = self.page()
        doc, state = self.read_doc_bytes(), self.read_state()
        real = common.atomic_write_bytes

        def failing(target, payload, prefix=".story-"):
            if os.path.normcase(target) == os.path.normcase(self.paths.report):
                raise PermissionError("report locked")
            return real(target, payload, prefix=prefix)

        draft, _ = self.export_draft()
        draft["stories"][0]["acceptance_criteria"].append("Given a user logs in, when the login succeeds, then the system records the time.")
        with mock.patch.object(common, "atomic_write_bytes", failing):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="rf.json"))
        self.assertEqual(code, 3)
        self.assertTrue(result["ok"])
        self.assertFalse(result["report"]["generated"])
        self.assertIn("stale", result["warning"])
        self.assertEqual(self.page(), good)
        self.assertIn("records the time", flat(self.read_doc_bytes().decode()))
        self.assertNotEqual(self.read_doc_bytes(), doc)
        self.assertEqual(len(self.read_state()["stories"]), len(state["stories"]))
        code, result = self.run_sync("regenerate-report")
        self.assertEqual(code, 0, result)
        self.assertIn("records the time", self.page())

    def test_12_report_only_regeneration_changes_nothing_else(self):
        self.generate()
        doc, state = self.read_doc_bytes(), read_binary(self.paths.state)
        backups = os.listdir(self.paths.backups) if os.path.isdir(self.paths.backups) else []
        decisions = read_binary(os.path.join(self.root, "gaps", "gaps.json"))
        code, result = self.run_sync("regenerate-report")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(read_binary(self.paths.state), state)
        self.assertEqual(read_binary(os.path.join(self.root, "gaps", "gaps.json")), decisions)
        self.assertEqual(os.listdir(self.paths.backups) if os.path.isdir(self.paths.backups) else [], backups)

    def test_06_manual_edits_reconciled_by_accept_reach_the_next_report(self):
        self.generate()
        text = self.read_doc_bytes().decode("utf-8")
        self.write_doc(text.replace("Managers export reports", "Managers export reports", 1).replace("**Summary:** Managers export reports", "**Summary:** Managers export reports as CSV", 1))
        self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        self.assertIn("Out of sync", self.page())
        code, result = self.run_sync("accept")
        self.assertEqual(code, 0, result)
        page = self.page()
        self.assertIn("Managers export reports as CSV", page)
        self.assertIn("In sync", page)

    def test_report_without_state_explains_itself(self):
        code, result = self.run_sync("regenerate-report")
        self.assertEqual(code, 1)
        self.assertIn("generate-stories", result["report"]["message"])
        self.assertFalse(os.path.exists(self.paths.report))

    def test_traceability_section_flags_discrepancies_instead_of_fabricating(self):
        self.generate()
        state = self.read_state()
        state["stories"].append(dict(state["stories"][0], story_id="US-050"))
        with open(self.paths.state, "w", encoding="utf-8") as h:
            json.dump(state, h)
        self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        self.assertIn("US-050 has a recorded mapping but is not in the document", self.page())

    def test_timestamp_changes_on_regeneration(self):
        self.generate()
        first = re.search(r'data-generated="([^"]+)"', self.page()).group(1)
        with mock.patch.object(common, "now_stamp", return_value="2030-01-01T00:00:00+00:00"):
            self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        self.assertIn('data-generated="2030-01-01T00:00:00+00:00"', self.page())
        self.assertNotEqual(first, "2030-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
