"""Tests for the pipeline checkpoint and resume script (standard library only).

Run from the plugin root:
    python -m unittest discover -s tests -v

Every test drives the real command-line interfaces as separate processes, so a "resumed" run is a
genuinely new process that knows nothing but what was written to disk.
"""

import json
import os
import unittest

from test_master_pipeline import COMMANDS, PHASE_COMMANDS, SCRIPTS, PipelineCase, read_text
from test_story_scripts import REQUIREMENTS

OPS = [
    "resolve_source", "atomic_requirements", "gap_analysis", "gap_triage", "gate_validation",
    "generate_stories", "enrich_stories", "phase3_report", "final_validation",
]


class CheckpointCase(PipelineCase):
    def ps(self, *argv):
        return self.run_script("pipeline-state.py", *argv, "--project-root", self.root)

    def op(self, verb, name, *extra):
        return self.ps(verb, "--operation", name, *extra)

    def ok(self, verb, name, *extra):
        code, result = self.op(verb, name, *extra)
        self.assertEqual(code, 0, result)
        return result

    def state(self):
        with open(self.checkpoint, encoding="utf-8") as handle:
            return json.load(handle)

    def write_state(self, data):
        self.write_json(self.checkpoint, data)

    def verdicts(self):
        code, info = self.ps("inspect")
        self.assertEqual(code, 0, info)
        return info, {row["name"]: row["verdict"] for row in info.get("operations", [])}

    def setUp(self):
        super().setUp()
        self.checkpoint = os.path.join(self.root, ".ba-requirements", "pipeline-state.json")

    # ------------------------------------------------------------ pipeline stages as the command runs them
    def phase1(self):
        code, result = self.ps("begin")
        self.assertEqual(code, 0, result)
        self.ok("start", "resolve_source", "--sources", self.doc)
        self.ok("complete", "resolve_source", "--sources", self.doc)
        self.ok("start", "atomic_requirements")
        self.ok("complete", "atomic_requirements")

    def phase2a(self, four_levels=False):
        self.ok("start", "gap_analysis")
        self.four_level_gaps() if four_levels else self.default_gaps()
        self.ok("complete", "gap_analysis")

    def triage(self, decisions, skips=()):
        """Answer and skip gaps through the store, recording each one in the checkpoint at once."""
        for gap_id in decisions:
            self.decide(gap_id, f"Decision for {gap_id}: confirmed by the business owner.")
            code, result = self.ps("triage-event", "--gap-id", gap_id, "--action", "resolved")
            self.assertEqual(code, 0, result)
        for gap_id in skips:
            self.gaps("skip", "--gap-id", gap_id)
            code, result = self.ps("triage-event", "--gap-id", gap_id, "--action", "skipped")
            self.assertEqual(code, 0, result)

    def through_gate(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")
        self.triage(["GAP-001", "GAP-002", "GAP-003"])
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.ok("complete", "gate_validation")

    def through_stories(self):
        self.through_gate()
        self.ok("start", "generate_stories")
        self.generate_stories()
        self.ok("complete", "generate_stories")

    def through_report(self):
        self.through_stories()
        self.ok("start", "enrich_stories")
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.enrich(gap_id, "no_change_required")
        self.ok("complete", "enrich_stories")
        self.ok("start", "phase3_report")
        code, result = self.stories("regenerate-report")
        self.assertEqual(code, 0, result)
        self.ok("complete", "phase3_report")

    def append_to_source(self, text="\n\n## Added requirement\nThe system shall export audit logs.\n"):
        with open(self.doc, "a", encoding="utf-8", newline="") as handle:
            handle.write(text)


class CheckpointFileTests(CheckpointCase):
    def test_no_checkpoint_means_a_new_run(self):
        code, info = self.ps("inspect")
        self.assertEqual(code, 0, info)
        self.assertEqual(info["state_status"], "NO_STATE")
        self.assertFalse(os.path.exists(self.checkpoint))

    def test_begin_writes_a_valid_checkpoint_atomically(self):
        code, result = self.ps("begin")
        self.assertEqual(code, 0, result)
        state = self.state()
        self.assertEqual([o["name"] for o in state["operations"]], OPS)
        self.assertEqual({o["status"] for o in state["operations"]}, {"pending"})
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["run_id"], result["run_id"])
        self.assertIsNone(state["last_completed_operation"])
        for field in ("source_files", "current_operation", "updated_at", "operations"):
            self.assertIn(field, state)
        for entry in state["operations"]:
            for field in ("name", "status", "started_at", "ended_at", "input_fingerprints", "output_paths", "error"):
                self.assertIn(field, entry)
        leftovers = [n for n in os.listdir(os.path.dirname(self.checkpoint)) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_a_second_begin_needs_an_explicit_replace_and_archives_the_old_run(self):
        self.ps("begin")
        first = self.state()["run_id"]
        code, result = self.ps("begin")
        self.assertEqual(code, 1, result)
        self.assertEqual(self.state()["run_id"], first)
        code, result = self.ps("begin", "--replace")
        self.assertEqual(code, 0, result)
        self.assertNotEqual(result["run_id"], first)
        archived = os.path.join(self.root, result["archived_previous"])
        with open(archived, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["run_id"], first)

    def test_checkpoints_never_copy_artifact_content(self):
        self.through_report()
        text = read_text(self.checkpoint)
        self.assertNotIn("Decision for GAP-001", text)
        self.assertNotIn("account lock", text)
        self.assertNotIn(REQUIREMENTS[0]["description"], text)

    def test_operations_must_run_in_order(self):
        self.ps("begin")
        code, result = self.op("start", "gap_analysis")
        self.assertEqual(code, 1, result)
        self.assertEqual(result["incomplete_before"], ["resolve_source", "atomic_requirements"])
        code, result = self.op("start", "not_an_operation")
        self.assertEqual(code, 1, result)

    def test_start_persists_in_progress_before_the_work_and_complete_records_outputs(self):
        self.ps("begin")
        self.ok("start", "resolve_source", "--sources", self.doc)
        state = self.state()
        self.assertEqual(state["current_operation"], "resolve_source")
        entry = state["operations"][0]
        self.assertEqual(entry["status"], "in_progress")
        self.assertTrue(entry["started_at"])
        self.ok("complete", "resolve_source", "--sources", self.doc)
        self.ok("start", "atomic_requirements")
        self.ok("complete", "atomic_requirements")
        state = self.state()
        self.assertEqual(state["last_completed_operation"], "atomic_requirements")
        self.assertIsNone(state["current_operation"])
        entry = state["operations"][1]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["output_paths"], ["atomic_requirements/atomic_requirements.json"])
        self.assertIn("atomic_requirements", entry["output_fingerprints"])
        self.assertTrue(entry["ended_at"])

    def test_completing_without_a_valid_result_fails_the_operation_and_keeps_prior_work(self):
        self.ps("begin")
        self.ok("start", "resolve_source", "--sources", self.doc)
        self.ok("complete", "resolve_source", "--sources", self.doc)
        self.ok("start", "atomic_requirements")
        self.write_json(self.atomic, [dict(REQUIREMENTS[0], extra="not allowed")])
        code, result = self.op("complete", "atomic_requirements")
        self.assertEqual(code, 1, result)
        state = self.state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["operations"][1]["status"], "failed")
        self.assertTrue(state["operations"][1]["error"]["problems"])
        self.assertEqual(state["operations"][0]["status"], "completed")
        # Nothing after a failed Phase 1 can start.
        code, result = self.op("start", "gap_analysis")
        self.assertEqual(code, 1, result)
        # After the issue is corrected the same operation resumes and completes.
        self.write_json(self.atomic, REQUIREMENTS)
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "atomic_requirements")
        self.ok("start", "atomic_requirements")
        self.ok("complete", "atomic_requirements")
        self.assertEqual(self.state()["status"], "in_progress")

    def test_fail_and_block_retain_their_error(self):
        self.ps("begin")
        self.ok("start", "resolve_source", "--sources", self.doc)
        self.ok("fail", "resolve_source", "--error", "source folder is empty")
        state = self.state()
        self.assertEqual((state["status"], state["operations"][0]["status"]), ("failed", "failed"))
        self.assertEqual(state["operations"][0]["error"]["message"], "source folder is empty")
        self.ok("start", "resolve_source")
        self.ok("block", "resolve_source", "--reason", "waiting for the user to confirm the source set")
        state = self.state()
        self.assertEqual((state["status"], state["operations"][0]["status"]), ("blocked", "blocked"))


