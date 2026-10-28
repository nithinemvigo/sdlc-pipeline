"""Tests for the master command /sdlc-pipeline:ba-run (standard library only).

Run from the plugin root:
    python -m unittest discover -s tests -v

The command itself is a prompt, so its conduct (asking questions, following the phase files)
depends on the model and cannot be unit-tested. What is tested here:

* the command file is well formed and refers only to files, scripts and commands that exist,
  and the phase commands remain independent of it;
* the script sequence the command orchestrates behaves as the specification requires, driven
  through the real command-line interfaces: full run, all gaps skipped, unresolved Critical/High
  gaps, Critical/High resolved with Medium/Low left open or skipped, an interrupted and resumed
  triage, and a phase that fails its validation gate. The story-generation gate is evaluated
  exactly as the command specifies it (``PipelineCase.blockers``).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_story_scripts import DOCUMENT, REQUIREMENTS, make_gap, standard_stories

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = os.path.join(PLUGIN_ROOT, "scripts")
COMMANDS = os.path.join(PLUGIN_ROOT, "commands")

PHASE_COMMANDS = ["start-analysis", "analyse-gaps", "triage-gaps", "generate-stories", "enrich-stories", "sync-stories", "generate-report"]


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return None
    return dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)


class CommandFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read_text(os.path.join(COMMANDS, "ba-run.md"))

    def test_frontmatter_and_name(self):
        meta = frontmatter(self.text)
        self.assertIsNotNone(meta)
        self.assertTrue(meta["description"].strip())
        tools = [t.strip() for t in meta["allowed-tools"].replace("Bash(", "Bash(").split(",")]
        for needed in ("Read", "Write", "Agent", "AskUserQuestion"):
            self.assertIn(needed, tools)
        # The command is named by its file: commands/ba-run.md -> /sdlc-pipeline:ba-run.
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["name"], "sdlc-pipeline")

    def test_every_plugin_path_it_mentions_exists(self):
        paths = set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+\.(?:md|py|json))", self.text))
        self.assertTrue(paths)
        for rel in paths:
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN_ROOT, rel)), rel)

    def test_it_orchestrates_every_phase_command_it_reuses(self):
        for name in ("start-analysis", "analyse-gaps", "triage-gaps", "generate-stories", "enrich-stories", "generate-report"):
            self.assertIn(f"commands/ba-{name}.md", self.text)

    def test_commands_it_names_exist(self):
        for name in set(re.findall(r"/sdlc-pipeline:(ba-[a-z-]+)", self.text)):
            self.assertTrue(os.path.isfile(os.path.join(COMMANDS, name + ".md")), name)

    def test_script_subcommands_it_names_exist(self):
        for script, subcommand in set(re.findall(r"scripts/([a-z-]+\.py) ([a-z-]+) --", self.text)):
            source = read_text(os.path.join(SCRIPTS, script))
            self.assertRegex(source, r"""["']%s["']""" % re.escape(subcommand), f"{script} {subcommand}")

    def test_required_rules_are_stated(self):
        for phrase in (
            "every Critical and High priority gap has status `resolved`",
            "Medium and Low gaps never affect the gate",
            "Nothing the user selects can bypass the gate",
            "Resolve the blocking gaps now",
            "Exit and resume later",
            "single consolidated file `stories/detailed_stories.md`",
            "only Story ID, concise summary and one functional acceptance-criteria statement",
            "skip all remaining gaps",
            "STALE",
            "UNAVAILABLE",
            "Never install dependencies",
            "never into the plugin directory",
            "illustrative or estimated",
        ):
            self.assertIn(phrase, self.text)

    def test_gate_is_evaluated_from_the_store_and_runs_before_any_story_write(self):
        gate = self.text.index("The story-generation gate (mandatory)")
        self.assertIn("gap-register-store.py list", self.text[gate:self.text.index("## Step 1")])
        step6 = self.text[self.text.index("## Step 6"):self.text.index("## Step 7")]
        self.assertIn("Precondition: the story-generation gate must have passed", step6)
        self.assertLess(step6.index("Precondition"), step6.index("Follow `ba-generate-stories.md`"))

    def test_skip_paths_return_to_the_gate_not_to_phase_3(self):
        step5 = self.text[self.text.index("## Step 5"):self.text.index("## Step 6")]
        self.assertIn("it does **not** continue to Phase 3", step5)
        self.assertNotIn("continues to Phase 3", step5)
        for phrase in ("5b — Story-generation gate", "5c — Blocker triage pass", "Repeat 5b–5c until the gate passes or the user exits"):
            self.assertIn(phrase, step5)

    def test_it_no_longer_claims_open_or_skipped_gaps_never_block(self):
        self.assertNotIn("Open and skipped gaps do not block story generation", self.text)
        self.assertNotIn("they never block Phase 3", self.text)

    def test_no_invented_example_counts(self):
        for line in self.text.splitlines():
            if "<" in line:
                continue
            self.assertFalse(re.search(r"(?i)\b\d+ (requirements|gaps|stories)\b", line), line)

    def test_phase_commands_remain_independent_of_the_master(self):
        for name in PHASE_COMMANDS:
            text = read_text(os.path.join(COMMANDS, "ba-" + name + ".md"))
            self.assertIsNotNone(frontmatter(text), name)
            self.assertNotIn("sdlc-pipeline:ba-run", text, name)


class PipelineCase(unittest.TestCase):
    """Drives the real scripts the master command orchestrates, as separate processes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ba-master-test-")
        self.root = os.path.join(self.tmp, "project")
        self.scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(os.path.join(self.root, "atomic_requirements"))
        os.makedirs(os.path.join(self.root, "requirements"))
        os.makedirs(self.scratch)
        self.doc = os.path.join(self.root, "requirements", "business-requirements.md")
        with open(self.doc, "w", encoding="utf-8", newline="") as handle:
            handle.write(DOCUMENT)
        self.atomic = os.path.join(self.root, "atomic_requirements", "atomic_requirements.json")
        self.write_json(self.atomic, REQUIREMENTS)
        self.register = os.path.join(self.root, "gaps", "gaps.json")
        self.report = os.path.join(self.root, "report", "phase3-report.html")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read_bytes(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def write_json(self, path, data):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def run_script(self, script, *argv):
        proc = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, script), *argv], capture_output=True, text=True, encoding="utf-8")
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = {"stdout": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, data

    def gaps(self, *argv):
        return self.run_script("gap-register-store.py", *argv, "--project-root", self.root)

    def stories(self, *argv):
        return self.run_script("sync-development-stories.py", *argv, "--project-root", self.root)

    # Phase 2a: save a new analysis through the store, as the command does.
    def save_gaps(self, gaps):
        draft = os.path.join(self.scratch, "gaps.draft.json")
        self.write_json(draft, gaps)
        code, result = self.gaps("save", "--draft", draft, "--mode", "new")
        self.assertEqual(code, 0, result)

    def default_gaps(self):
        self.save_gaps([
            make_gap("GAP-001", "Critical", "Should the account lock after failed logins?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "How long is a reset link valid?", ["REQ-002"]),
            make_gap("GAP-003", "Medium", "Which formats can reports be exported in?", ["REQ-005"]),
        ])

    def decide(self, gap_id, text):
        path = os.path.join(self.scratch, f"{gap_id}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        code, result = self.gaps("resolve", "--gap-id", gap_id, "--decision-file", path)
        self.assertEqual(code, 0, result)

    def blockers(self):
        """The story-generation gate, exactly as run.md defines it: Critical/High gaps in the queue.

        Returns the list of blocking gap IDs ([] = gate passes), or None when `list` fails and the
        gate therefore cannot be verified (which also stops the pipeline).
        """
        code, listing = self.gaps("list")
        if code != 0:
            return None
        return [g["gap_id"] for g in listing["queue"] if g["priority"] in ("Critical", "High")]

    def four_level_gaps(self):
        self.save_gaps([
            make_gap("GAP-001", "Critical", "Should the account lock after failed logins?", ["REQ-001", "REQ-003"]),
            make_gap("GAP-002", "High", "How long is a reset link valid?", ["REQ-002"]),
            make_gap("GAP-003", "Medium", "Which events must the audit log record?", ["REQ-004"]),
            make_gap("GAP-004", "Low", "Which formats can reports be exported in?", ["REQ-005"]),
        ])

    def counts(self):
        code, result = self.gaps("summary")
        self.assertEqual(code, 0, result)
        return {status: result["counts"][status] for status in ("open", "skipped", "resolved")}

    # Phase 3a: generate through the store.
    def generate_stories(self):
        draft = os.path.join(self.scratch, "draft.json")
        self.write_json(draft, {"stories": standard_stories()})
        code, info = self.stories("inspect", "--target", self.doc)
        self.assertEqual(info["status"], "OK", info)
        code, result = self.stories("apply", "--draft", draft, "--target", self.doc, "--expected-source-sha256", info["target"]["source_sha256"])
        self.assertEqual(code, 0, result)
        return result

    def enrich(self, gap_id, outcome="incorporated"):
        code, export = self.stories("export", "--draft-out", os.path.join(self.scratch, "existing.json"))
        self.assertEqual(code, 0, export)
        draft = export["draft"]
        draft["decisions_reviewed"] = [{"gap_id": gap_id, "outcome": outcome}]
        path = os.path.join(self.scratch, "enrich.json")
        self.write_json(path, draft)
        code, result = self.stories("apply", "--draft", path)
        self.assertEqual(code, 0, result)
        return result


class FullRunTests(PipelineCase):
    def test_full_run_resolves_gaps_generates_stories_enriches_and_reports(self):
        # Phase 1 gate
        code, _ = self.run_script("validate-atomic-requirements.py", self.atomic)
        self.assertEqual(code, 0)
        # Phase 2: analyse, triage (all resolved)
        self.default_gaps()
        code, info = self.gaps("inspect")
        self.assertEqual(info["status"], "UNCHANGED", info)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "gaps", "gap-analysis.html")))
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.decide(gap_id, f"Decision for {gap_id}: confirmed by the business owner.")
        self.assertEqual(self.counts(), {"open": 0, "skipped": 0, "resolved": 3})
        code, listing = self.gaps("list")
        self.assertEqual(listing["eligible_count"], 0)
        self.assertEqual(self.blockers(), [])
        # Phase 3: generate, enrich, report
        result = self.generate_stories()
        self.assertEqual(len(result["created"]), 6)
        code, info = self.stories("inspect")
        self.assertEqual({p["gap_id"] for p in info["pending_decisions"]}, {"GAP-001", "GAP-002", "GAP-003"})
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.enrich(gap_id, "no_change_required")
        code, info = self.stories("inspect")
        self.assertEqual(info["pending_decisions"], [])
        code, result = self.stories("regenerate-report")
        self.assertEqual(code, 0, result)
        self.assertTrue(result["report"]["generated"])
        self.assertTrue(os.path.isfile(self.report))
        page = read_text(self.report)
        self.assertIn("Decision for GAP-001", page)
        code, summary = self.stories("summary")
        self.assertEqual(code, 0, summary)
        self.assertTrue(summary["validation"]["passed"])
        self.assertEqual(summary["stories"], 6)


class SkipAllTests(PipelineCase):
    def test_all_gaps_skipped_blocks_story_generation(self):
        self.default_gaps()
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            code, result = self.gaps("skip", "--gap-id", gap_id)
            self.assertEqual(code, 0, result)
        self.assertEqual(self.counts(), {"open": 0, "skipped": 3, "resolved": 0})
        # Critical and High are unresolved, so the master command may not start Phase 3.
        self.assertEqual(self.blockers(), ["GAP-001", "GAP-002"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))
        self.assertFalse(os.path.exists(self.report))

    def test_skip_all_remaining_does_not_bypass_the_gate(self):
        self.default_gaps()
        self.decide("GAP-001", "Lock the account after five failed attempts for 30 minutes.")
        # "Skip all remaining" (Medium/Low only) records GAP-003 as skipped; the High GAP-002 is untouched.
        code, result = self.gaps("skip", "--gap-id", "GAP-003")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.counts(), {"open": 1, "skipped": 1, "resolved": 1})
        self.assertEqual(self.blockers(), ["GAP-002"])
        # Skipping the blocker individually changes its status but not the gate.
        code, result = self.gaps("skip", "--gap-id", "GAP-002")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.blockers(), ["GAP-002"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))

    def test_skipping_never_records_a_decision(self):
        self.default_gaps()
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.gaps("skip", "--gap-id", gap_id)
        with open(self.register, encoding="utf-8") as handle:
            self.assertTrue(all(g["decisions_recorded"] == [] for g in json.load(handle)))
        self.assertEqual(self.counts(), {"open": 0, "skipped": 3, "resolved": 0})

    def test_standalone_generate_stories_is_still_not_blocked_by_gaps(self):
        # /sdlc-pipeline:ba-generate-stories is independent of the master gate and unchanged.
        self.default_gaps()
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.gaps("skip", "--gap-id", gap_id)
        self.generate_stories()
        code, result = self.stories("regenerate-report")
        self.assertEqual(code, 0, result)
        page = read_text(self.report)
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.assertIn(gap_id, page)
        self.assertEqual(self.counts(), {"open": 0, "skipped": 3, "resolved": 0})


class GateTests(PipelineCase):
    def test_unresolved_critical_or_high_blocks_whatever_the_state_of_the_rest(self):
        self.four_level_gaps()
        self.assertEqual(self.blockers(), ["GAP-001", "GAP-002"])
        self.decide("GAP-001", "Lock the account after five failed attempts for 30 minutes.")
        self.assertEqual(self.blockers(), ["GAP-002"])  # a resolved Critical does not release an open High
        self.gaps("skip", "--gap-id", "GAP-002")
        self.assertEqual(self.blockers(), ["GAP-002"])  # skipped is not resolved

    def test_blockers_are_listed_critical_first(self):
        self.save_gaps([
            make_gap("GAP-001", "High", "How long is a reset link valid?", ["REQ-002"]),
            make_gap("GAP-002", "Low", "Which formats can reports be exported in?", ["REQ-005"]),
            make_gap("GAP-003", "Critical", "Should the account lock after failed logins?", ["REQ-001"]),
        ])
        self.assertEqual(self.blockers(), ["GAP-003", "GAP-001"])

    def test_gate_passes_with_critical_and_high_resolved_and_medium_low_open_or_skipped(self):
        self.four_level_gaps()
        self.decide("GAP-001", "Lock the account after five failed attempts for 30 minutes.")
        self.decide("GAP-002", "A reset link is valid for 24 hours.")
        self.gaps("skip", "--gap-id", "GAP-003")  # Medium skipped, Low still open
        self.assertEqual(self.counts(), {"open": 1, "skipped": 1, "resolved": 2})
        self.assertEqual(self.blockers(), [])
        # Phase 3 proceeds; only the resolved decisions are pending for enrichment.
        self.generate_stories()
        code, info = self.stories("inspect")
        self.assertEqual({p["gap_id"] for p in info["pending_decisions"]}, {"GAP-001", "GAP-002"})
        self.assertEqual(self.counts(), {"open": 1, "skipped": 1, "resolved": 2})

    def test_gate_passes_for_an_empty_register(self):
        self.save_gaps([])
        code, listing = self.gaps("list")
        self.assertEqual(code, 0, listing)
        self.assertEqual(listing["eligible_count"], 0)
        self.assertEqual(self.blockers(), [])

    def test_reopening_a_critical_gap_blocks_the_gate_again(self):
        self.four_level_gaps()
        self.decide("GAP-001", "Lock the account after five failed attempts for 30 minutes.")
        self.decide("GAP-002", "A reset link is valid for 24 hours.")
        self.assertEqual(self.blockers(), [])
        code, result = self.gaps("reopen", "--gap-id", "GAP-001")
        self.assertEqual(code, 0, result)
        self.assertEqual(self.blockers(), ["GAP-001"])

    def test_gate_cannot_be_verified_when_the_register_is_missing_or_invalid(self):
        self.assertIsNone(self.blockers())  # no register yet
        self.four_level_gaps()
        with open(self.register, encoding="utf-8") as handle:
            gaps = json.load(handle)
        gaps[0]["status"] = "resolved"  # resolved without a decision
        self.write_json(self.register, gaps)
        self.assertIsNone(self.blockers())

    def test_gate_cannot_be_verified_when_the_atomic_requirements_changed(self):
        self.four_level_gaps()
        self.write_json(self.atomic, REQUIREMENTS[:-1])
        self.assertIsNone(self.blockers())


class PartialResolutionTests(PipelineCase):
    def test_only_resolved_gap_decisions_enrich_stories(self):
        self.four_level_gaps()
        text = "Lock the account after five consecutive failed login attempts for 30 minutes."
        self.decide("GAP-001", text)
        self.decide("GAP-002", "A reset link is valid for 24 hours.")
        self.gaps("skip", "--gap-id", "GAP-003")
        # GAP-004 (Low) stays open. Neither it nor the skipped Medium gap blocks Phase 3.
        self.assertEqual(self.blockers(), [])
        self.generate_stories()
        code, info = self.stories("inspect")
        self.assertEqual({p["gap_id"] for p in info["pending_decisions"]}, {"GAP-001", "GAP-002"})
        self.enrich("GAP-001", "no_change_required")
        self.enrich("GAP-002", "no_change_required")
        with open(self.paths_state(), encoding="utf-8") as handle:
            ledger = json.load(handle)["decision_ledger"]
        self.assertEqual(set(ledger), {"GAP-001", "GAP-002"})
        code, _ = self.stories("regenerate-report")
        self.assertEqual(code, 0)
        page = read_text(self.report)
        self.assertIn(text, page)
        self.assertEqual(self.counts(), {"open": 1, "skipped": 1, "resolved": 2})

    def paths_state(self):
        return os.path.join(self.root, "stories", "story-generation-state.json")


class InterruptedRunTests(PipelineCase):
    def test_answers_and_triage_status_survive_an_interruption_and_resume(self):
        self.default_gaps()
        self.decide("GAP-001", "Lock the account after five failed attempts for 30 minutes.")
        self.gaps("skip", "--gap-id", "GAP-002")
        # The user stops here (or the gate is blocked and they exit): Phase 3 is not started.
        self.assertEqual(self.blockers(), ["GAP-002"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))
        # A new process (the resumed run) sees everything exactly as it was left.
        code, info = self.gaps("inspect")
        self.assertEqual(info["status"], "UNCHANGED", info)
        code, listing = self.gaps("list")
        self.assertEqual([g["gap_id"] for g in listing["queue"]], ["GAP-002", "GAP-003"])
        self.assertEqual({k: listing["counts"][k] for k in ("open", "skipped", "resolved")}, {"open": 1, "skipped": 1, "resolved": 1})
        with open(self.register, encoding="utf-8") as handle:
            gaps = {g["gap_id"]: g for g in json.load(handle)}
        self.assertEqual(len(gaps["GAP-001"]["decisions_recorded"]), 1)
        # The resumed run resolves the blocker, the gate passes, and Phase 3 starts with GAP-003 still open.
        self.decide("GAP-002", "A reset link is valid for 24 hours.")
        self.assertEqual(self.blockers(), [])
        self.generate_stories()
        self.assertEqual(self.counts(), {"open": 1, "skipped": 0, "resolved": 2})

    def test_rerunning_story_generation_neither_duplicates_nor_changes_anything(self):
        self.default_gaps()
        self.generate_stories()
        with open(self.doc, "rb") as handle:
            before = handle.read()
        draft = os.path.join(self.scratch, "export.json")
        code, export = self.stories("export", "--draft-out", draft)
        self.assertEqual(code, 0, export)
        code, info = self.stories("inspect")
        self.assertEqual(info["uncovered_requirements"], [])
        self.assertFalse(info["manual_changes"]["section_modified"])
        code, result = self.stories("apply", "--draft", draft)
        self.assertEqual(code, 0, result)
        self.assertFalse(result["document_changed"])
        with open(self.doc, "rb") as handle:
            self.assertEqual(handle.read(), before)


class GateFailureTests(PipelineCase):
    def test_invalid_atomic_requirements_fail_the_phase_1_gate_and_stop_everything_after(self):
        broken = [dict(REQUIREMENTS[0], extra="not allowed"), REQUIREMENTS[1]]
        self.write_json(self.atomic, broken)
        code, _ = self.run_script("validate-atomic-requirements.py", self.atomic)
        self.assertNotEqual(code, 0)
        code, info = self.gaps("inspect")
        self.assertEqual(info["status"], "INPUT_INVALID", info)
        self.assertFalse(os.path.exists(self.register))
        code, info = self.stories("inspect")
        self.assertEqual(info["status"], "INPUT_INVALID", info)
        code, result = self.stories("apply", "--draft", os.path.join(self.scratch, "none.json"), "--target", self.doc)
        self.assertNotEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))
        self.assertFalse(os.path.exists(self.report))

    def test_missing_atomic_requirements_are_reported_not_created(self):
        os.remove(self.atomic)
        code, info = self.gaps("inspect")
        self.assertEqual(info["status"], "INPUT_MISSING", info)
        self.assertFalse(os.path.exists(self.register))

    def test_invalid_gap_register_fails_the_phase_2_gate(self):
        self.default_gaps()
        with open(self.register, encoding="utf-8") as handle:
            gaps = json.load(handle)
        gaps[0]["status"] = "resolved"  # resolved without a decision
        self.write_json(self.register, gaps)
        code, result = self.run_script("validate-gap-register.py", self.register)
        self.assertEqual(code, 1, result)
        code, result = self.gaps("list")
        self.assertNotEqual(code, 0)
        code, info = self.stories("inspect")
        self.assertEqual(info["gaps"]["status"], "INVALID", info)

    def test_failed_report_keeps_valid_work_and_the_previous_report(self):
        self.default_gaps()
        self.generate_stories()
        self.assertTrue(os.path.isfile(self.report))
        previous = read_text(self.report)
        document = self.read_bytes(self.doc)
        # Break the report's input (the recorded document) without touching the story state.
        shutil.move(self.doc, self.doc + ".moved")
        code, result = self.stories("regenerate-report")
        self.assertNotEqual(code, 0)
        self.assertFalse(result.get("report", {}).get("generated", False))
        self.assertEqual(read_text(self.report), previous)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "stories", "story-generation-state.json")))
        shutil.move(self.doc + ".moved", self.doc)
        self.assertEqual(self.read_bytes(self.doc), document)


if __name__ == "__main__":
    unittest.main()
