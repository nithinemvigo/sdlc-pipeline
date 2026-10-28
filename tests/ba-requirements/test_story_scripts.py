"""Tests for the Phase 3 scripts (standard library only).

Run from the plugin root:
    python -m unittest discover -s tests -v

Judgements that depend on the model (story decomposition, wording, whether a decision changes a
story) are specified in the agent, skills and rules and cannot be unit-tested. Everything the
scripts enforce is covered here: the ultra-lean stories in the requirements document, the single
consolidated stories/detailed_stories.md, their synchronisation, and the report built from it.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
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


def make_story(summary, lean, sources, story_id=None, applied=None, **detail):
    """A draft story: the ultra-lean criteria and a detailed story (defaults derived from the summary)."""
    detailed = {
        "description": f"As a user, I want to {summary.lower()}, so that I can achieve the outcome.",
        "functional_behaviour": [f"The system supports: {summary}."],
        "acceptance_criteria": [f"The system completes a request to {summary.lower()}."],
    }
    detailed.update(detail)
    return {
        "story_id": story_id, "summary": summary, "lean_acceptance_criteria": list(lean), "detailed": detailed,
        "source_requirement_ids": sources, "applied_decisions": applied or [],
    }


def add_criterion(story, lean_text, detailed_text=None):
    """Add a criterion the way the agent does when a story changes: to the detailed story first, then to the lean story."""
    story["detailed"]["acceptance_criteria"].append(detailed_text or lean_text)
    if lean_text:
        story["lean_acceptance_criteria"] = [" ".join(story["lean_acceptance_criteria"] + [lean_text])]


def standard_stories():
    return [
        make_story("User Login", ["Registered users can log in using valid credentials, and invalid credentials are rejected with the defined error response."], ["REQ-001"],
                   description="As a registered user, I want to log in using my registered email address and password so that I can access my account.",
                   preconditions=["The user has a registered account."],
                   functional_behaviour=["The system authenticates the user against the registered email address and password."],
                   business_rules=["A rejected login does not say which of the two values was wrong."],
                   acceptance_criteria=["A registered user who submits valid credentials is authenticated.",
                                        "A login attempt with invalid credentials is rejected."],
                   scenarios=["An unknown email address is rejected with the same response as a wrong password."],
                   non_functional_requirements=["Login completes within 2 seconds under normal load."]),
        make_story("Password Reset", ["Registered users can reset their password by email."], ["REQ-002"],
                   description="As a registered user, I want to reset my password by email so that I can regain access to my account.",
                   acceptance_criteria=["A reset request from a registered user sends a reset message to the registered email address."]),
        make_story("Session Timeout", ["Inactive sessions are ended."], ["REQ-003"],
                   description="As a registered user, I want inactive sessions to end so that my account stays protected.",
                   acceptance_criteria=["A session that reaches the inactivity limit is ended."]),
        make_story("Audit Log", ["Security-relevant events are recorded."], ["REQ-004"],
                   description="As an administrator, I want security-relevant events recorded so that I can review them.",
                   acceptance_criteria=["Every security-relevant event is recorded."]),
        make_story("Report Export", ["Managers can export reports as a file."], ["REQ-005"],
                   description="As a manager, I want to export reports so that I can share them.",
                   acceptance_criteria=["A manager who requests an export of a report receives it as a file."]),
        make_story("Profile Update", ["Users can update their profile details."], ["REQ-006"],
                   description="As a user, I want to update my profile so that my details stay correct.",
                   acceptance_criteria=["Saved profile changes are stored."]),
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

    def read_detailed(self):
        return read_text(self.paths.detailed_file)

    def edit_detailed(self, old, new):
        text = self.read_detailed()
        self.assertIn(old, text)
        with open(self.paths.detailed_file, "w", encoding="utf-8", newline="") as h:
            h.write(text.replace(old, new, 1))

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

    def edit_section(self, old, new):
        text = self.read_doc_bytes().decode("utf-8")
        self.assertIn(old, text)
        self.write_doc(text.replace(old, new, 1))


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
        self.assertFalse(os.path.exists(self.paths.detailed_file))
        self.assertNotIn("# Development Stories\n\n## US", self.read_doc_bytes().decode())

    def test_06_07_one_story_many_requirements_and_one_requirement_many_stories(self):
        stories = standard_stories()
        stories[0]["source_requirement_ids"] = ["REQ-001", "REQ-003"]
        stories[2]["source_requirement_ids"] = ["REQ-003", "REQ-001"]
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
        before, detailed_before = self.read_doc_bytes(), read_binary(self.paths.detailed_file)
        state_before = self.read_state()
        draft, _ = self.export_draft()
        path = self.write_draft(draft["stories"], name="again.json")
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertFalse(result["detailed_file_changed"])
        self.assertFalse(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), before)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed_before)
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
        self.assertIn("\r\n# Development Stories\r\n\r\n## US-001 — User Login\r\n".encode("utf-8"), after)
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][4], "Large reports can be exported.", "A large export is still completed.")
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
        add_criterion(stories[0], "Failed logins show a generic error.", "A rejected login attempt shows a generic error.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories, name="rm.json"), "--allow-remove", "US-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["removed"], ["US-002"])
        self.assertEqual(result["detailed_removed"], ["US-002"])
        self.assertNotIn("## US-002", self.read_detailed())
        self.assertIn("US-002", self.read_state()["retired_story_ids"])
        new = make_story("Password Reset Request", ["Registered users can request a password reset."], ["REQ-002"])
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories + [new], name="add.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["created"], ["US-007"])  # US-002 is retired, US-006 was the highest
        reuse = copy.deepcopy(removed)
        reuse["story_id"] = "US-002"
        code, result = self.run_sync("apply", "--draft", self.write_draft(stories + [new, reuse], name="reuse.json"))
        self.assertEqual(code, 1)
        self.assertIn("never reused", result["error"])

    def test_27_the_document_holds_only_id_summary_and_criteria(self):
        self.generate()
        section = self.section_of()
        self.assertTrue(section.startswith(
            "# Development Stories\n\n## US-001 — User Login\n\n**Acceptance Criteria:** "
            "Registered users can log in using valid credentials, and invalid credentials are rejected with the defined error response.\n\n## US-002 — Password Reset\n"
        ), section[:400])
        self.assertEqual(re.findall(r"^\*\*([^*]+):\*\*", section, re.M), ["Acceptance Criteria"] * 6)
        self.assertEqual(re.findall(r"^## (US-\d+) — ", section, re.M), [f"US-00{n}" for n in range(1, 7)])
        for forbidden in ("REQ-", "GAP-", "Given ", "Description", "Preconditions", "within 2 seconds", "Non-Functional"):
            self.assertNotIn(forbidden, section)
        stories, problems = common.parse_section(section)
        self.assertEqual(problems, [])
        self.assertEqual(stories[0]["acceptance_criteria"],
                         ["Registered users can log in using valid credentials, and invalid credentials are rejected with the defined error response."])


class ConsolidatedDetailedStoriesTests(ProjectCase):
    """All detailed stories live in the single file stories/detailed_stories.md."""

    def test_all_detailed_stories_are_in_one_file_and_no_per_story_files_exist(self):
        self.generate()
        self.assertEqual(sorted(os.listdir(self.paths.stories_dir)), ["backups", "detailed_stories.md", "story-generation-state.json"])
        self.assertFalse(os.path.exists(self.paths.legacy_detailed_dir))
        self.assertFalse(os.path.exists(self.paths.legacy_lean_file))
        text = self.read_detailed()
        self.assertTrue(text.startswith("# Detailed Stories\n\n<!--"))
        self.assertEqual(re.findall(r"^## (US-\d+) — (.+)$", text, re.M),
                         [("US-001", "User Login"), ("US-002", "Password Reset"), ("US-003", "Session Timeout"),
                          ("US-004", "Audit Log"), ("US-005", "Report Export"), ("US-006", "Profile Update")])

    def test_every_story_has_the_same_field_order_and_empty_optional_fields_are_left_out(self):
        self.generate()
        order = ["Description", "Preconditions", "Functional Behaviour", "Business Rules", "Acceptance Criteria",
                 "Alternate and Error Scenarios", "Non-Functional Requirements", "Dependencies"]
        required = ["Description", "Functional Behaviour", "Acceptance Criteria"]
        blocks = re.split(r"^## US-\d+ — .*$", self.read_detailed(), flags=re.M)[1:]
        self.assertEqual(len(blocks), 6)
        for block in blocks:
            labels = re.findall(r"^\*\*([^*]+):\*\*", block, re.M)
            self.assertEqual(labels, sorted(labels, key=order.index))
            self.assertTrue(set(required) <= set(labels))
        first = blocks[0]
        self.assertEqual(re.findall(r"^\*\*([^*]+):\*\*", first, re.M),
                         ["Description", "Preconditions", "Functional Behaviour", "Business Rules", "Acceptance Criteria",
                          "Alternate and Error Scenarios", "Non-Functional Requirements"])
        self.assertIn("**Non-Functional Requirements:**\n- Login completes within 2 seconds under normal load.", first)
        self.assertIn("**Preconditions:**\n- The user has a registered account.", first)
        self.assertIn("**Acceptance Criteria:**\n1. A registered user who submits valid credentials is authenticated.", first)
        self.assertIn("\n2. A login attempt with invalid credentials is rejected.", first)
        self.assertEqual(re.findall(r"^\*\*([^*]+):\*\*", blocks[1], re.M), ["Description", "Functional Behaviour", "Acceptance Criteria"])
        self.assertNotIn("Not specified.", self.read_detailed())
        self.assertNotIn("Given ", self.read_detailed())
        self.assertNotIn("REQ-", self.read_detailed())
        self.assertNotIn("GAP-", self.read_detailed())

    def test_dependencies_on_other_stories_carry_the_story_id(self):
        stories = standard_stories()
        stories[1]["detailed"]["dependencies"] = ["[[User Login]]: the user must be logged in to request a reset.", "The mail service delivers the reset message."]
        stories[0]["detailed"]["dependencies"] = ["[[Profile Update]]: the profile holds the registered email address."]
        self.generate(stories)
        text = self.read_detailed()
        self.assertIn("**Dependencies:**\n- US-001 (User Login): the user must be logged in to request a reset.\n- The mail service delivers the reset message.", text)
        self.assertIn("**Dependencies:**\n- US-006 (Profile Update): the profile holds the registered email address.", text)
        self.assertNotIn("[[", text)
        page = read_text(self.paths.report)
        self.assertIn("US-001 (User Login): the user must be logged in to request a reset.", page)

    def test_a_dependency_on_a_new_story_resolves_and_re_applying_changes_nothing(self):
        self.generate()
        draft, _ = self.export_draft()
        extra = make_story("Account Deletion", ["Users can delete their account."], ["REQ-006"],
                           description="As a user, I want to delete my account so that my data is removed.",
                           dependencies=["[[Profile Update]]: the profile is the data that is removed.", "[[Account Deletion Audit]]: the deletion is recorded."])
        audit = make_story("Account Deletion Audit", ["Account deletions are recorded."], ["REQ-004"],
                           description="As an administrator, I want deletions recorded so that I can review them.")
        draft["stories"] += [extra, audit]
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="dep.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["created"], ["US-007", "US-008"])
        self.assertIn("- US-006 (Profile Update): the profile is the data that is removed.\n- US-008 (Account Deletion Audit): the deletion is recorded.", self.read_detailed())
        again, _ = self.export_draft()
        code, result = self.run_sync("apply", "--draft", self.write_draft(again["stories"], name="again.json"))
        self.assertEqual(code, 0, result)
        self.assertFalse(result["detailed_file_changed"])
        self.assertEqual(result["detailed_changed"], [])

    def test_a_file_with_not_specified_fields_from_an_earlier_version_is_still_read(self):
        legacy = "# Detailed Stories\n\n## US-001 — User Login\n\n**Description:**\nAs a user, I want to log in.\n\n**Preconditions:**\nNot specified.\n\n**Functional Behaviour:**\n- Users log in.\n\n**Acceptance Criteria:**\n1. Valid credentials grant access.\n\n**Dependencies:**\nNot specified.\n"
        stories, problems = common.parse_detailed_document(legacy)
        self.assertEqual(problems, [])
        self.assertEqual((stories[0]["preconditions"], stories[0]["dependencies"]), ([], []))
        rendered = common.render_detailed(stories[0])
        self.assertNotIn("Not specified.", rendered)
        self.assertEqual(common.detailed_hash(common.parse_detailed_document("# Detailed Stories\n\n" + rendered + "\n")[0][0]), common.detailed_hash(stories[0]))

    def test_the_detailed_file_round_trips_exactly(self):
        self.generate()
        detailed = common.scan_detailed(self.paths)
        self.assertEqual(detailed.problems, [])
        self.assertEqual(detailed.order, [f"US-00{n}" for n in range(1, 7)])
        again = common.render_detailed_document([common.render_detailed(detailed.stories[i]) for i in detailed.order])
        self.assertEqual(again, self.read_detailed())
        draft, _ = self.export_draft()
        self.assertEqual(draft["stories"][0]["detailed"]["non_functional_requirements"], ["Login completes within 2 seconds under normal load."])
        self.assertEqual(draft["stories"][0]["lean_acceptance_criteria"],
                         ["Registered users can log in using valid credentials, and invalid credentials are rejected with the defined error response."])

    def test_state_records_both_versions_under_the_same_id(self):
        self.generate()
        state = self.read_state()
        self.assertEqual(state["schema_version"], "2.0")
        self.assertEqual(state["detailed_document"], "stories/detailed_stories.md")
        self.assertEqual(state["detailed_document_hash"], common.scan_detailed(self.paths).file_hash)
        entry = state["stories"][0]
        self.assertEqual(entry["story_id"], "US-001")
        stories, _ = common.parse_section(self.section_of())
        detailed = common.scan_detailed(self.paths).stories["US-001"]
        self.assertEqual(entry["story_content_hash"], common.lean_hash(stories[0]))
        self.assertEqual(entry["detailed_content_hash"], common.detailed_hash(detailed))
        self.assertEqual(entry["lean_derived_from"], entry["detailed_content_hash"])
        self.assertNotIn("detailed_file", entry)

    def test_the_report_shows_the_detailed_story_not_the_document_entry(self):
        self.generate()
        page = read_text(self.paths.report)
        story = page.split('id="US-001"')[1].split("</article>")[0]
        self.assertEqual(re.findall(r"<h4>([^<]+)</h4>", story),
                         ["Description", "Preconditions", "Functional Behaviour", "Business Rules", "Acceptance Criteria",
                          "Alternate and Error Scenarios", "Non-Functional Requirements"])
        self.assertIn("Login completes within 2 seconds under normal load.", story)
        self.assertIn("A registered user who submits valid credentials is authenticated.", story)
        self.assertNotIn("Registered users can log in using valid credentials.", story)
        self.assertNotIn("REQ-", story)
        self.assertNotIn("GAP-", story)

    def test_report_text_comes_from_the_detailed_file_even_if_the_document_differs(self):
        self.generate()
        self.edit_detailed("The user has a registered account.", "The user has a verified, registered account.")
        self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        self.assertIn("verified, registered account", read_text(self.paths.report))
        self.assertIn("Out of sync", read_text(self.paths.report))

    def test_a_story_without_a_detailed_story_is_flagged_and_never_replaced_by_the_document_text(self):
        self.generate()
        text = self.read_detailed()
        start, end = text.index("## US-003"), text.index("## US-004")
        with open(self.paths.detailed_file, "w", encoding="utf-8", newline="") as h:
            h.write(text[:start] + text[end:])
        self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        story = read_text(self.paths.report).split('id="US-003"')[1].split("</article>")[0]
        self.assertIn("has no detailed story in stories/detailed_stories.md", story)
        self.assertNotIn("Inactive sessions are ended.", story)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["missing"], ["US-003"])
        self.assertEqual(info["detailed"]["deleted_by_hand"], ["US-003"])
        draft, ctx = self.export_draft()
        self.assertIsNone(draft["stories"][2]["detailed"])
        self.assertTrue(ctx["story_context"][2]["detailed_missing"])

    def test_validation_checks_ids_summaries_and_a_missing_detailed_file(self):
        self.generate()
        errors, _, status = validator.validate_story_set(*self.set_args())
        self.assertEqual(errors, [])
        self.edit_detailed("## US-002 — Password Reset", "## US-002 — Password Change")
        errors, _, _ = validator.validate_story_set(*self.set_args())
        self.assertTrue(any("US-002: the summary differs" in e for e in errors), errors)
        os.unlink(self.paths.detailed_file)
        errors, _, _ = validator.validate_story_set(*self.set_args())
        self.assertTrue(any("stories/detailed_stories.md does not exist" in e for e in errors), errors)

    def set_args(self):
        doc = common.read_document(self.doc)
        state, _, _ = common.load_state(self.paths)
        _, _, requirements, _ = common.load_atomic(self.paths)
        return doc.stories, doc.problems, common.scan_detailed(self.paths), requirements, state

    def test_validator_cli_checks_the_detailed_stories(self):
        self.generate()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = validator.main(["--document", self.doc, "--project-root", self.root])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("stories/detailed_stories.md", out.getvalue())
        self.edit_detailed("**Description:**", "**Notes:**")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = validator.main(["--document", self.doc, "--project-root", self.root])
        self.assertEqual(code, 1)
        self.assertIn("extra story field 'Notes'", err.getvalue())

    def test_inspect_and_summary_report_detailed_status(self):
        self.generate()
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["file"], "stories/detailed_stories.md")
        self.assertEqual(info["detailed"]["story_count"], 6)
        self.assertEqual(info["detailed"]["missing"], [])
        self.assertFalse(info["detailed"]["file_modified"])
        code, summary = self.run_sync("summary")
        self.assertEqual(summary["detailed"]["stories"], 6)
        self.assertEqual(summary["detailed"]["file"], "stories/detailed_stories.md")
        self.assertTrue(summary["in_sync"])

    def test_detailed_manual_edit_is_detected_and_not_overwritten_without_consent(self):
        self.generate()
        self.edit_detailed("Login completes within 2 seconds under normal load.", "Login completes within 1 second under normal load.")
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["edited"], ["US-001"])
        self.assertTrue(info["detailed"]["file_modified"])
        self.assertEqual(info["detailed"]["lean_needs_update"], ["US-001"])
        draft = standard_stories()
        for number, story in enumerate(draft, start=1):
            story["story_id"] = f"US-00{number}"
        add_criterion(draft[0], "", "A locked account is denied access.")
        before = read_binary(self.paths.detailed_file)
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft))
        self.assertEqual(code, 1)
        conflict = result["conflicts"][0]
        self.assertEqual((conflict["story_id"], conflict["reason"], conflict["representation"]), ("US-001", "detailed_manual_edit", "detailed"))
        self.assertIn("within 1 second", json.dumps(conflict["current"]))
        self.assertEqual(read_binary(self.paths.detailed_file), before)
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft, name="o.json"), "--overwrite", "US-001")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["overwritten_manual_edits"], ["US-001"])
        self.assertIn("within 2 seconds", self.read_detailed())
        self.assertTrue(any(name.startswith("detailed_stories.md.") for name in os.listdir(self.paths.backups)))

    def test_a_kept_detailed_edit_makes_the_ultra_lean_story_stale_until_it_is_reviewed(self):
        self.generate()
        self.edit_detailed("A rejected login does not say which of the two values was wrong.", "A rejected login never says which of the two values was wrong.")
        code, result = self.run_sync("accept")
        self.assertEqual(code, 0, result)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["edited"], [])
        self.assertEqual(info["detailed"]["lean_needs_update"], ["US-001"])
        code, summary = self.run_sync("summary")
        self.assertFalse(summary["in_sync"])
        self.assertIn("Requirements document out of sync", read_text(self.paths.report))
        # Exporting keeps the edit; confirming the ultra-lean story clears the flag.
        draft, ctx = self.export_draft()
        self.assertIn("never says", draft["stories"][0]["detailed"]["business_rules"][0])
        self.assertTrue(ctx["story_context"][0]["lean_needs_update"])
        draft["stories"][0]["lean_reviewed"] = True
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="r.json"))
        self.assertEqual(code, 0, result)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["lean_needs_update"], [])
        self.assertTrue(self.run_sync("summary")[1]["in_sync"])

    def test_a_detailed_story_deleted_by_hand_is_not_recreated_without_consent(self):
        self.generate()
        text = self.read_detailed()
        start, end = text.index("## US-002"), text.index("## US-003")
        with open(self.paths.detailed_file, "w", encoding="utf-8", newline="") as h:
            h.write(text[:start] + text[end:])
        draft, _ = self.export_draft()
        draft["stories"][1]["detailed"] = standard_stories()[1]["detailed"]
        path = self.write_draft(draft["stories"], name="d.json")
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 1)
        self.assertEqual(result["conflicts"][0]["reason"], "detailed_deleted_by_hand")
        self.assertNotIn("## US-002", self.read_detailed())
        code, result = self.run_sync("apply", "--draft", path, "--restore", "US-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["restored"], [])
        self.assertIn("## US-002 — Password Reset", self.read_detailed())

    def test_an_orphan_detailed_story_is_kept_reported_and_never_collides_with_a_new_id(self):
        self.generate()
        orphan = common.render_detailed({**standard_stories()[0]["detailed"], "story_id": "US-009", "summary": "Orphan Story",
                                         "functional_behaviour": ["x"], "acceptance_criteria": ["Given a, when b, then c."], "description": "As a, I want b."})
        with open(self.paths.detailed_file, "a", encoding="utf-8", newline="") as h:
            h.write("\n" + orphan + "\n")
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["without_lean_story"], ["US-009"])
        errors, _, _ = validator.validate_story_set(*self.set_args())
        self.assertTrue(any("US-009" in e and "no matching story" in e for e in errors), errors)
        draft, _ = self.export_draft()
        new = make_story("Dark Theme", ["Users can switch to a dark theme."], ["REQ-006"])
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"] + [new], name="n.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["created"], ["US-010"])
        self.assertEqual(result["detailed_without_lean_story"], ["US-009"])
        self.assertIn("## US-009 — Orphan Story", self.read_detailed())

    def test_invalid_detailed_file_blocks_updates_until_fixed(self):
        self.generate()
        self.edit_detailed("**Functional Behaviour:**", "**Behaviour:**")
        code, result = self.run_sync("export")
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "DETAILED_PROBLEMS")
        before = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        self.assertEqual(self.read_doc_bytes(), before)
        self.assertEqual(self.run_sync("accept")[0], 1)

    def test_a_failed_detailed_write_leaves_the_document_alone(self):
        self.generate()
        doc, detailed, state = self.read_doc_bytes(), read_binary(self.paths.detailed_file), self.read_state()
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Logins are recorded.", "A successful login is recorded.")
        real = common.atomic_write_bytes

        def failing(target, payload, prefix=".story-"):
            if os.path.normcase(target) == os.path.normcase(self.paths.detailed_file):
                raise PermissionError("detailed file locked")
            return real(target, payload, prefix=prefix)

        with mock.patch.object(common, "atomic_write_bytes", failing):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="f.json"))
        self.assertEqual(code, 2)
        self.assertIn("detailed file locked", result["error"])
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)
        self.assertEqual(self.read_state(), state)

    def test_a_failed_document_write_restores_the_detailed_stories(self):
        self.generate()
        doc, detailed, state = self.read_doc_bytes(), read_binary(self.paths.detailed_file), self.read_state()
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Logins are recorded.", "A successful login is recorded.")
        real = common.atomic_write_bytes

        def failing(target, payload, prefix=".story-"):
            if os.path.normcase(target) == os.path.normcase(self.doc):
                raise PermissionError("document locked")
            return real(target, payload, prefix=prefix)

        with mock.patch.object(common, "atomic_write_bytes", failing):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="f.json"))
        self.assertEqual(code, 2)
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)
        self.assertEqual(self.read_state(), state)

    def test_a_failed_verification_restores_the_detailed_stories(self):
        self.generate()
        detailed = read_binary(self.paths.detailed_file)
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Logins are recorded.", "A successful login is recorded.")
        with mock.patch.object(sync, "verify_written", return_value=["simulated read-back mismatch"]):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="v.json"))
        self.assertEqual(code, 1)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)

    def test_renaming_a_story_by_hand_moves_its_detailed_story_and_retiring_removes_it(self):
        self.generate()
        self.edit_section("## US-005 — Report Export", "## US-025 — Report Export")
        text = self.read_doc_bytes().decode("utf-8")
        start, end = text.index("## US-004"), text.index("## US-025")
        self.write_doc(text[:start] + text[end:])
        code, result = self.run_sync("accept", "--rename", "US-005=US-025", "--retire", "US-004")
        self.assertEqual(code, 0, result)
        detailed = self.read_detailed()
        self.assertIn("## US-025 — Report Export", detailed)
        self.assertNotIn("## US-005", detailed)
        self.assertNotIn("## US-004", detailed)
        self.assertEqual(result["detailed_renamed"], [{"from": "US-005", "to": "US-025"}])
        self.assertEqual(result["detailed_removed"], ["US-004"])
        self.assertTrue(any(name.startswith("detailed_stories.md.") for name in os.listdir(self.paths.backups)))
        state = self.read_state()
        self.assertEqual(state["detailed_document_hash"], common.scan_detailed(self.paths).file_hash)
        self.assertIn("US-005", state["retired_story_ids"])
        self.assertIn("US-004", state["retired_story_ids"])
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["missing"], [])
        self.assertEqual(info["detailed"]["without_lean_story"], [])
        self.assertTrue(self.run_sync("summary")[1]["in_sync"])

    def test_enrichment_changes_the_detailed_story_first_and_the_non_functional_target_stays_out_of_the_document(self):
        self.write_gaps([make_gap("GAP-001", "High", "How fast must login be?", ["REQ-001"])])
        self.generate()
        with open(os.path.join(self.root, "gaps", "gaps.json"), encoding="utf-8") as h:
            gaps = json.load(h)
        gaps[0]["status"] = "resolved"
        gaps[0]["decisions_recorded"] = [{"decision": "Login must complete within 1 second.", "recorded_at": "2026-10-27T09:00:00+05:30"}]
        self.write_gaps(gaps)
        document_before = self.read_doc_bytes()
        draft, _ = self.export_draft()
        draft["stories"][0]["detailed"]["non_functional_requirements"] = ["Login completes within 1 second under normal load."]
        draft["stories"][0]["applied_decisions"] = ["GAP-001"]
        draft["decisions_reviewed"] = [{"gap_id": "GAP-001", "outcome": "incorporated"}]
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name="e.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["updated"], ["US-001"])
        self.assertEqual(result["detailed_changed"], ["US-001"])
        self.assertEqual(result["lean_changed"], [])
        self.assertFalse(result["document_changed"])
        self.assertEqual(self.read_doc_bytes(), document_before)
        self.assertIn("within 1 second", self.read_detailed())
        self.assertEqual(self.read_state()["decision_ledger"]["GAP-001"]["outcome"], "incorporated")
        self.assertIn("within 1 second", read_text(self.paths.report))

    def test_legacy_layout_is_detected_and_migrated_with_consent(self):
        legacy = (
            "\n# Development Stories\n\n## US-001\n\n**Summary:** Log in with registered credentials\n\n**Detailed Description:**\n"
            "As a registered user, I want to log in so that I can access my account.\n\n**Acceptance Criteria:**\n\n"
            "1. Given valid credentials, when the user logs in, then access is granted.\n"
        )
        self.write_doc(DOCUMENT + legacy)
        os.makedirs(os.path.join(self.root, "stories", "detailed"))
        with open(os.path.join(self.root, "stories", "detailed", "US-001.md"), "w", encoding="utf-8") as h:
            h.write("# US-001\n")
        with open(self.paths.legacy_lean_file, "w", encoding="utf-8") as h:
            h.write("mirror\n")
        code, info = self.run_sync("inspect", "--target", self.doc)
        self.assertEqual(info["section"]["legacy_layout_story_ids"], ["US-001"])
        self.assertEqual(info["section"]["problems"], [])
        self.assertEqual(info["detailed"]["legacy_files"], ["stories/detailed/", "stories/lean-stories.md"])
        self.assertFalse(info["recoverable_from_document"])
        errors, _, _ = validator.validate_story_set(*self.set_args_for_legacy())
        self.assertTrue(any("layout of an earlier plugin version" in e for e in errors), errors)
        code, result = self.run_sync("accept", "--target", self.doc)
        self.assertEqual(code, 1)
        self.assertIn("earlier plugin version", result["error"])
        first = standard_stories()[0]
        first["story_id"] = "US-001"
        code, result = self.run_sync("apply", "--target", self.doc, "--draft", self.write_draft([first] + standard_stories()[1:], name="m.json"))
        self.assertEqual(code, 1)
        self.assertEqual(result["conflicts"][0]["reason"], "no_baseline")
        code, result = self.run_sync("apply", "--target", self.doc, "--draft", self.write_draft([first] + standard_stories()[1:], name="m2.json"), "--overwrite", "US-001")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["overwritten_manual_edits"], ["US-001"])
        self.assertEqual(result["created"], ["US-002", "US-003", "US-004", "US-005", "US-006"])
        section = self.section_of()
        self.assertNotIn("Detailed Description", section)
        self.assertIn("## US-001 — User Login", section)
        self.assertTrue(os.path.isfile(self.paths.detailed_file))
        # The old files are reported, left in place and never read.
        self.assertTrue(os.path.isdir(self.paths.legacy_detailed_dir))
        code, summary = self.run_sync("summary")
        self.assertEqual(summary["detailed"]["legacy_files"], ["stories/detailed/", "stories/lean-stories.md"])
        self.assertTrue(summary["validation"]["passed"])
        self.assertTrue(any("earlier plugin version" in w for w in summary["validation"]["warnings"]))

    def set_args_for_legacy(self):
        doc = common.read_document(self.doc)
        _, _, requirements, _ = common.load_atomic(self.paths)
        return doc.stories, doc.problems, common.scan_detailed(self.paths), requirements, None

    def test_an_old_state_version_is_not_used(self):
        self.generate()
        state = self.read_state()
        state["schema_version"] = "1.1"
        with open(self.paths.state, "w", encoding="utf-8") as h:
            json.dump(state, h)
        code, info = self.run_sync("inspect")
        self.assertEqual(info["state"]["status"], "INVALID")
        self.assertIn("earlier plugin version", info["state"]["errors"][0])


class ValidationTests(ProjectCase):
    def check(self, mutate=None, register=None):
        draft = {"stories": standard_stories()}
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

    def test_the_standard_stories_are_valid_without_warnings(self):
        errors, warnings = self.check()
        self.assertEqual((errors, warnings), ([], []))

    def test_structure_ids_and_extra_metadata(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("priority", "High"))
        self.assertTrue(any("unexpected property: priority" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("owner", "Sam"))
        self.assertTrue(any("unexpected property: owner" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("story_id", "US-1"))
        self.assertTrue(any("story_id" in e for e in errors))
        errors, _ = self.check(lambda d: (d["stories"][0].__setitem__("story_id", "US-001"), d["stories"][1].__setitem__("story_id", "US-001")))
        self.assertTrue(any("duplicate story_id" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", []))
        self.assertTrue(errors)
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("acceptance_criteria", []))
        self.assertTrue(errors)
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("functional_behaviour", []))
        self.assertTrue(errors)
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("dependencies", ["", "x"]))
        self.assertTrue(any("dependencies item 1" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("acceptance_criteria", ["a b c", "A B C"]))
        self.assertTrue(any("duplicate detailed acceptance criteria" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["1. numbered itself"]))
        self.assertTrue(any("numbering" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("summary", "  "))
        self.assertTrue(errors)
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("summary", "Two\nlines"))
        self.assertTrue(any("single line" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0].pop("detailed"))
        self.assertTrue(any("missing required property: detailed" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].pop("description"))
        self.assertTrue(any("detailed: missing required property: description" in e for e in errors))
        errors, _ = self.check(lambda d: d["stories"][1].__setitem__("summary", "user login"))
        self.assertTrue(any("summary duplicates" in e for e in errors))

    def test_text_that_cannot_round_trip_as_markdown_is_rejected(self):
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("description", "As a user, I want x.\n\n**Priority:** high"))
        self.assertTrue(any("detailed story cannot be written as readable Markdown" in e for e in errors), errors)
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("description", "# Heading inside the description"))
        self.assertTrue(any("detailed story cannot be written as readable Markdown" in e for e in errors), errors)
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("summary", "Login ##"))
        self.assertTrue(any("cannot be written as readable Markdown" in e for e in errors), errors)

    def test_coverage_requires_a_story_or_a_reason(self):
        errors, _ = self.check(lambda d: d["stories"].pop())
        self.assertTrue(any("REQ-006 is not covered" in e for e in errors))
        errors, _ = self.check(lambda d: (d["stories"].pop(), d.__setitem__("not_covered_requirements", [{"requirement_id": "REQ-006", "reason": "Out of scope for development."}])))
        self.assertEqual(errors, [])
        errors, _ = self.check(lambda d: d.__setitem__("not_covered_requirements", [{"requirement_id": "REQ-006", "reason": "x"}]))
        self.assertTrue(any("also be reported" in e for e in errors))

    def test_vague_wording_is_a_warning_not_an_error(self):
        errors, warnings = self.check(lambda d: d["stories"][0]["detailed"]["acceptance_criteria"].append("The system shall respond as expected."))
        self.assertEqual(errors, [])
        self.assertTrue(any("as expected" in w for w in warnings))

    def test_detailed_criteria_written_as_given_when_then_draw_a_warning_only(self):
        gherkin = "Given valid credentials, when the user logs in, then access is granted."
        errors, warnings = self.check(lambda d: d["stories"][0]["detailed"]["acceptance_criteria"].append(gherkin))
        self.assertEqual(errors, [])
        self.assertTrue(any("detailed criterion 3 is written as Given/When/Then" in w for w in warnings), warnings)
        errors, warnings = self.check()
        self.assertEqual((errors, warnings), ([], []))

    def test_a_dependency_on_another_story_must_name_a_story_of_the_draft(self):
        def depend(text, story=1):
            return lambda d: d["stories"][story]["detailed"].__setitem__("dependencies", [text])
        errors, _ = self.check(depend("[[User Login]]: the user must be logged in."))
        self.assertEqual(errors, [])
        errors, _ = self.check(depend("[[user   login]]: matching ignores case and spacing."))
        self.assertEqual(errors, [])
        errors, _ = self.check(depend("[[Unknown Story]]: needed."))
        self.assertTrue(any("not the summary of any story in the draft" in e for e in errors), errors)
        errors, _ = self.check(depend("[[Password Reset]]: needed."))
        self.assertTrue(any("depend on itself" in e for e in errors), errors)
        errors, _ = self.check(depend("US-009: needed."))
        self.assertTrue(any("US-009" in e and "not a story in the draft" in e for e in errors), errors)
        errors, _ = self.check(lambda d: (d["stories"][0].__setitem__("story_id", "US-001"), d["stories"][1]["detailed"].__setitem__("dependencies", ["US-001: needed."])))
        self.assertEqual(errors, [])

    def test_the_saved_detailed_file_warns_about_a_dependency_on_a_missing_story(self):
        self.generate()
        detailed = common.scan_detailed(self.paths)
        story = dict(detailed.stories["US-002"], dependencies=["US-001 (User Login): logged in.", "US-077 (Ghost): needed."])
        _, warnings, _ = validator.validate_story_set(
            [{"story_id": "US-002", "summary": "Password Reset", "acceptance_criteria": ["Users can reset a password."]}], [],
            type("D", (), {"problems": [], "exists": True, "stories": {"US-002": story, "US-001": detailed.stories["US-001"]}})(), None, None)
        self.assertTrue(any("US-077" in w for w in warnings), warnings)
        self.assertFalse(any("US-001" in w for w in warnings), warnings)

    def test_lean_criteria_must_not_be_given_when_then_scenarios(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["Given valid credentials, when the user logs in, then access is granted."]))
        self.assertTrue(any("lean criterion 1 is a Given/When/Then scenario" in e for e in errors), errors)
        # The detailed criteria are plain statements.
        errors, _ = self.check()
        self.assertEqual(errors, [])

    def test_lean_criteria_must_be_exactly_one_statement(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["Users can log in.", "Invalid credentials are rejected."]))
        self.assertTrue(any("exactly one statement (2 given)" in e for e in errors), errors)
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["Users can log in."]))
        self.assertEqual(errors, [])

    def test_summary_length_is_advice_only(self):
        errors, warnings = self.check(lambda d: d["stories"][0].__setitem__("summary", "Login"))
        self.assertEqual(errors, [])
        self.assertTrue(any("summary is too vague" in w for w in warnings), warnings)
        errors, warnings = self.check(lambda d: d["stories"][0].__setitem__("summary", "Registered user login"))
        self.assertEqual((errors, warnings), ([], []))

    def test_a_long_summary_is_advice_only(self):
        errors, warnings = self.check(lambda d: d["stories"][0].__setitem__("summary", "Allow registered users to authenticate themselves with an email address and a password"))
        self.assertEqual(errors, [])
        self.assertTrue(any("summary is not concise" in w for w in warnings))
        errors, warnings = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["Password reset links are valid for 24 hours."]))
        self.assertEqual([e for e in errors if "non-functional" in e], [])
        self.assertEqual([w for w in warnings if "non-functional" in w], [])
        words = " ".join(["word"] * 80)
        errors, warnings = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", [words]))
        self.assertTrue(any("statement is long" in w for w in warnings))

    def test_a_non_functional_requirement_in_the_lean_story_is_an_error(self):
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", ["The system logs users in. Login completes within 2 seconds."]))
        self.assertTrue(any("non-functional requirement ('within 2 seconds')" in e for e in errors), errors)
        leaked = "Users can complete every action using the keyboard alone, with labelled fields and readable text error messages."
        errors, _ = self.check(lambda d: d["stories"][0].__setitem__("lean_acceptance_criteria", [leaked]))
        self.assertTrue(any("keyboard" in e and "Non-Functional Requirements" in e for e in errors), errors)

    def test_a_story_that_is_only_a_non_functional_requirement_is_an_error(self):
        def make_standalone(d):
            story = d["stories"][0]
            story["summary"] = "Keyboard and accessible form use"
            story["lean_acceptance_criteria"] = ["Users can complete every action using the keyboard alone."]
            story["detailed"]["functional_behaviour"] = ["Every action can be completed with the keyboard alone.", "The forms can be used with a screen reader."]
        errors, _ = self.check(make_standalone)
        self.assertTrue(any("summary names a non-functional requirement ('Keyboard')" in e for e in errors), errors)
        self.assertTrue(any("lean acceptance criteria statement is or contains" in e for e in errors), errors)
        self.assertTrue(any("every functional behaviour item is a quality attribute" in e for e in errors), errors)

    def test_a_story_with_only_quality_attributes_as_behaviour_is_an_error(self):
        errors, _ = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("functional_behaviour", ["Pages load within 3 seconds.", "The system keeps 99.9% availability target."]))
        self.assertTrue(any("every functional behaviour item is a quality attribute" in e for e in errors), errors)

    def test_non_functional_requirements_stay_in_the_detailed_story_without_error(self):
        errors, warnings = self.check(lambda d: d["stories"][0]["detailed"].__setitem__("non_functional_requirements", ["Every action can be completed with the keyboard alone.", "Form fields are labelled."]))
        self.assertEqual((errors, warnings), ([], []))

    def test_the_documented_lean_checks_also_apply_to_the_saved_document(self):
        story = {"story_id": "US-001", "summary": "Log in", "acceptance_criteria": ["Given a, when b, then c.", "Login responds within 2 seconds."]}
        _, warnings = validator.validate_managed_section([story], [], None)
        self.assertTrue(any("Given/When/Then scenario" in w for w in warnings))
        self.assertTrue(any("non-functional" in w for w in warnings))

    def test_a_bulleted_document_is_read_and_flagged_for_combining(self):
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — User Login\n\n**Acceptance Criteria:**\n- Users can log in.\n- Invalid credentials are rejected.\n")
        self.assertEqual((problems, stories[0]["acceptance_criteria"]), ([], ["Users can log in.", "Invalid credentials are rejected."]))
        _, warnings = validator.validate_managed_section(stories, [], None)
        self.assertTrue(any("combine them into one statement" in w for w in warnings), warnings)
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — User Login\n\n**Acceptance Criteria:** Users can log in\nand invalid credentials are rejected.\n")
        self.assertEqual((problems, stories[0]["acceptance_criteria"]), ([], ["Users can log in and invalid credentials are rejected."]))
        self.assertEqual(common.render_lean(stories[0]).splitlines()[2], "**Acceptance Criteria:** Users can log in and invalid credentials are rejected.")
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — User Login\n\n**Acceptance Criteria:**\n")
        self.assertTrue(any("'Acceptance Criteria' field is empty" in p for p in problems), problems)

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
        broken = read_text(self.doc).replace("**Acceptance Criteria:**", "**Owner:** Sam\n\n**Acceptance Criteria:**", 1)
        self.write_doc(broken)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = validator.main(["--document", self.doc, "--project-root", self.root])
        self.assertEqual(code, 1)
        self.assertIn("extra story field 'Owner'", err.getvalue())

    def test_the_document_contract_rejects_descriptions_and_missing_summaries(self):
        stories, problems = common.parse_section("# Development Stories\n\n## US-001\n\n**Acceptance Criteria:**\n- x\n")
        self.assertTrue(any("no short summary" in p for p in problems), problems)
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — Login\n\n**Description:**\nAs a user.\n\n**Acceptance Criteria:**\n- x\n")
        self.assertTrue(any("extra story field 'Description'" in p for p in problems), problems)
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — Login\n\nStray text.\n\n**Acceptance Criteria:**\n- x\n")
        self.assertTrue(any("text before the first field" in p for p in problems), problems)
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 — Login\n")
        self.assertTrue(any("'Acceptance Criteria' field is missing" in p for p in problems), problems)
        # Hyphen and colon separators are read; the script always writes the em dash.
        stories, problems = common.parse_section("# Development Stories\n\n## US-001 - Login\n\n**Acceptance Criteria:**\n- x\n\n## US-002: Logout\n\n**Acceptance Criteria:**\n- y\n")
        self.assertEqual((problems, [s["summary"] for s in stories]), ([], ["Login", "Logout"]))


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
        self.write_doc("# One\n\ntext\n\n# Development Stories\n\n## US-001 — x\n\n**Acceptance Criteria:**\n- z\n")
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

    def resolve(self, gap_id, text, at="2026-10-27T09:00:00+05:30"):
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

    def enrich_us001(self):
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Accounts are locked for 30 minutes after five consecutive failed login attempts.",
                      "After five consecutive failed login attempts the account is locked for 30 minutes.")
        draft["stories"][0]["detailed"]["business_rules"].append("An account is locked for 30 minutes after five consecutive failed login attempts.")
        draft["stories"][0]["applied_decisions"] = ["GAP-001"]
        draft["decisions_reviewed"] = [{"gap_id": "GAP-001", "outcome": "incorporated"}]
        return draft

    def apply_enrichment(self, name="e.json"):
        draft = self.enrich_us001()
        return self.run_sync("apply", "--draft", self.write_draft(draft["stories"], {"decisions_reviewed": draft["decisions_reviewed"]}, name=name))

    def test_14_15_resolved_gap_enriches_only_the_impacted_stories_and_report_shows_decision(self):
        self.resolve("GAP-001", self.DECISION)
        code, info = self.run_sync("inspect")
        pending = info["pending_decisions"]
        self.assertEqual([(p["gap_id"], p["kind"], p["candidate_story_ids"]) for p in pending], [("GAP-001", "new", ["US-001", "US-003"])])
        self.assertEqual(info["gap_changes"]["newly_resolved"], ["GAP-001"])
        code, result = self.apply_enrichment()
        self.assertEqual(code, 0, result)
        self.assertEqual(result["updated"], ["US-001"])
        self.assertEqual(len(result["unchanged"]), 5)
        self.assertIn("Accounts are locked for 30 minutes after five consecutive failed login attempts.", self.section_of())
        self.assertIn("**Acceptance Criteria:** Registered users can log in using valid credentials,", self.section_of())
        self.assertIn("3. After five consecutive failed login attempts the account is locked for 30 minutes.", self.read_detailed())
        code, info = self.run_sync("inspect")
        self.assertEqual(info["pending_decisions"], [])
        self.assertEqual(self.read_state()["decision_ledger"]["GAP-001"]["outcome"], "incorporated")
        page = read_text(self.paths.report)
        self.assertIn(self.DECISION, page)
        self.assertIn("Incorporated in stories", page)

    def test_16_resolved_gap_without_story_change_still_reaches_the_report(self):
        self.resolve("GAP-002", "A reset link is valid for 24 hours.")
        before, detailed = self.read_doc_bytes(), read_binary(self.paths.detailed_file)
        draft, _ = self.export_draft()
        extra = {"decisions_reviewed": [{"gap_id": "GAP-002", "outcome": "no_change_required"}]}
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], extra, name="n.json"))
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertFalse(result["detailed_file_changed"])
        self.assertTrue(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), before)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)
        page = read_text(self.paths.report)
        self.assertIn("A reset link is valid for 24 hours.", page)
        self.assertIn("Reviewed: no story change required", page)

    def test_17_rerunning_enrichment_changes_nothing(self):
        self.resolve("GAP-001", self.DECISION)
        self.assertEqual(self.apply_enrichment()[0], 0)
        doc, detailed, state = self.read_doc_bytes(), read_binary(self.paths.detailed_file), self.read_state()
        code, result = self.run_sync("apply", "--draft", os.path.join(self.scratch, "e.json"))
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        self.assertFalse(result["detailed_file_changed"])
        self.assertFalse(result["state_changed"])
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)
        self.assertEqual(self.read_state(), state)

    def test_18_a_revised_decision_is_pending_again(self):
        self.resolve("GAP-001", self.DECISION)
        self.assertEqual(self.apply_enrichment()[0], 0)
        self.resolve("GAP-001", "Lock the account after three failed attempts for 15 minutes.", at="2026-10-28T09:00:00+05:30")
        code, info = self.run_sync("inspect")
        self.assertEqual([(p["gap_id"], p["kind"]) for p in info["pending_decisions"]], [("GAP-001", "revised")])
        self.assertIn("three failed attempts", info["pending_decisions"][0]["decision"])

    def test_19_reopening_does_not_delete_criteria_and_needs_acknowledgement(self):
        self.resolve("GAP-001", self.DECISION)
        self.assertEqual(self.apply_enrichment()[0], 0)
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
        self.assertIn("five consecutive failed login attempts", flat(self.read_detailed()))
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

    def test_20_manual_edit_is_detected_with_detail(self):
        self.edit_section("## US-002 — Password Reset", "## US-002 — Password Reset by e-mail link")
        self.edit_section("Registered users can reset their password by email.", "Registered users can reset their password by email. A second manual criterion is added.")
        code, info = self.run_sync("inspect")
        changes = info["manual_changes"]
        self.assertTrue(changes["section_modified"])
        self.assertEqual(changes["edited"], ["US-002"])
        self.assertTrue(changes["edited_details"]["US-002"]["summary_changed"])
        self.assertEqual(changes["edited_details"]["US-002"]["criteria_added"], ["Registered users can reset their password by email. A second manual criterion is added."])
        self.assertEqual(changes["edited_details"]["US-002"]["criteria_removed_count"], 1)

    def test_deletion_and_id_change_are_detected(self):
        text = self.read_doc_bytes().decode("utf-8")
        start, end = text.index("## US-004"), text.index("## US-005")
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
        add_criterion(draft["stories"][5], "Empty names are rejected.", "A profile saved with an empty name is rejected.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="o.json"))
        self.assertEqual(code, 0, result)
        self.assertIn("Managers export reports in CSV.", self.read_doc_bytes().decode())

    def test_manual_edit_conflicts_are_not_overwritten_without_consent(self):
        draft, _ = self.export_draft()
        self.edit_section("Users can update their profile details.", "Users can maintain their profile details.")
        add_criterion(draft["stories"][5], "Empty names are rejected.", "A profile saved with an empty name is rejected.")
        path = self.write_draft(draft["stories"], name="c.json")
        before = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 1)
        self.assertEqual(result["conflicts"][0]["story_id"], "US-006")
        self.assertEqual(result["conflicts"][0]["reason"], "manual_edit")
        self.assertEqual(result["conflicts"][0]["representation"], "lean")
        self.assertEqual(self.read_doc_bytes(), before)
        code, result = self.run_sync("apply", "--draft", path, "--overwrite", "US-006")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["overwritten_manual_edits"], ["US-006"])

    def test_a_draft_built_from_the_edited_document_keeps_the_edit(self):
        self.edit_section("## US-006 — Profile Update", "## US-006 — Profile Maintenance")
        draft, _ = self.export_draft()
        self.assertEqual(draft["stories"][5]["summary"], "Profile Maintenance")
        add_criterion(draft["stories"][0], "Sessions are kept unique.", "A second login by the same user keeps a single session.")
        code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="k.json"))
        self.assertEqual(code, 0, result)
        self.assertEqual(result["updated"], ["US-001", "US-006"])  # the kept summary also reaches US-006's detailed story
        self.assertEqual(result["lean_changed"], ["US-001"])
        self.assertIn("Profile Maintenance", self.read_doc_bytes().decode())
        self.assertIn("## US-006 — Profile Maintenance", self.read_detailed())

    def test_extra_metadata_blocks_updates_until_reconciled(self):
        self.edit_section("**Acceptance Criteria:**", "**Priority:** High\n\n**Acceptance Criteria:**")
        code, info = self.run_sync("inspect")
        self.assertTrue(any("extra story field 'Priority'" in p for p in info["section"]["problems"]))
        before = self.read_doc_bytes()
        code, result = self.run_sync("apply", "--draft", self.write_draft(standard_stories()))
        self.assertEqual(code, 1)
        code, result = self.run_sync("accept")
        self.assertEqual(code, 1)
        self.assertEqual(self.read_doc_bytes(), before)

    def test_accept_records_manual_edits_without_touching_the_document(self):
        self.edit_section("## US-002 — Password Reset", "## US-002 — Password Reset by e-mail link")
        text = self.read_doc_bytes().decode("utf-8")
        start, end = text.index("## US-004"), text.index("## US-005")
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
        page = read_text(self.paths.report)
        self.assertNotIn("e-mail link", page)  # the report shows the detailed story, not the hand-edited document entry
        self.assertIn("summary differs between the requirements document and the detailed story", page)

    def test_accept_requires_mappings_for_manually_added_stories_and_supports_rename(self):
        text = self.read_doc_bytes().decode("utf-8")
        added = "\n\n## US-020 — Guest Checkout\n\n**Acceptance Criteria:**\n- Guests can check out and place an order.\n"
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
        code, info = self.run_sync("inspect")
        self.assertEqual(info["detailed"]["missing"], ["US-020"])  # the detailed story still has to be written
        # Rename keeps the mapping and retires the old ID.
        self.edit_section("## US-005 — Report Export", "## US-025 — Report Export")
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
        self.assertTrue(result["conflicts"])
        mapping = {f"US-00{i}": {"source_requirement_ids": [f"REQ-00{i}"]} for i in range(1, 7)}
        path = os.path.join(self.scratch, "m.json")
        with open(path, "w") as h:
            json.dump(mapping, h)
        code, result = self.run_sync("accept", "--target", self.doc, "--mappings", path)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["recovered_from_document"])
        state = self.read_state()
        self.assertEqual(len(state["stories"]), 6)
        self.assertEqual(state["detailed_document_hash"], common.scan_detailed(self.paths).file_hash)
        self.assertTrue(self.run_sync("summary")[1]["in_sync"])


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
        self.assertFalse(os.path.exists(self.paths.detailed_file))
        self.write_requirements([{"requirement_id": "REQ-001", "title": "x"}])
        code, info = self.run_sync("inspect", "--target", self.doc)
        self.assertEqual(info["status"], "INPUT_INVALID")

    def test_23_failed_write_keeps_the_original_document_and_state(self):
        self.generate()
        before_doc, before_state = self.read_doc_bytes(), self.read_state()
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Login times are recorded.", "A successful login records the login time.")
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
        add_criterion(draft["stories"][0], "Login times are recorded.", "A successful login records the login time.")
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
        add_criterion(draft["stories"][0], "Login times are recorded.", "A successful login records the login time.")
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

        add_criterion(draft["stories"][0], "Logouts end the session.", "A completed logout ends the session.")
        detailed = read_binary(self.paths.detailed_file)
        with mock.patch.object(sync, "make_backup", sneaky):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="c2.json"), "--expected-source-sha256", sha)
        self.assertEqual(code, 1)
        self.assertIn("concurrent", result["error"])
        self.assertTrue(self.read_doc_bytes().endswith(b"\nsneaky edit\n"))
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)

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
        dark = make_story("Dark Theme", ["Users can switch to a dark colour theme."], ["REQ-007"])
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
        self.assertNotIn("## US-005", self.read_detailed())

    def test_state_failure_after_document_write_is_reported(self):
        self.generate()
        draft, _ = self.export_draft()
        add_criterion(draft["stories"][0], "Login times are recorded.", "A successful login records the login time.")
        path = self.write_draft(draft["stories"], name="s.json")
        with mock.patch.object(sync, "save_state", side_effect=common.IOFailure("disk full")):
            code, result = self.run_sync("apply", "--draft", path)
        self.assertEqual(code, 4)
        self.assertFalse(result["ok"])
        self.assertIn("accept", result["warning"])
        self.assertIn("login times are recorded", flat(self.read_doc_bytes().decode()).lower())


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
        self.assertEqual(result["detailed"]["stories"], 5)
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
        self.assertIn("A registered user who submits valid credentials is authenticated.", page)
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
        self.assertIn("stories/detailed_stories.md", page)
        self.assertNotIn("stories/detailed/", page)

    def test_story_entries_show_detail_without_requirement_or_gap_ids(self):
        self.generate()
        story = self.page().split('id="US-001"')[1].split("</article>")[0]
        self.assertNotIn("REQ-", story)
        self.assertNotIn("GAP-", story)
        self.assertIn("Requirements document in sync", story)

    def test_traceability_lists_story_to_requirement_and_gap_mappings(self):
        self.generate()
        trace = self.page().split('id="traceability"')[1].split("</section>")[0]
        row = re.search(r"<tr><td><a href=\"#US-001\">US-001</a></td><td>User Login</td><td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td></tr>", trace)
        self.assertIsNotNone(row, trace)
        self.assertEqual(row.group(1), "REQ-001")
        self.assertEqual(row.group(2), "GAP-001 (Resolved)")
        row = re.search(r"<a href=\"#US-002\">US-002</a></td><td>Password Reset</td><td>REQ-002</td><td>([^<]*)</td>", trace)
        self.assertEqual(row.group(1), "GAP-002 (Open)")
        self.assertIn("<h4>Requirements</h4>", trace)

    def test_08_source_text_is_escaped(self):
        stories = standard_stories()
        stories[0]["summary"] = "Login <img src=x onerror=alert(1)> & more"
        stories[0]["detailed"]["acceptance_criteria"][0] = "<script>alert('x')</script> when 1 < 2 the system responds in 3 seconds."
        stories[0]["detailed"]["non_functional_requirements"] = ["Responds <b>fast</b> & reliably."]
        self.generate(stories)
        page = self.page()
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;", page)
        self.assertIn("Responds &lt;b&gt;fast&lt;/b&gt; &amp; reliably.", page)
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
        add_criterion(draft["stories"][0], "Login times are recorded.", "A successful login records the login time.")
        with mock.patch.object(common, "atomic_write_bytes", failing):
            code, result = self.run_sync("apply", "--draft", self.write_draft(draft["stories"], name="rf.json"))
        self.assertEqual(code, 3)
        self.assertTrue(result["ok"])
        self.assertFalse(result["report"]["generated"])
        self.assertIn("stale", result["warning"])
        self.assertEqual(self.page(), good)
        self.assertIn("login times are recorded", flat(self.read_doc_bytes().decode()).lower())
        self.assertNotEqual(self.read_doc_bytes(), doc)
        self.assertEqual(len(self.read_state()["stories"]), len(state["stories"]))
        code, result = self.run_sync("regenerate-report")
        self.assertEqual(code, 0, result)
        self.assertIn("A successful login records the login time.", self.page())

    def test_12_report_only_regeneration_changes_nothing_else(self):
        self.generate()
        doc, state, detailed = self.read_doc_bytes(), read_binary(self.paths.state), read_binary(self.paths.detailed_file)
        backups = os.listdir(self.paths.backups) if os.path.isdir(self.paths.backups) else []
        decisions = read_binary(os.path.join(self.root, "gaps", "gaps.json"))
        code, result = self.run_sync("regenerate-report")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.read_doc_bytes(), doc)
        self.assertEqual(read_binary(self.paths.state), state)
        self.assertEqual(read_binary(self.paths.detailed_file), detailed)
        self.assertEqual(read_binary(os.path.join(self.root, "gaps", "gaps.json")), decisions)
        self.assertEqual(os.listdir(self.paths.backups) if os.path.isdir(self.paths.backups) else [], backups)

    def test_06_manual_edits_reconciled_by_accept_reach_the_next_report(self):
        self.generate()
        self.edit_detailed("## US-005 — Report Export", "## US-005 — Report Export as CSV")
        self.assertEqual(self.run_sync("regenerate-report")[0], 0)
        self.assertIn("Out of sync", self.page())
        code, result = self.run_sync("accept")
        self.assertEqual(code, 0, result)
        page = self.page()
        self.assertIn("Report Export as CSV", page)
        self.assertIn("Requirements document out of sync", page)  # the detailed edit is recorded; the document entry still needs updating

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


def read_plugin(*parts):
    return read_text(os.path.join(PLUGIN_ROOT, *parts))


class StandardDocsTests(unittest.TestCase):
    """The rules, skills, agent and commands must state the ultra-lean and consolidated-file standards."""

    def test_the_writing_rules_define_both_representations(self):
        text = read_plugin("rules", "story-writing-rules.md")
        for expected in ("stories/detailed_stories.md", "Story ID", "typically 3-7 words", "**One** concise statement", "**Given/When/Then**", "Non-Functional Requirements", "Story ID and summary",
                         "Never create a separate Markdown file per story", "## US-001 — Registered user login"):
            self.assertIn(expected, text)

    def test_the_criteria_rules_separate_detailed_and_ultra_lean_criteria(self):
        text = read_plugin("rules", "acceptance-criteria-rules.md")
        self.assertIn("Detailed criteria (plain text)", text)
        self.assertIn("Ultra-lean criteria (requirements document)", text)
        self.assertIn("Do not use Given / When / Then", text)
        self.assertIn("**Not Gherkin.**", text)

    def test_the_management_rules_state_the_locations_the_gate_and_the_validation_list(self):
        text = read_plugin("rules", "story-management-rules.md")
        for expected in ("stories/detailed_stories.md", "stories/story-generation-state.json", "No per-story Markdown files are ever created",
                         "Every Critical and High gap must be `resolved`", "Open or skipped Medium and Low gaps never block generation",
                         "Manual edits have not been silently overwritten", "The HTML report sources story content from `stories/detailed_stories.md`"):
            self.assertIn(expected, text)

    def test_nothing_in_the_plugin_still_describes_the_per_story_layout(self):
        stale = ("stories/detailed/US", "stories/detailed/<ID>", "<ID>.md", "Detailed Description:**", "four fields")
        for folder in ("rules", "skills", "agents", "commands"):
            for dirpath, _, names in os.walk(os.path.join(PLUGIN_ROOT, folder)):
                for name in names:
                    text = read_text(os.path.join(dirpath, name))
                    for marker in stale:
                        self.assertNotIn(marker, text, f"{name} still mentions {marker!r}")

    def test_skills_agent_and_commands_apply_the_standard(self):
        for parts in (("skills", "story-generation", "SKILL.md"), ("skills", "story-enrichment", "SKILL.md"), ("agents", "story-generation-agent.md"),
                      ("commands", "ba-generate-stories.md"), ("commands", "ba-enrich-stories.md"), ("commands", "ba-sync-stories.md"), ("commands", "ba-generate-report.md")):
            text = read_plugin(*parts)
            self.assertIn("detailed_stories.md", text, parts)
            self.assertIn("ultra-lean", text.lower(), parts)

    def test_the_report_and_run_command_use_the_consolidated_file(self):
        run = read_plugin("commands", "ba-run.md")
        self.assertIn("stories/detailed_stories.md", run)
        self.assertIn("never one file per story", run)
        self.assertIn("stories/detailed_stories.md", read_plugin("commands", "ba-generate-report.md"))

    def test_the_schema_describes_the_draft(self):
        schema = json.loads(read_plugin("schemas", "development-stories.schema.json"))
        story = schema["properties"]["stories"]["items"]
        self.assertEqual(set(story["properties"]), {"story_id", "summary", "lean_acceptance_criteria", "detailed", "lean_reviewed", "source_requirement_ids", "applied_decisions"})
        self.assertEqual(set(story["properties"]["detailed"]["properties"]), set(common.DETAILED_KEYS))
        self.assertEqual(set(story["properties"]["detailed"]["required"]), set(common.DETAILED_REQUIRED))

    def test_the_example_draft_in_the_skill_is_valid(self):
        text = read_plugin("skills", "story-generation", "SKILL.md")
        block = re.search(r"```json\n(.*?)\n```", text, re.S).group(1)
        draft = json.loads(block)
        requirements = {"REQ-001": REQUIREMENTS[0]}
        errors, warnings = validator.validate_draft(draft, requirements, None)
        self.assertEqual((errors, warnings), ([], []))

    def test_the_readme_examples_match_what_the_scripts_write(self):
        text = read_plugin("README.md")
        if "Ultra-lean story in the document:" not in text:
            # sdlc-pipeline does not copy the upstream BA README; the check runs once our README carries the examples.
            self.skipTest("the upstream BA README with the story examples is not part of sdlc-pipeline")
        lean = re.search(r"Ultra-lean story in the document:\n\n```markdown\n(.*?)\n```", text, re.S).group(1)
        stories, problems = common.parse_section(lean)
        self.assertEqual((problems, stories[0]["story_id"], stories[0]["summary"]), ([], "US-001", "Registered user login"))
        self.assertEqual(len(stories[0]["acceptance_criteria"]), 1)
        self.assertEqual(common.render_section([common.render_lean(stories[0])]).rstrip("\n"), lean)
        detailed = re.search(r"The matching detailed story in `stories/detailed_stories.md`:\n\n```markdown\n(.*?)\n```", text, re.S).group(1)
        parsed, problems = common.parse_detailed_document(detailed)
        self.assertEqual(problems, [])
        self.assertEqual(common.render_detailed(parsed[0]), detailed.split("\n\n", 1)[1])


if __name__ == "__main__":
    unittest.main()