class CorruptCheckpointTests(CheckpointCase):
    def test_garbage_is_reported_not_overwritten_and_archived_on_a_fresh_run(self):
        os.makedirs(os.path.dirname(self.checkpoint))
        with open(self.checkpoint, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        code, info = self.ps("inspect")
        self.assertEqual((code, info["state_status"]), (0, "CORRUPT"), info)
        self.assertEqual(info["recommended_action"], "offer_fresh_run")
        self.assertEqual(read_text(self.checkpoint), "{ this is not json")
        for verb in ("resume",):
            code, result = self.ps(verb)
            self.assertEqual(code, 1, result)
        code, result = self.ps("begin")
        self.assertEqual(code, 1, result)
        self.assertEqual(read_text(self.checkpoint), "{ this is not json")
        code, result = self.ps("begin", "--replace")
        self.assertEqual(code, 0, result)
        with open(os.path.join(self.root, result["archived_previous"]), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "{ this is not json")

    def test_incompatible_schema_is_reported(self):
        self.ps("begin")
        state = self.state()
        state["schema_version"] = "9.0"
        self.write_state(state)
        code, info = self.ps("inspect")
        self.assertEqual(info["state_status"], "INCOMPATIBLE", info)

    def test_an_inconsistent_checkpoint_is_corrupt(self):
        self.phase1()
        state = self.state()
        state["operations"][0]["status"] = "pending"  # a later operation is completed without its predecessor
        self.write_state(state)
        code, info = self.ps("inspect")
        self.assertEqual(info["state_status"], "CORRUPT", info)
        self.assertTrue(any("completed operation follows" in e for e in info["errors"]), info)

    def test_unknown_operations_and_missing_fields_are_corrupt(self):
        self.ps("begin")
        state = self.state()
        state["operations"][3]["name"] = "something_else"
        self.write_state(state)
        self.assertEqual(self.ps("inspect")[1]["state_status"], "CORRUPT")
        self.write_state({"schema_version": "1.0", "run_id": "x"})
        self.assertEqual(self.ps("inspect")[1]["state_status"], "CORRUPT")
        self.write_state([1, 2])
        self.assertEqual(self.ps("inspect")[1]["state_status"], "CORRUPT")


class ResumeTests(CheckpointCase):
    def test_an_interrupted_run_resumes_at_the_first_incomplete_operation(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")  # the process dies here
        info, verdicts = self.verdicts()
        self.assertEqual(info["state_status"], "INCOMPLETE")
        self.assertEqual(info["last_completed_operation"], "gap_analysis")
        self.assertEqual(info["current_operation"], "gap_triage")
        self.assertEqual(info["resume_from"], "gap_triage")
        self.assertEqual(info["reusable"], ["resolve_source", "atomic_requirements", "gap_analysis"])
        self.assertEqual(info["would_invalidate"], [])
        code, resumed = self.ps("resume")
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["resume_from"], "gap_triage")
        self.assertEqual(resumed["reused"], ["resolve_source", "atomic_requirements", "gap_analysis"])
        self.assertEqual(resumed["rerun"], ["gap_triage"])
        # The interrupted operation is simply started again.
        result = self.ok("start", "gap_triage")
        self.assertEqual(result["attempt"], 2)
        # Completed operations were not repeated: their records and timestamps are untouched.
        state = self.state()
        self.assertEqual(state["operations"][2]["attempts"], 1)

    def test_every_triage_answer_and_skip_is_recoverable_after_an_interruption(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")
        self.triage(["GAP-001"], skips=["GAP-002"])
        # Interrupted before the pass ends: a new process sees every answer, in the register and the checkpoint.
        code, info = self.ps("inspect")
        self.assertEqual(info["resume_from"], "gap_triage")
        self.assertEqual({k: info["triage"][k] for k in ("events", "presented", "resolved", "skipped")},
                         {"events": 2, "presented": 2, "resolved": 1, "skipped": 1})
        self.assertNotIn("triage_drift", info)
        code, listing = self.gaps("list")
        self.assertEqual([g["gap_id"] for g in listing["queue"]], ["GAP-002", "GAP-003"])
        events = self.state()["triage"]["events"]
        self.assertEqual([(e["gap_id"], e["action"], e["status_after"]) for e in events],
                         [("GAP-001", "resolved", "resolved"), ("GAP-002", "skipped", "skipped")])
        code, resumed = self.ps("resume")
        self.assertEqual(code, 0, resumed)
        self.assertEqual(len(self.state()["triage"]["events"]), 2)

    def test_triage_events_are_checked_against_the_register(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")
        code, result = self.ps("triage-event", "--gap-id", "GAP-001", "--action", "resolved")
        self.assertEqual(code, 1, result)  # not saved in the register yet
        code, result = self.ps("triage-event", "--gap-id", "GAP-099", "--action", "presented")
        self.assertEqual(code, 1, result)
        code, result = self.ps("triage-event", "--gap-id", "GAP-001", "--action", "presented")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["recorded"]["status_after"], "open")
        self.assertEqual(self.state()["triage"]["events"][0]["priority"], "Critical")

    def test_register_ahead_of_the_checkpoint_is_reported_as_drift_not_lost(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")
        self.triage([], skips=["GAP-002"])
        self.decide("GAP-002", "A reset link is valid for 24 hours.")  # saved, then the process died before the event
        code, info = self.ps("inspect")
        self.assertTrue(any("GAP-002" in line for line in info["triage_drift"]), info)
        self.assertEqual(self.counts(), {"open": 2, "skipped": 0, "resolved": 1})

    def test_a_completed_run_is_never_resumed_or_silently_reused(self):
        self.through_report()
        self.ok("start", "final_validation")
        result = self.ok("complete", "final_validation")
        self.assertEqual(result["run_status"], "completed")
        code, info = self.ps("inspect")
        self.assertEqual((info["state_status"], info["recommended_action"]), ("COMPLETED", "offer_new_run"), info)
        self.assertTrue(info["artifacts_still_valid"])
        code, result = self.ps("resume")
        self.assertEqual(code, 1, result)
        code, result = self.op("start", "gap_analysis")
        self.assertEqual(code, 1, result)
        first = self.state()["run_id"]
        code, result = self.ps("begin", "--replace")
        self.assertEqual(code, 0, result)
        self.assertNotEqual(result["run_id"], first)
        self.assertEqual({o["status"] for o in self.state()["operations"]}, {"pending"})

    def test_a_valid_run_up_to_the_report_resumes_at_final_validation_only(self):
        self.through_report()
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "final_validation")
        self.assertEqual(set(v for k, v in verdicts.items() if k != "final_validation"), {"valid"})
        # Phase 3 stories survive the checks even though Phase 3 appended its section to the source document.
        self.assertEqual(verdicts["resolve_source"], "valid")
        self.assertEqual(verdicts["atomic_requirements"], "valid")


class InvalidationTests(CheckpointCase):
    def test_a_changed_source_invalidates_that_operation_and_everything_after_it(self):
        self.phase1()
        self.phase2a()
        self.append_to_source()
        info, verdicts = self.verdicts()
        self.assertEqual(verdicts["resolve_source"], "invalid")
        self.assertEqual(info["resume_from"], "resolve_source")
        self.assertEqual(info["would_invalidate"], ["resolve_source", "atomic_requirements", "gap_analysis"])
        before = self.read_bytes(self.register)
        code, resumed = self.ps("resume")
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["resume_from"], "resolve_source")
        self.assertEqual(resumed["reused"], [])
        self.assertTrue(any("source file changed" in r for r in resumed["reasons"]), resumed)
        state = self.state()
        self.assertEqual({o["status"] for o in state["operations"]}, {"pending"})
        self.assertIsNone(state["last_completed_operation"])
        self.assertEqual(state["invalidations"][-1]["operations"], ["resolve_source", "atomic_requirements", "gap_analysis"])
        # Existing user decisions and artifacts are untouched; downstream phases reconcile them.
        self.assertEqual(self.read_bytes(self.register), before)

    def test_a_changed_atomic_requirements_file_invalidates_phase_2_onwards(self):
        self.through_gate()
        data = json.loads(self.read_bytes(self.atomic).decode("utf-8"))
        data[0]["description"] += " Locking also applies to the admin console."
        self.write_json(self.atomic, data)
        info, verdicts = self.verdicts()
        self.assertEqual(verdicts["resolve_source"], "valid")
        self.assertEqual(verdicts["atomic_requirements"], "invalid")
        self.assertEqual(info["would_invalidate"], OPS[1:5])

    def test_a_missing_generated_artifact_reruns_its_operation_and_what_follows(self):
        self.through_report()
        os.remove(self.report)
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "phase3_report")
        self.assertEqual(verdicts["enrich_stories"], "valid")
        self.assertEqual(info["would_invalidate"], ["phase3_report"])
        os.remove(self.atomic)
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "atomic_requirements")
        self.assertEqual(verdicts["gap_analysis"], "invalid")

    def test_a_corrupted_register_fails_validation_and_reruns_gap_analysis(self):
        self.through_gate()
        with open(self.register, "w", encoding="utf-8") as handle:
            handle.write("[ not json")
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "gap_analysis")
        self.assertEqual(verdicts["atomic_requirements"], "valid")

    def test_a_new_decision_after_stories_exist_reruns_enrichment_not_generation(self):
        self.phase1()
        self.phase2a(four_levels=True)
        self.ok("start", "gap_triage")
        self.triage(["GAP-001", "GAP-002"])
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.ok("complete", "gate_validation")
        self.ok("start", "generate_stories")
        self.generate_stories()
        self.ok("complete", "generate_stories")
        self.ok("start", "enrich_stories")
        for gap_id in ("GAP-001", "GAP-002"):
            self.enrich(gap_id, "no_change_required")
        self.ok("complete", "enrich_stories")
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "phase3_report")
        # A Medium gap is decided outside the pipeline: enrichment is stale, story generation is not.
        self.decide("GAP-003", "The audit log records logins, role changes and exports.")
        info, verdicts = self.verdicts()
        self.assertEqual(verdicts["generate_stories"], "valid")
        self.assertEqual(verdicts["gate_validation"], "valid")
        self.assertEqual(verdicts["enrich_stories"], "invalid")
        self.assertEqual(info["resume_from"], "enrich_stories")

    def test_changed_inputs_during_an_operation_stop_before_stale_results_are_applied(self):
        self.ps("begin")
        self.ok("start", "resolve_source", "--sources", self.doc)
        self.ok("complete", "resolve_source", "--sources", self.doc)
        self.ok("start", "atomic_requirements")
        self.append_to_source()
        code, result = self.op("check-inputs", "atomic_requirements")
        self.assertEqual(code, 1, result)
        self.assertEqual(result["code"], "INPUTS_CHANGED")
        self.assertEqual(result["restart_from"], "resolve_source")
        state = self.state()
        self.assertEqual((state["status"], state["operations"][1]["status"]), ("blocked", "blocked"))
        self.assertEqual(state["operations"][1]["error"]["code"], "INPUTS_CHANGED")
        # The operation cannot be completed while blocked; restarting from source analysis clears it.
        code, result = self.op("complete", "atomic_requirements")
        self.assertEqual(code, 1, result)
        code, result = self.ps("invalidate", "--from", "resolve_source", "--reason", "user restarted after the source changed")
        self.assertEqual(code, 0, result)
        state = self.state()
        self.assertEqual({o["status"] for o in state["operations"]}, {"pending"})
        self.assertEqual(state["status"], "in_progress")
        self.assertIn("atomic_requirements", state["invalidations"][-1]["operations"])

    def test_complete_also_guards_against_input_changes(self):
        self.ps("begin")
        self.ok("start", "resolve_source", "--sources", self.doc)
        self.ok("complete", "resolve_source", "--sources", self.doc)
        self.ok("start", "atomic_requirements")
        self.append_to_source()
        code, result = self.op("complete", "atomic_requirements")
        self.assertEqual((code, result["code"]), (1, "INPUTS_CHANGED"), result)

    def test_refresh_invalidates_after_an_individual_command_changed_an_artifact(self):
        code, result = self.ps("refresh")
        self.assertEqual((code, result["state_status"]), (0, "NO_STATE"), result)
        self.through_gate()
        code, result = self.ps("refresh")
        self.assertEqual((code, result["invalidated"]), (0, []), result)
        self.gaps("reopen", "--gap-id", "GAP-001")  # a standalone /triage-gaps reopened a Critical gap
        code, result = self.ps("refresh")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["invalidated"], ["gate_validation"])
        self.assertEqual(self.state()["last_completed_operation"], "gap_triage")

    def test_refresh_leaves_a_corrupt_checkpoint_alone(self):
        os.makedirs(os.path.dirname(self.checkpoint))
        with open(self.checkpoint, "w", encoding="utf-8") as handle:
            handle.write("nonsense")
        code, result = self.ps("refresh")
        self.assertEqual((code, result["state_status"]), (0, "CORRUPT"), result)
        self.assertEqual(read_text(self.checkpoint), "nonsense")


class GateTests(CheckpointCase):
    def run_to_triage(self):
        self.phase1()
        self.phase2a(four_levels=True)
        self.ok("start", "gap_triage")

    def test_unresolved_critical_or_high_blocks_the_gate_and_story_generation(self):
        self.run_to_triage()
        self.triage(["GAP-001"], skips=["GAP-002"])
        self.ok("complete", "gap_triage")  # "skip all remaining" ends the pass; it never passes the gate
        self.ok("start", "gate_validation")
        code, result = self.op("complete", "gate_validation")
        self.assertEqual(code, 1, result)
        self.assertEqual([b["gap_id"] for b in result["blockers"]], ["GAP-002"])
        state = self.state()
        self.assertEqual((state["status"], state["operations"][4]["status"]), ("blocked", "blocked"))
        code, result = self.op("start", "generate_stories")
        self.assertEqual(code, 1, result)
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))

    def test_the_gate_stays_blocked_across_a_resume_until_the_blocker_is_resolved(self):
        self.run_to_triage()
        self.triage(["GAP-001"], skips=["GAP-002"])
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.op("complete", "gate_validation")
        info, verdicts = self.verdicts()
        self.assertEqual(info["resume_from"], "gate_validation")
        self.assertEqual(verdicts["gap_triage"], "valid")
        code, resumed = self.ps("resume")
        self.assertEqual(code, 0, resumed)
        self.assertEqual(resumed["resume_from"], "gate_validation")
        self.assertEqual(self.state()["operations"][4]["status"], "blocked")  # blocked until its condition holds
        # Re-evaluating without resolving the blocker leaves it blocked.
        self.ok("start", "gate_validation")
        code, result = self.op("complete", "gate_validation")
        self.assertEqual(code, 1, result)
        # The blocker triage pass records its answers, then the gate passes. Medium and Low stay open.
        self.decide("GAP-002", "A reset link is valid for 24 hours.")
        code, result = self.ps("triage-event", "--gap-id", "GAP-002", "--action", "resolved")
        self.assertEqual(code, 0, result)
        self.ok("start", "gate_validation")
        result = self.ok("complete", "gate_validation")
        self.assertEqual(result["last_completed_operation"], "gate_validation")
        self.assertEqual(self.counts(), {"open": 2, "skipped": 0, "resolved": 2})
        self.ok("start", "generate_stories")

    def test_medium_and_low_gaps_do_not_block(self):
        self.run_to_triage()
        self.triage(["GAP-001", "GAP-002"], skips=["GAP-003"])  # Medium skipped, Low open
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.ok("complete", "gate_validation")
        self.ok("start", "generate_stories")
        self.generate_stories()
        self.ok("complete", "generate_stories")
        code, summary = self.ps("summary")
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["gaps"]["unresolved_by_priority"]["Critical"], {"open": 0, "skipped": 0})
        self.assertEqual(summary["gaps"]["unresolved_by_priority"]["Medium"], {"open": 0, "skipped": 1})
        self.assertEqual(summary["gaps"]["unresolved_by_priority"]["Low"], {"open": 1, "skipped": 0})

    def test_reopening_a_critical_gap_after_the_gate_passed_blocks_story_generation_on_resume(self):
        self.run_to_triage()
        self.triage(["GAP-001", "GAP-002"])
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.ok("complete", "gate_validation")
        self.gaps("reopen", "--gap-id", "GAP-001")
        info, verdicts = self.verdicts()
        self.assertEqual(verdicts["gate_validation"], "invalid")
        self.assertEqual(info["resume_from"], "gate_validation")
        # Even a command that ignores the resume validation cannot start story generation.
        code, result = self.op("start", "generate_stories")
        self.assertEqual(code, 1, result)
        self.assertEqual(result["blocked_operation"], "gate_validation")
        self.assertEqual([b["gap_id"] for b in result["gate"]["blockers"]], ["GAP-001"])
        state = self.state()
        self.assertEqual((state["status"], state["operations"][4]["status"], state["operations"][5]["status"]), ("blocked", "blocked", "pending"))
        self.assertFalse(os.path.exists(os.path.join(self.root, "stories")))

    def test_the_gate_cannot_be_verified_without_a_valid_register(self):
        self.phase1()
        code, gate = self.ps("gate")
        self.assertEqual(code, 0, gate)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["verifiable"])

    def test_an_empty_register_passes_the_gate(self):
        self.phase1()
        self.ok("start", "gap_analysis")
        self.save_gaps([])
        self.ok("complete", "gap_analysis")
        self.ok("start", "gap_triage")
        self.ok("complete", "gap_triage")
        self.ok("start", "gate_validation")
        self.ok("complete", "gate_validation")

    def test_a_gate_command_reports_blockers_critical_first(self):
        self.phase1()
        self.phase2a(four_levels=True)
        code, gate = self.ps("gate")
        self.assertEqual([b["gap_id"] for b in gate["blockers"]], ["GAP-001", "GAP-002"])


class PhaseThreeTests(CheckpointCase):
    def test_story_generation_that_wrote_nothing_does_not_complete(self):
        self.through_gate()
        self.ok("start", "generate_stories")
        code, result = self.op("complete", "generate_stories")
        self.assertEqual(code, 1, result)
        self.assertEqual(self.state()["operations"][5]["status"], "failed")

    def test_enrichment_is_not_complete_while_resolved_decisions_are_pending(self):
        self.through_stories()
        self.ok("start", "enrich_stories")
        code, result = self.op("complete", "enrich_stories")
        self.assertEqual(code, 1, result)
        self.assertTrue(any("not yet reflected" in p for p in result["details"]), result)
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.enrich(gap_id, "no_change_required")
        self.ok("start", "enrich_stories")
        self.ok("complete", "enrich_stories")

    def test_a_report_that_does_not_exist_does_not_complete(self):
        self.through_stories()
        self.ok("start", "enrich_stories")
        for gap_id in ("GAP-001", "GAP-002", "GAP-003"):
            self.enrich(gap_id, "no_change_required")
        self.ok("complete", "enrich_stories")
        self.ok("start", "phase3_report")
        os.remove(self.report)
        code, result = self.op("complete", "phase3_report")
        self.assertEqual(code, 1, result)
        code, summary = self.ps("summary")
        self.assertEqual(summary["report"]["status"], "UNAVAILABLE")

    def test_final_validation_marks_the_run_completed_and_the_summary_reports_the_run(self):
        self.through_report()
        code, interim = self.ps("summary")
        self.assertEqual(interim["report"]["status"], "GENERATED")
        self.ok("start", "final_validation")
        result = self.ok("complete", "final_validation")
        self.assertEqual((result["run_status"], result["last_completed_operation"]), ("completed", "final_validation"))
        code, summary = self.ps("summary")
        self.assertEqual(code, 0, summary)
        self.assertEqual(summary["run_status"], "completed")
        self.assertEqual(summary["stories"]["in_document"], 6)
        self.assertEqual(summary["report"]["path"], "report/phase3-report.html")
        self.assertEqual(summary["resumed_skipped_operations"], [])
        self.assertEqual(summary["operations_rerun"], [])

    def test_final_validation_rechecks_everything(self):
        self.through_report()
        self.ok("start", "final_validation")
        self.gaps("reopen", "--gap-id", "GAP-001")
        code, result = self.op("complete", "final_validation")
        self.assertEqual(code, 1, result)
        self.assertNotEqual(self.state()["status"], "completed")

    def test_summary_lists_skipped_and_rerun_operations_after_a_resume(self):
        self.phase1()
        self.phase2a()
        self.ok("start", "gap_triage")
        self.ps("resume")
        self.ok("start", "gap_triage")
        self.triage(["GAP-001", "GAP-002", "GAP-003"])
        self.ok("complete", "gap_triage")
        code, summary = self.ps("summary")
        self.assertEqual(summary["resumed_skipped_operations"], ["resolve_source", "atomic_requirements", "gap_analysis"])
        self.assertEqual(summary["operations_rerun"], ["gap_triage"])
        self.assertEqual(summary["resumes"], 1)
        self.assertEqual(summary["triage"]["resolved"], 3)


class CommandFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_md = read_text(os.path.join(COMMANDS, "ba-run.md"))

    def test_script_has_the_documented_subcommands(self):
        source = read_text(os.path.join(SCRIPTS, "pipeline-state.py"))
        for name in ("inspect", "begin", "resume", "start", "check-inputs", "complete", "fail", "block",
                     "triage-event", "invalidate", "refresh", "gate", "summary"):
            self.assertIn(f'"{name}"', source)

    def test_run_command_checks_the_checkpoint_before_asking_for_the_source(self):
        step0, step1 = self.run_md.index("## Step 0"), self.run_md.index("## Step 1")
        self.assertLess(step0, step1)
        section = self.run_md[step0:step1]
        for phrase in ("pipeline-state.py inspect --", "Resume", "Start a new run", "CORRUPT", "INCOMPATIBLE", "COMPLETED",
                       "never reused as a new execution", "pipeline-state.py resume --"):
            self.assertIn(phrase, section)

    def test_run_command_names_every_operation_and_the_checkpoint_calls(self):
        for name in OPS:
            self.assertIn(f"`{name}`", self.run_md)
        for call in ("pipeline-state.py start --operation", "pipeline-state.py check-inputs --operation",
                     "pipeline-state.py complete --operation", "pipeline-state.py fail --operation",
                     "triage-event --gap-id", "pipeline-state.py begin --", "pipeline-state.py invalidate --from"):
            self.assertIn(call, self.run_md)

    def test_run_command_keeps_the_gate_rules_under_resume(self):
        self.assertIn("after a resume the gate is evaluated again", self.run_md)
        self.assertIn("refuses (exit 1, `blocked_operation` `gate_validation`)", self.run_md)
        step6 = self.run_md[self.run_md.index("## Step 6"):self.run_md.index("## Step 7")]
        self.assertLess(step6.index("pipeline-state.py start --operation generate_stories"), step6.index("Follow `generate-stories.md`"))

    def test_run_command_asks_before_restarting_on_a_changed_source(self):
        self.assertIn("restart from source analysis", self.run_md)
        self.assertIn("INPUTS_CHANGED", self.run_md)

    def test_every_phase_command_refreshes_the_checkpoint_without_depending_on_the_master(self):
        for name in PHASE_COMMANDS:
            text = read_text(os.path.join(COMMANDS, "ba-" + name + ".md"))
            self.assertIn("pipeline-state.py refresh --project-root", text, name)
            self.assertIn("## Pipeline checkpoint", text, name)
            self.assertNotIn("sdlc-pipeline:ba-run", text, name)
            meta = text.split("---")[1]
            self.assertIn("Bash(python:*)", meta, name)


if __name__ == "__main__":
    unittest.main()
