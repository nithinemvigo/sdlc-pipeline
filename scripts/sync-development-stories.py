#!/usr/bin/env python3
"""Safe section handling and persistence for development stories (ba-requirements plugin, Phase 3).

Every write to the requirements document, the detailed stories file, the story state and the
Phase 3 report goes through this script, so the commands never hand-edit them: boundary
detection, hashing, manual-edit and concurrency detection, backup, temp-file write with atomic
replace, read-back verification and state update (only after verification). Standard library only.

Every story exists twice under one stable Story ID:
  * an ultra-lean story (Story ID, concise summary, one functional criteria statement) in the managed
    '# Development Stories' section of the requirements document, and
  * a detailed story (functional and non-functional detail) in the single file
    stories/detailed_stories.md, which is also the source of the HTML report.

Usage (all commands take --project-root, default: the current directory):

  inspect  [--target DOC] [--ignore-gaps]
      Read-only. Input validity, target document and section status, stories found, manual
      changes since the last sync (document and detailed file), atomic-requirement and
      gap-register changes, resolved decisions not yet reflected in stories, and requirements
      not covered by a story.
      Status: INPUT_MISSING | INPUT_INVALID | INPUT_EMPTY | TARGET_REQUIRED | TARGET_NOT_MARKDOWN |
      DOCUMENT_MISSING | DOCUMENT_UNREADABLE | SECTION_AMBIGUOUS | OK.

  export   [--target DOC] [--ignore-gaps] [--draft-out FILE]
      Read-only. The stories now in the project as a draft (the detailed stories from
      stories/detailed_stories.md with the lean criteria from the document), plus their
      traceability context.

  apply    --draft FILE [--target DOC] [--ignore-gaps] [--expected-source-sha256 H]
           [--overwrite US-001,..] [--allow-remove US-001,..] [--restore US-001,..]
           [--acknowledge-changes] [--change-target] [--dry-run]
      Validate a structured draft (schemas/development-stories.schema.json) and write each story
      twice under its stable ID: the detailed story into stories/detailed_stories.md and the
      ultra-lean story into the managed '# Development Stories' section. New stories (story_id
      null) get the next unused ID.

  accept   [--target DOC] [--expected-source-sha256 H] [--mappings FILE]
           [--rename OLD=NEW,..] [--retire US-001,..]
      Reconcile manual edits to the lean section or to the detailed stories file into the story
      state without touching the document. Detailed stories of renamed or retired stories follow
      their ID in the detailed file.

  summary  [--target DOC] [--ignore-gaps]
      Read-only. Real counts for execution summaries: stories, requirement coverage, gaps
      referenced by status, validation result, synchronisation status.

  regenerate-report
      Rebuild report/phase3-report.html only. Nothing else changes.

Results are printed as JSON. Exit status: 0 = success, 1 = refused or invalid (nothing changed),
2 = a file could not be read or written (nothing changed), 3 = saved but the HTML report could not
be generated (run regenerate-report), 4 = the stories were saved and verified but the state could
not be saved (run inspect, then accept).
"""

import argparse
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime


def _load(filename, name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load("story_common.py", "ba_story_common")
validator = _load("validate-development-stories.py", "ba_validate_stories")
reporter = _load("generate-phase3-report.py", "ba_phase3_report")

Refused = common.Refused
IOFailure = common.IOFailure


# -------------------------------------------------------------------------- context


class Context:
    pass


def load_context(paths, target_arg=None, ignore_gaps=False):
    ctx = Context()
    ctx.paths = paths
    ctx.atomic_status, ctx.atomic_errors, ctx.requirements, ctx.atomic_raw = common.load_atomic(paths)
    ctx.gaps = common.load_gaps(paths, ctx.requirements, ignore=ignore_gaps)
    ctx.register = ctx.gaps["register"] if ctx.gaps["status"] == "OK" else None
    ctx.state, ctx.state_status, ctx.state_errors = common.load_state(paths)
    ctx.detailed = common.scan_detailed(paths)
    ctx.legacy_files = common.scan_legacy_files(paths)
    ctx.target, ctx.target_origin, ctx.target_changed = None, None, False
    state_target = common.resolve_target(paths, ctx.state["target_document"]) if ctx.state else None
    if target_arg:
        ctx.target, ctx.target_origin = common.resolve_target(paths, target_arg), "argument"
        ctx.target_changed = bool(state_target) and os.path.normcase(state_target) != os.path.normcase(ctx.target)
    elif state_target:
        ctx.target, ctx.target_origin = state_target, "state"
    ctx.state_target_exists = bool(state_target) and os.path.isfile(state_target)
    ctx.doc, ctx.doc_status, ctx.doc_error = None, "TARGET_REQUIRED", None
    if ctx.target:
        if not ctx.target.lower().endswith(".md"):
            ctx.doc_status = "TARGET_NOT_MARKDOWN"
        elif not os.path.isfile(ctx.target):
            ctx.doc_status = "DOCUMENT_MISSING"
        else:
            try:
                ctx.doc = common.read_document(ctx.target)
                ctx.doc_status = "SECTION_AMBIGUOUS" if ctx.doc.ambiguity else "OK"
            except (Refused, IOFailure) as exc:
                ctx.doc_status, ctx.doc_error = "DOCUMENT_UNREADABLE", str(exc)
    return ctx


def require_ready(ctx):
    """Refuse unless the inputs and the target document are usable."""
    if ctx.atomic_status:
        raise Refused(
            "The atomic requirements are not usable (" + ctx.atomic_status + "). Phase 1 must be completed successfully first.",
            ctx.atomic_errors, {"status": ctx.atomic_status},
        )
    messages = {
        "TARGET_REQUIRED": "No target document is known yet. Ask the user which Markdown requirements document should hold the Development Stories, then pass --target.",
        "TARGET_NOT_MARKDOWN": "The target must be a Markdown (.md) document.",
        "DOCUMENT_MISSING": "The target document was not found. Ask the user to locate the original requirements document and pass --target; a replacement is never created silently.",
        "DOCUMENT_UNREADABLE": "The target document cannot be read: " + str(ctx.doc_error),
        "SECTION_AMBIGUOUS": "The Development Stories section boundary is ambiguous; the file was not modified. " + str(ctx.doc.ambiguity if ctx.doc else ""),
    }
    if ctx.doc_status != "OK":
        raise Refused(messages[ctx.doc_status], [], {"status": ctx.doc_status, "target": ctx.target})
    if ctx.gaps["status"] == "INVALID":
        raise Refused(
            "The gap register is invalid. Ask the user to correct it, or to explicitly proceed without gap context (--ignore-gaps).",
            ctx.gaps["errors"], {"status": "GAPS_INVALID"},
        )


def require_detailed_ok(ctx):
    if ctx.detailed.problems:
        raise Refused(
            f"{common.DETAILED_RELATIVE} has structural problems (probably manual edits). "
            "Fix them, or reconcile with /sdlc-pipeline:ba-sync-stories first.",
            ctx.detailed.problems, {"status": "DETAILED_PROBLEMS"},
        )


def ids_from(text, pattern, label):
    ids = [part.strip().upper() for part in (text or "").split(",") if part.strip()]
    for item in ids:
        if not pattern.match(item):
            raise Refused(f"{item!r} is not a valid {label}.")
    return ids


# ------------------------------------------------------------------------- analysis


def state_story_map(ctx):
    return {entry["story_id"]: entry for entry in (ctx.state or {}).get("stories", [])}


def compare_with_baseline(doc, state):
    base = {e["story_id"]: e for e in state["stories"]}
    cur = {s["story_id"]: s for s in doc.stories}
    edited, details = [], {}
    for story_id in sorted(set(cur) & set(base), key=common.story_number):
        story = cur[story_id]
        if common.lean_hash(story) == base[story_id]["story_content_hash"]:
            continue
        edited.append(story_id)
        known = base[story_id].get("field_hashes")
        detail = {}
        if known:
            now = common.lean_field_hashes(story)
            detail["summary_changed"] = known.get("summary") != now["summary"]
            old_set, new_set = set(known.get("acceptance_criteria", [])), set(now["acceptance_criteria"])
            detail["criteria_added"] = [text for text, h in zip(story["acceptance_criteria"], now["acceptance_criteria"]) if h not in old_set]
            detail["criteria_removed_count"] = len(old_set - new_set)
        details[story_id] = detail
    added = sorted(set(cur) - set(base), key=common.story_number)
    removed = sorted(set(base) - set(cur), key=common.story_number)
    id_changes = []
    for old in removed:
        for new in added:
            if base[old]["story_content_hash"] == common.lean_hash(cur[new]):
                id_changes.append({"from": old, "to": new})
    return {"edited": edited, "edited_details": details, "added": added, "removed": removed, "id_changes": id_changes}


def detailed_changes(ctx):
    """Where the detailed stories file differs from the lean section and from the last synchronised state."""
    scan = ctx.detailed
    stories = ctx.doc.stories if ctx.doc else []
    status = common.pair_status(stories, scan.stories, ctx.state)
    deleted = []
    file_modified = None
    if ctx.state:
        deleted = sorted(
            (e["story_id"] for e in ctx.state["stories"] if e.get("detailed_content_hash") and e["story_id"] not in scan.stories),
            key=common.story_number,
        )
        known = ctx.state.get("detailed_document_hash")
        file_modified = bool(known) and scan.exists and scan.file_hash != known
    return {
        "file": common.DETAILED_RELATIVE,
        "file_exists": scan.exists,
        "story_count": len(scan.stories),
        "problems": scan.problems,
        "missing": status["detailed_missing"],
        "deleted_by_hand": deleted,
        "without_lean_story": status["detailed_extra"],
        "edited": status["detailed_edited"],
        "not_tracked": status["detailed_untracked"],
        "lean_edited": status["lean_edited"],
        "lean_needs_update": status["lean_stale"],
        "file_modified": file_modified,
        "legacy_files": ctx.legacy_files,
    }


def requirement_changes(ctx):
    snapshot = (ctx.state or {}).get("requirement_snapshot")
    if snapshot is None or ctx.requirements is None:
        return None
    added = sorted((r for r in ctx.requirements if r not in snapshot), key=common.requirement_number)
    removed = sorted((r for r in snapshot if r not in ctx.requirements), key=common.requirement_number)
    changed = sorted(
        (r for r in ctx.requirements if r in snapshot and snapshot[r].get("sha256") != common.requirement_fingerprint(ctx.requirements[r])),
        key=common.requirement_number,
    )
    touched = set(changed) | set(removed)
    affected = [e["story_id"] for e in ctx.state["stories"] if touched & set(e.get("source_requirement_ids", []))]
    return {"added": added, "changed": changed, "removed": removed, "affected_story_ids": affected}


def gap_events(ctx):
    if ctx.register is None:
        return None
    snapshot = (ctx.state or {}).get("gap_snapshot")
    if not ctx.state or snapshot is None:
        return {"tracked": False, "reopened": []}
    events = {"tracked": True, "reopened": [], "newly_skipped": [], "newly_resolved": [], "new_gaps": [], "removed_gaps": []}
    current = {g["gap_id"]: g for g in ctx.register}
    for gap_id in sorted(current, key=lambda g: int(common.GAP_ID_RE.match(g).group(1))):
        old = snapshot.get(gap_id)
        now = current[gap_id]["status"]
        if old is None:
            events["new_gaps"].append(gap_id)
            continue
        before = old.get("status")
        if before == "resolved" and now != "resolved":
            events["reopened"].append(gap_id)
        elif before != "skipped" and now == "skipped":
            events["newly_skipped"].append(gap_id)
        elif before != "resolved" and now == "resolved":
            events["newly_resolved"].append(gap_id)
    events["removed_gaps"] = sorted(g for g in snapshot if g not in current)
    return events


def pending_decisions(ctx):
    """Resolved gaps whose latest decision has not been reviewed for the stories (new or revised)."""
    if ctx.register is None:
        return []
    ledger = (ctx.state or {}).get("decision_ledger", {})
    out = []
    for gap in ctx.register:
        if gap["status"] != "resolved":
            continue
        version = common.decision_version(gap)
        if version is None:
            continue
        entry = ledger.get(gap["gap_id"])
        if entry and entry.get("recorded_at") == version["recorded_at"] and entry.get("decision_sha256") == version["decision_sha256"]:
            continue
        req_ids = [ref["requirement_id"] for ref in gap["affected_requirements"]]
        candidates = [e["story_id"] for e in (ctx.state or {}).get("stories", []) if set(e.get("source_requirement_ids", [])) & set(req_ids)]
        out.append({
            "gap_id": gap["gap_id"],
            "kind": "revised" if entry else "new",
            "gap_definition": gap["gap_definition"],
            "decision": gap["decisions_recorded"][-1]["decision"],
            "recorded_at": version["recorded_at"],
            "affected_requirement_ids": req_ids,
            "candidate_story_ids": candidates,
        })
    return sorted(out, key=lambda item: int(common.GAP_ID_RE.match(item["gap_id"]).group(1)))


def uncovered_requirements(ctx):
    if ctx.requirements is None:
        return []
    covered = set()
    for entry in (ctx.state or {}).get("stories", []):
        covered |= set(entry.get("source_requirement_ids", []))
    listed = {e["requirement_id"] for e in (ctx.state or {}).get("not_covered_requirements", [])}
    return [r for r in sorted(ctx.requirements, key=common.requirement_number) if r not in covered and r not in listed]


def inspect_project(ctx):
    paths = ctx.paths
    report = {
        "project_root": paths.root,
        "paths": {
            "requirements": paths.requirements, "gaps": paths.register, "state": paths.state,
            "detailed_stories": paths.detailed_file, "report": paths.report,
        },
    }
    if ctx.atomic_status:
        report.update(status=ctx.atomic_status, errors=ctx.atomic_errors)
        return report
    report["atomic_requirements"] = {"count": len(ctx.requirements), "sha256": common.sha256_bytes(ctx.atomic_raw)}
    report["gaps"] = {
        "status": ctx.gaps["status"],
        "errors": ctx.gaps["errors"],
        "warnings": ctx.gaps["warnings"],
        "counts": None if ctx.register is None else {
            s: sum(1 for g in ctx.register if g["status"] == s) for s in ("open", "skipped", "resolved")
        },
    }
    report["state"] = {"status": ctx.state_status, "errors": ctx.state_errors}
    report["target"] = {"path": ctx.target, "origin": ctx.target_origin, "differs_from_state": ctx.target_changed}
    report["status"] = ctx.doc_status
    if ctx.doc_status == "SECTION_AMBIGUOUS":
        report["ambiguity"] = ctx.doc.ambiguity
    if ctx.doc_status == "DOCUMENT_UNREADABLE":
        report["errors"] = [ctx.doc_error]
    if ctx.doc_status != "OK":
        report["uncovered_requirements"] = uncovered_requirements(ctx)
        return report
    doc = ctx.doc
    report["target"].update(source_sha256=doc.sha256, line_ending="CRLF" if doc.eol == "\r\n" else "LF")
    report["section"] = {
        "state": doc.section_state,
        "story_count": len(doc.stories),
        "story_ids": [s["story_id"] for s in doc.stories],
        "problems": doc.problems,
        "legacy_layout_story_ids": doc.legacy_ids,
    }
    report["detailed"] = detailed_changes(ctx)
    if ctx.state:
        report["manual_changes"] = {
            "section_modified": doc.section_state == "present" and doc.section_hash != ctx.state["managed_section_hash"],
            "outside_section_modified": bool(ctx.state.get("outside_section_hash")) and doc.outside_hash != ctx.state["outside_section_hash"],
            **compare_with_baseline(doc, ctx.state),
        }
        report["manual_changes"]["formatting_only"] = (
            report["manual_changes"]["section_modified"]
            and not (report["manual_changes"]["edited"] or report["manual_changes"]["added"] or report["manual_changes"]["removed"])
        )
        report["requirement_changes"] = requirement_changes(ctx)
        report["gap_changes"] = gap_events(ctx)
    else:
        report["manual_changes"] = None
        report["recoverable_from_document"] = doc.section_state == "present" and not doc.problems and not ctx.detailed.problems and not doc.legacy_ids
    report["pending_decisions"] = pending_decisions(ctx)
    report["uncovered_requirements"] = uncovered_requirements(ctx)
    return report


# ----------------------------------------------------------------------------- export


def story_context(ctx, story, baseline, pair):
    story_id = story["story_id"]
    entry = baseline.get(story_id)
    sources = list(entry.get("source_requirement_ids", [])) if entry else []
    lean_edited = entry is None or entry["story_content_hash"] != common.lean_hash(story)
    detailed_edited = story_id in pair["detailed_edited"]
    return {
        "story_id": story_id,
        "source_requirement_ids": sources,
        "related_gap_ids": common.derive_related_gaps(ctx.register, sources) if ctx.register is not None else list(entry.get("related_gap_ids", [])) if entry else [],
        "applied_decisions": list(entry.get("applied_decisions", [])) if entry else [],
        "detailed_missing": story_id in pair["detailed_missing"],
        "legacy_layout": bool(story.get("legacy")),
        "lean_edited": lean_edited,
        "detailed_edited": detailed_edited,
        "lean_needs_update": story_id in pair["lean_stale"],
        "edited_since_last_sync": lean_edited or detailed_edited,
    }


def cmd_export(paths, args):
    ctx = load_context(paths, args.target, args.ignore_gaps)
    require_ready(ctx)
    if ctx.doc.problems:
        raise Refused("The managed section has structural problems; reconcile them with /sdlc-pipeline:ba-sync-stories first.", ctx.doc.problems)
    require_detailed_ok(ctx)
    baseline = state_story_map(ctx)
    pair = common.pair_status(ctx.doc.stories, ctx.detailed.stories, ctx.state)
    contexts = [story_context(ctx, s, baseline, pair) for s in ctx.doc.stories]
    detailed = ctx.detailed.stories

    def export_story(s, c):
        full = detailed.get(s["story_id"])
        if full is None:
            # No detailed story yet (a story added by hand, or a project from an earlier version): the agent writes it.
            item = {"story_id": s["story_id"], "summary": s["summary"], "lean_acceptance_criteria": list(s["acceptance_criteria"]), "detailed": None}
        else:
            # The summary is shared by both versions. A summary edited by hand in the document (and not in the
            # detailed file) is kept and carried into the detailed story; otherwise the detailed one is authoritative.
            keep_lean_summary = c["lean_edited"] and not c["detailed_edited"]
            item = common.draft_item({**s, "summary": s["summary"] if keep_lean_summary else full["summary"]}, full)
        item["source_requirement_ids"] = c["source_requirement_ids"]
        item["applied_decisions"] = c["applied_decisions"]
        return item

    draft = {
        "stories": [export_story(s, c) for s, c in zip(ctx.doc.stories, contexts)],
        "not_covered_requirements": list((ctx.state or {}).get("not_covered_requirements", [])),
        "decisions_reviewed": [],
    }
    if args.draft_out:
        try:
            common.atomic_write_bytes(args.draft_out, common.to_json_bytes(draft), prefix=".draft-")
        except OSError as exc:
            raise IOFailure(f"cannot write {args.draft_out}: {exc}")
    return {
        "target": ctx.target,
        "source_sha256": ctx.doc.sha256,
        "section_state": ctx.doc.section_state,
        "story_count": len(contexts),
        "detailed_without_lean_story": pair["detailed_extra"],
        "draft": draft,
        "story_context": contexts,
        "draft_written_to": args.draft_out,
    }, 0


# ----------------------------------------------------------------------------- state


def build_state(ctx, doc, entries, not_covered, ledger, retired, highest, preserve_gaps, detailed_file_hash):
    paths = ctx.paths
    previous = ctx.state or {}
    state = {
        "schema_version": common.STATE_SCHEMA_VERSION,
        "target_document": common.target_for_state(paths, ctx.target),
        "detailed_document": common.DETAILED_RELATIVE,
        "detailed_document_hash": detailed_file_hash,
        "last_successful_sync": common.now_stamp(),
        "source_document_hash": doc.sha256,
        "outside_section_hash": doc.outside_hash,
        "managed_section_hash": doc.section_hash,
        "atomic_requirements_hash": common.sha256_bytes(ctx.atomic_raw),
        "gap_register_hash": previous.get("gap_register_hash") if preserve_gaps else ctx.gaps["sha256"],
        "highest_story_number": highest,
        "retired_story_ids": sorted(retired, key=common.story_number),
        "stories": entries,
        "not_covered_requirements": not_covered,
        "requirement_snapshot": {
            r: {"title": item["title"], "sha256": common.requirement_fingerprint(item)} for r, item in sorted(ctx.requirements.items())
        },
        "gap_snapshot": previous.get("gap_snapshot", {}) if preserve_gaps else {
            g["gap_id"]: {"status": g["status"], "decision_count": len(g["decisions_recorded"])} for g in ctx.register
        },
        "decision_ledger": ledger,
    }
    return state


def story_entry(story_id, lean, detailed, sources, related, applied, derived_from=None):
    """The state entry of a story: its mappings, the hash of the lean story, the hash of the detailed
    story, and which detailed version the lean story was last derived from."""
    entry = {
        "story_id": story_id,
        "source_requirement_ids": sorted(sources, key=common.requirement_number),
        "related_gap_ids": related,
        "applied_decisions": sorted(applied, key=lambda g: int(common.GAP_ID_RE.match(g).group(1))),
        "story_content_hash": common.lean_hash(lean),
        "field_hashes": common.lean_field_hashes(lean),
    }
    if detailed is not None:
        entry.update(
            detailed_content_hash=common.detailed_hash(detailed),
            lean_derived_from=derived_from if derived_from is not None else common.detailed_hash(detailed),
        )
    return entry


def same_state(old, new):
    if not old:
        return False
    strip = lambda s: {k: v for k, v in s.items() if k != "last_successful_sync"}
    return strip(old) == strip(new)


def save_state(paths, state):
    payload = common.to_json_bytes(state)
    try:
        common.atomic_write_bytes(paths.state, payload, prefix=".story-state-")
        if common.read_bytes(paths.state) != payload:
            raise IOFailure("the saved story state does not match what was written")
    except OSError as exc:
        raise IOFailure(f"cannot save {paths.state}: {exc}")


def make_backup(paths, target, raw):
    """Keep a copy of a file (the requirements document or the detailed stories) before it is changed."""
    os.makedirs(paths.backups, exist_ok=True)
    base = os.path.basename(target)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, counter = os.path.join(paths.backups, f"{base}.{stamp}.bak"), 1
    while os.path.exists(candidate):
        candidate = os.path.join(paths.backups, f"{base}.{stamp}-{counter}.bak")
        counter += 1
    try:
        with open(candidate, "xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise IOFailure(f"cannot create the backup {candidate}: {exc}. Nothing was modified.")
    return candidate


def restore_detailed_file(paths, original):
    """Put the detailed stories file back as it was (best effort; used only when a later step fails)."""
    try:
        if original is None:
            if os.path.exists(paths.detailed_file):
                os.remove(paths.detailed_file)
        else:
            common.atomic_write_bytes(paths.detailed_file, original, prefix=".story-detailed-")
    except OSError:
        pass


def write_detailed_file(paths, payload, expected, original):
    """Write stories/detailed_stories.md atomically, read it back and check every story. All or nothing.

    expected: {story_id: detailed story} that must read back unchanged."""
    try:
        common.atomic_write_bytes(paths.detailed_file, payload, prefix=".story-detailed-")
        if common.read_bytes(paths.detailed_file) != payload:
            raise IOFailure("the saved detailed stories do not match what was written")
        scanned = common.scan_detailed(paths)
        if scanned.problems:
            raise IOFailure("the saved detailed stories do not read back as written: " + "; ".join(scanned.problems[:3]))
        got = {story_id: common.detailed_hash(story) for story_id, story in scanned.stories.items()}
        want = {story_id: common.detailed_hash(story) for story_id, story in expected.items()}
        if got != want:
            raise IOFailure("the detailed stories read back do not match the stories that were written")
    except (OSError, IOFailure) as exc:
        restore_detailed_file(paths, original)
        raise IOFailure(f"cannot write {common.DETAILED_RELATIVE}: {exc}. The detailed stories and the document are unchanged.")


def detailed_payload(blocks):
    return common.render_detailed_document(blocks).encode("utf-8")


def overall_status(entry):
    """One status per story across both representations."""
    lean, detailed = entry["status"], entry["dstatus"]
    if "overwritten" in (lean, detailed):
        return "overwritten"
    if lean in ("created", "restored"):
        return lean
    if lean == "updated" or detailed in ("updated", "created", "restored"):
        return "updated"
    return "unchanged"


def finish(paths, result, state_ok=True):
    """Regenerate the report and set the exit code."""
    if not state_ok:
        result["report"] = {"generated": False, "message": "Skipped: the report is generated only after the document and state are verified."}
        return 4
    code, message = reporter.generate(paths)
    result["report"] = {"generated": code == 0, "path": "report/phase3-report.html", "message": message}
    if code != 0:
        result["warning"] = "The stories and state were saved, but the HTML report is stale. Run regenerate-report."
    return 0 if code == 0 else 3


# ----------------------------------------------------------------------------- apply


def read_draft(path):
    try:
        text = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8-sig").read()
    except (OSError, UnicodeDecodeError) as exc:
        raise IOFailure(f"cannot read the draft: {exc}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise Refused(f"The draft is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg}).")


def check_acknowledged(ctx, args):
    needed = {}
    changes = requirement_changes(ctx)
    if changes and (changes["added"] or changes["changed"] or changes["removed"]):
        needed["requirement_changes"] = changes
    events = gap_events(ctx)
    if events and events.get("reopened"):
        needed["reopened_gaps"] = events["reopened"]
    if needed and not args.acknowledge_changes:
        raise Refused(
            "The atomic requirements or the gap register changed since the last sync. Show these changes to the user, "
            "make sure the draft handles them, then re-run with --acknowledge-changes. A reopened gap never deletes "
            "incorporated criteria on its own: ask whether to retain, revise or remove them.",
            [], {"unacknowledged_changes": needed},
        )


def cmd_apply(paths, args):
    ctx = load_context(paths, args.target, args.ignore_gaps)
    require_ready(ctx)
    doc = ctx.doc
    state = ctx.state
    if ctx.target_changed and ctx.state_target_exists and not args.change_target:
        raise Refused(
            "The stories are tracked in a different document that still exists. Use that document, or pass --change-target "
            "after the user confirms the stories should live in the new target.",
            [], {"state_target": state["target_document"], "requested_target": ctx.target},
        )
    if args.expected_source_sha256 and doc.sha256 != args.expected_source_sha256:
        raise Refused("The document changed after it was inspected (concurrent edit). Nothing was written. Re-run inspect and retry.")
    if doc.problems:
        raise Refused("The managed section has structural problems (probably manual edits). Reconcile with /sdlc-pipeline:ba-sync-stories first.", doc.problems)
    require_detailed_ok(ctx)
    check_acknowledged(ctx, args)

    draft = read_draft(args.draft)
    preserve = ctx.register is None
    prior = state_story_map(ctx)
    check_copy = copy.deepcopy(draft)
    if preserve and isinstance(check_copy, dict) and check_copy.get("decisions_reviewed"):
        raise Refused("Decisions cannot be reviewed without gap context (the gap register is unavailable or ignored).")
    # A decision that was incorporated earlier stays on record after its gap is reopened or removed; only
    # newly claimed decisions must belong to a resolved gap. Retained references are kept out of validation.
    historical = {}
    gap_status = {g["gap_id"]: g["status"] for g in ctx.register or []}
    if isinstance(check_copy, dict) and isinstance(check_copy.get("stories"), list):
        for item in check_copy["stories"]:
            if not isinstance(item, dict) or not isinstance(item.get("applied_decisions"), list):
                continue
            story_id = item.get("story_id")
            old_applied = prior.get(story_id, {}).get("applied_decisions", []) if isinstance(story_id, str) else []
            keep = [g for g in item["applied_decisions"] if g in old_applied and (preserve or gap_status.get(g) != "resolved")]
            historical[story_id] = keep
            item["applied_decisions"] = [g for g in item["applied_decisions"] if g not in keep]
    errors, warnings = validator.validate_draft(check_copy, ctx.requirements, ctx.register)
    if errors:
        raise Refused("The draft stories are invalid; nothing was saved.", errors, {"warnings": warnings})

    baseline = prior
    retired = set((state or {}).get("retired_story_ids", []))
    doc_by_id = {s["story_id"]: s for s in doc.stories}
    overwrite = ids_from(args.overwrite, common.STORY_ID_RE, "story ID")
    allow_remove = ids_from(args.allow_remove, common.STORY_ID_RE, "story ID")
    restore = ids_from(args.restore, common.STORY_ID_RE, "story ID")
    for story_id in overwrite + allow_remove:
        if story_id not in doc_by_id:
            raise Refused(f"{story_id} is not in the document, so it cannot be overwritten or removed.")
    detailed_now = ctx.detailed.stories
    for story_id in restore:
        lean_deleted = story_id not in doc_by_id and story_id in baseline
        detailed_deleted = story_id in doc_by_id and baseline.get(story_id, {}).get("detailed_content_hash") and story_id not in detailed_now
        if not (lean_deleted or detailed_deleted):
            raise Refused(f"{story_id} cannot be restored: neither its story in the document nor its detailed story was deleted by hand.")

    # New stories get the next unused IDs in draft order. They are known before the plan is made so that a
    # dependency written as [[Summary of another story]] can already name that story by its ID.
    numbers = [common.story_number(s) for s in list(doc_by_id) + list(baseline) + list(retired) + list(detailed_now)]
    highest = max([int((state or {}).get("highest_story_number", 0))] + numbers)
    new_ids = {}
    for index, item in enumerate(draft["stories"]):
        if item.get("story_id") is None:
            highest += 1
            new_ids[index] = common.format_story_id(highest)
    ids_by_summary = {
        common.story_reference_key(item["summary"]): (item.get("story_id") or new_ids[index], common.collapse(item["summary"]))
        for index, item in enumerate(draft["stories"])
    }

    plan, conflicts = [], []
    pair = common.pair_status(doc.stories, detailed_now, state)
    for index, item in enumerate(draft["stories"]):
        story_id = item.get("story_id")
        lean, full = common.lean_view(item), common.detailed_view(item)
        full["dependencies"] = common.resolve_story_references(full["dependencies"], ids_by_summary)
        entry = {"draft": item, "lean": lean, "full": full, "index": index, "story_id": story_id, "status": "created", "dstatus": "created", "raw": None, "draw": None}
        if story_id is not None:
            if story_id in retired:
                raise Refused(f"{story_id} belongs to a deleted, retired or superseded story. IDs are never reused; use story_id null for a new story.")
            current = doc_by_id.get(story_id)
            if current is None:
                if story_id not in baseline:
                    raise Refused(f"{story_id} is unknown. Only IDs already in the document may be reused; use story_id null for a new story.")
                if story_id in restore:
                    entry["status"] = "restored"
                else:
                    conflicts.append({"story_id": story_id, "reason": "deleted_by_hand", "representation": "lean", "message": "The story was deleted from the document by hand; restoring it needs --restore."})
            elif common.lean_hash(lean) == common.lean_hash(current):
                entry.update(status="unchanged", raw=current["raw"])
            else:
                known = baseline.get(story_id, {}).get("story_content_hash")
                if known is not None and known == common.lean_hash(current):
                    entry["status"] = "updated"
                elif story_id in overwrite:
                    entry["status"] = "overwritten"
                else:
                    conflicts.append({
                        "story_id": story_id,
                        "reason": "manual_edit" if known else "no_baseline",
                        "representation": "lean",
                        "message": "The story in the document differs from the last known version (edited by hand)." if known else "No synchronised baseline exists for this story, so existing content is not overwritten silently.",
                        "current": common.canonical_lean(current),
                        "proposed": common.canonical_lean(lean),
                    })
            file_story = detailed_now.get(story_id)
            known_d = baseline.get(story_id, {}).get("detailed_content_hash")
            if file_story is None:
                if known_d is not None and story_id in restore:
                    entry["dstatus"] = "restored"
                elif known_d is not None and current is not None:
                    conflicts.append({
                        "story_id": story_id, "reason": "detailed_deleted_by_hand", "representation": "detailed",
                        "message": f"The detailed story was deleted from {common.DETAILED_RELATIVE} by hand; restoring it needs --restore.",
                    })
            elif common.detailed_hash(full) == common.detailed_hash(file_story):
                entry.update(dstatus="unchanged", draw=ctx.detailed.raw_blocks[story_id])
            elif known_d is not None and known_d == common.detailed_hash(file_story):
                entry["dstatus"] = "updated"
            elif story_id in overwrite:
                entry["dstatus"] = "overwritten"
            else:
                conflicts.append({
                    "story_id": story_id,
                    "reason": "detailed_manual_edit" if known_d else "detailed_no_baseline",
                    "representation": "detailed",
                    "message": "The detailed story differs from the last known version (edited by hand)." if known_d else "No synchronised baseline exists for this detailed story, so the existing story is not overwritten silently.",
                    "current": common.canonical_detailed(file_story),
                    "proposed": common.canonical_detailed(full),
                })
        plan.append(entry)
    draft_ids = {e["story_id"] for e in plan if e["story_id"]}
    removed = []
    for story_id, current in doc_by_id.items():
        if story_id not in draft_ids:
            if story_id in allow_remove:
                removed.append(story_id)
            else:
                conflicts.append({"story_id": story_id, "reason": "would_be_removed", "message": "The story is in the document but not in the draft; removing it needs --allow-remove.", "current": common.canonical_lean(current)})
    if conflicts:
        raise Refused(
            "The draft would overwrite or remove content that was changed or should not be dropped silently. Show the conflicts to the user and ask how to proceed.",
            [f"{c['story_id']}: {c['reason']}" for c in conflicts], {"conflicts": conflicts},
        )
    manually_deleted = sorted((s for s in baseline if s not in doc_by_id and s not in draft_ids), key=common.story_number)

    for entry in plan:
        if entry["story_id"] is None:
            entry["story_id"] = new_ids[entry["index"]]
    plan.sort(key=lambda e: common.story_number(e["story_id"]))

    # Traceability and decision bookkeeping.
    ledger = copy.deepcopy((state or {}).get("decision_ledger", {}))
    gaps_by_id = {g["gap_id"]: g for g in ctx.register or []}
    entries = []
    for e in plan:
        item = e["draft"]
        sources = item["source_requirement_ids"]
        if preserve:
            old = prior.get(e["story_id"], {})
            related, applied = list(old.get("related_gap_ids", [])), list(old.get("applied_decisions", []))
        else:
            related = common.derive_related_gaps(ctx.register, sources)
            applied = sorted(set(item.get("applied_decisions", [])) | set(historical.get(e["draft"].get("story_id"), [])))
        lean_story = {**e["lean"], "story_id": e["story_id"]}
        full_story = {**e["full"], "story_id": e["story_id"]}
        # A pair that was already out of step and that this run did not touch stays flagged until its lean story is updated.
        untouched_stale = (
            e["story_id"] in pair["lean_stale"] and e["status"] == "unchanged" and e["dstatus"] == "unchanged" and not item.get("lean_reviewed")
        )
        derived = prior.get(e["story_id"], {}).get("lean_derived_from") if untouched_stale else None
        entries.append(story_entry(e["story_id"], lean_story, full_story, sources, related, applied, derived))
    for review in draft.get("decisions_reviewed", []):
        version = common.decision_version(gaps_by_id[review["gap_id"]])
        old = ledger.get(review["gap_id"])
        if old and old.get("recorded_at") == version["recorded_at"] and old.get("decision_sha256") == version["decision_sha256"] and old.get("outcome") == review["outcome"]:
            continue
        ledger[review["gap_id"]] = {**version, "outcome": review["outcome"], "reviewed_at": common.now_stamp()}

    # Compose the section and the detailed stories file, and decide whether either changes.
    lean_blocks = [e["raw"] if e["raw"] is not None else common.render_lean({**e["lean"], "story_id": e["story_id"]}) for e in plan]
    section_lf = common.render_section(lean_blocks)
    structure_changed = any(e["status"] != "unchanged" for e in plan) or bool(removed)
    document_changed = doc.section_state != "present" or structure_changed

    dropped = set(removed) | set(manually_deleted)
    plan_ids = {e["story_id"] for e in plan}
    # Detailed stories without a story in the document are kept and reported, never silently dropped.
    orphans = sorted((s for s in detailed_now if s not in plan_ids and s not in dropped), key=common.story_number)
    blocks_by_id = {
        e["story_id"]: e["draw"] if e["draw"] is not None else common.render_detailed({**e["full"], "story_id": e["story_id"]}) for e in plan
    }
    for story_id in orphans:
        blocks_by_id[story_id] = ctx.detailed.raw_blocks[story_id]
    detailed_blocks = [blocks_by_id[s] for s in sorted(blocks_by_id, key=common.story_number)]
    detailed_text = common.render_detailed_document(detailed_blocks)
    current_detailed = (common.normalise_eol(ctx.detailed.text).rstrip("\n") + "\n") if ctx.detailed.exists else None
    detailed_changed = detailed_text != current_detailed
    expected_detailed = {e["story_id"]: {**e["full"], "story_id": e["story_id"]} for e in plan}
    for story_id in orphans:
        expected_detailed[story_id] = detailed_now[story_id]

    overall = {e["story_id"]: overall_status(e) for e in plan}
    detailed_story_changes = sorted((e["story_id"] for e in plan if e["dstatus"] != "unchanged"), key=common.story_number)
    summary = {
        "story_count": len(plan),
        "created": [i for i, v in overall.items() if v == "created"],
        "updated": [i for i, v in overall.items() if v in ("updated", "overwritten")],
        "overwritten_manual_edits": [i for i, v in overall.items() if v == "overwritten"],
        "restored": [i for i, v in overall.items() if v == "restored"],
        "unchanged": [i for i, v in overall.items() if v == "unchanged"],
        "removed": removed,
        "manually_deleted_kept_out": manually_deleted,
        "lean_changed": [e["story_id"] for e in plan if e["status"] != "unchanged"],
        "detailed_changed": detailed_story_changes,
        "detailed_removed": sorted((s for s in dropped if s in detailed_now), key=common.story_number),
        "detailed_without_lean_story": orphans,
        "detailed_file_changed": detailed_changed,
        "document_changed": document_changed,
        "warnings": warnings,
        "target": ctx.target,
    }
    if args.dry_run:
        summary["dry_run"] = True
        return summary, 0

    new_doc = doc
    backup = None
    original_detailed = ctx.detailed.raw if ctx.detailed.exists else None
    new_raw = located = None
    if document_changed:
        new_text = common.compose_document(doc, section_lf)
        new_raw = common.document_bytes(doc, new_text)
        located = common.locate_section(new_text)
        outside_ok = new_text.startswith(doc.text) if doc.section_state != "present" else located["prefix"] == doc.prefix
        if not outside_ok:
            raise Refused("Internal check failed: content outside the managed section would change. Nothing was written.")
        backup = make_backup(paths, ctx.target, doc.raw)
        if common.sha256_bytes(common.read_bytes(ctx.target)) != doc.sha256:
            raise Refused("The document changed while the update was being prepared (concurrent edit). Nothing was written; a backup of the earlier version was kept.")
    if detailed_changed:
        if original_detailed is not None:
            summary["detailed_backup"] = make_backup(paths, paths.detailed_file, original_detailed)
        write_detailed_file(paths, detailed_text.encode("utf-8"), expected_detailed, original_detailed)
    if document_changed:
        try:
            common.atomic_write_bytes(ctx.target, new_raw, prefix=".story-doc-")
        except OSError as exc:
            if detailed_changed:
                restore_detailed_file(paths, original_detailed)
            raise IOFailure(f"cannot write {ctx.target}: {exc}. The document and the detailed stories are unchanged.")
        problems = verify_written(ctx.target, new_raw, plan, doc, located["prefix"])
        if problems:
            try:
                common.atomic_write_bytes(ctx.target, doc.raw, prefix=".story-doc-")
            except OSError:
                pass
            if detailed_changed:
                restore_detailed_file(paths, original_detailed)
            raise Refused("The saved document failed read-back verification; the previous version was restored.", problems)
        new_doc = common.read_document(ctx.target)
        summary["backup"] = backup

    not_covered = list(draft.get("not_covered_requirements", []))
    detailed_file_hash = common.sha256_text(detailed_text.rstrip("\n") + "\n")
    new_state = build_state(ctx, new_doc, entries, not_covered, ledger, retired | set(removed) | set(manually_deleted), highest, preserve, detailed_file_hash)
    state_changed = not same_state(state, new_state)
    summary["state_changed"] = state_changed
    state_ok = True
    if state_changed:
        try:
            save_state(paths, new_state)
        except IOFailure as exc:
            state_ok = False
            summary["error"] = str(exc)
            summary["warning"] = "The document was saved and verified but the story state was not. Run inspect, then accept, to recover the state from the document."
    summary["source_sha256"] = new_doc.sha256
    code = finish(paths, summary, state_ok)
    return summary, code


def verify_written(path, expected_raw, plan, original, expected_prefix):
    problems = []
    saved = common.read_bytes(path)
    if saved != expected_raw:
        problems.append("The saved file does not match what was prepared.")
    try:
        doc = common.Document(path, saved)
    except Refused as exc:
        return problems + [str(exc)]
    if doc.ambiguity or doc.section_state != "present":
        problems.append("The Development Stories section cannot be found after saving.")
        return problems
    if doc.prefix != expected_prefix:
        problems.append("Content outside the managed section changed.")
    if doc.problems:
        problems += doc.problems
    wanted = {e["story_id"]: common.lean_hash({**e["lean"], "story_id": e["story_id"]}) for e in plan}
    found = {s["story_id"]: common.lean_hash(s) for s in doc.stories}
    if wanted != found:
        problems.append("The stories read back do not match the stories that were written.")
    if doc.bom != original.bom:
        problems.append("The byte-order mark was not preserved.")
    return problems


# ----------------------------------------------------------------------------- accept


def parse_pairs(text):
    pairs = []
    for part in (text or "").split(","):
        if not part.strip():
            continue
        if "=" not in part:
            raise Refused(f"{part!r} is not OLD=NEW.")
        old, new = (side.strip().upper() for side in part.split("=", 1))
        if not (common.STORY_ID_RE.match(old) and common.STORY_ID_RE.match(new)):
            raise Refused(f"{part!r} must be two story IDs such as US-002=US-009.")
        pairs.append((old, new))
    return pairs


def cmd_accept(paths, args):
    ctx = load_context(paths, args.target, False)
    if ctx.gaps["status"] == "INVALID":
        ctx.gaps.update(status="IGNORED")
        ctx.register = None
    require_ready(ctx)
    doc, state = ctx.doc, ctx.state
    if args.expected_source_sha256 and doc.sha256 != args.expected_source_sha256:
        raise Refused("The document changed after it was inspected (concurrent edit). Nothing was recorded. Re-run inspect and retry.")
    if doc.section_state != "present":
        raise Refused("There is no Development Stories section to reconcile.")
    if doc.problems:
        raise Refused(
            "The section breaks the lean story contract (Story ID and short summary in the heading, Acceptance Criteria only; valid unique IDs). "
            "Fix these in the document, or have the stories rewritten with apply --overwrite after the user agrees.",
            doc.problems,
        )
    if doc.legacy_ids:
        raise Refused(
            "The section uses the layout of an earlier plugin version (" + ", ".join(doc.legacy_ids) + "). Run /sdlc-pipeline:ba-generate-stories to rewrite "
            "those stories as ultra-lean stories with detailed stories in " + common.DETAILED_RELATIVE + "; there is nothing to accept yet."
        )
    require_detailed_ok(ctx)
    detailed_now = ctx.detailed.stories
    baseline = state_story_map(ctx)
    current = {s["story_id"]: s for s in doc.stories}
    renames = parse_pairs(args.rename)
    retire = set(ids_from(args.retire, common.STORY_ID_RE, "story ID"))
    rename_from = {old for old, _ in renames}
    rename_to = {new for _, new in renames}
    for old, new in renames:
        if old not in baseline or old in current or new not in current or new in baseline:
            raise Refused(f"The rename {old}={new} does not match the document: {old} must have been removed and {new} must be new.")
    mappings = {}
    if args.mappings:
        try:
            mappings = json.loads(open(args.mappings, "r", encoding="utf-8-sig").read())
        except (OSError, ValueError) as exc:
            raise Refused(f"cannot read the mappings file: {exc}")
        if not isinstance(mappings, dict):
            raise Refused("The mappings file must be an object keyed by story ID.")

    removed = sorted((s for s in baseline if s not in current and s not in rename_from), key=common.story_number)
    unconfirmed = [s for s in removed if s not in retire]
    if unconfirmed:
        raise Refused(
            "Stories were deleted from the document. Confirm with the user, then pass them in --retire (their IDs are retired and never reused).",
            [f"{s} is in the story state but not in the document." for s in unconfirmed], {"deleted": unconfirmed},
        )
    entries, missing, bad, moves = [], [], [], {}
    for story_id in sorted(current, key=common.story_number):
        story = current[story_id]
        origin = next((old for old, new in renames if new == story_id), story_id)
        previous = baseline.get(origin)
        override = mappings.get(story_id, {}) if isinstance(mappings.get(story_id, {}), dict) else {}
        sources = override.get("source_requirement_ids", previous.get("source_requirement_ids") if previous else None)
        if not sources:
            missing.append(story_id)
            continue
        unknown = [r for r in sources if r not in ctx.requirements]
        if unknown:
            bad.append(f"{story_id}: unknown requirement(s) {', '.join(unknown)}.")
            continue
        if ctx.register is not None:
            related = common.derive_related_gaps(ctx.register, sources)
        else:
            related = list(previous.get("related_gap_ids", [])) if previous else []
        applied = [g for g in (previous.get("applied_decisions", []) if previous else []) if g in related or ctx.register is None]
        detailed = detailed_now.get(story_id)
        if detailed is None and origin != story_id and origin in detailed_now:
            detailed = {**detailed_now[origin], "story_id": story_id}
            moves[origin] = detailed
        derived = None
        if detailed is not None and previous and previous.get("detailed_content_hash"):
            lean_edited = common.lean_hash(story) != previous["story_content_hash"]
            detailed_edited = common.detailed_hash(detailed) != previous["detailed_content_hash"]
            was_stale = previous.get("lean_derived_from") != previous["detailed_content_hash"]
            # Keeping a hand-edited lean story is an explicit choice; a hand-edited detailed story still needs its lean story updated.
            if detailed_edited or (was_stale and not lean_edited):
                derived = previous.get("lean_derived_from")
        entries.append(story_entry(story_id, story, detailed, sources, related, applied, derived))
    if missing or bad:
        raise Refused(
            "Source requirement IDs are needed for stories that are new or have no recorded mapping. Work them out from the story text, confirm uncertain ones with the user, and pass --mappings.",
            [f"{s}: source requirement IDs are required (--mappings)." for s in missing] + bad, {"needs_mapping": missing},
        )

    retired = set((state or {}).get("retired_story_ids", [])) | retire | rename_from
    numbers = [common.story_number(s) for s in list(current) + list(baseline) + list(retired)]
    highest = max([int((state or {}).get("highest_story_number", 0))] + numbers)

    # The detailed stories of renamed stories follow their new ID; those of retired stories leave the file.
    detailed_rewrite = None
    gone = (rename_from | retire) & set(detailed_now)
    if gone:
        blocks = {}
        for story_id in ctx.detailed.order:
            if story_id in moves:
                blocks[moves[story_id]["story_id"]] = common.render_detailed(moves[story_id])
            elif story_id not in gone:
                blocks[story_id] = ctx.detailed.raw_blocks[story_id]
        detailed_rewrite = common.render_detailed_document([blocks[s] for s in sorted(blocks, key=common.story_number)])
    detailed_file_hash = common.sha256_text(detailed_rewrite.rstrip("\n") + "\n") if detailed_rewrite is not None else ctx.detailed.file_hash

    if state:
        new_state = copy.deepcopy(state)
        new_state.update(
            target_document=common.target_for_state(paths, ctx.target),
            detailed_document=common.DETAILED_RELATIVE,
            detailed_document_hash=detailed_file_hash,
            source_document_hash=doc.sha256,
            outside_section_hash=doc.outside_hash,
            managed_section_hash=doc.section_hash,
            highest_story_number=highest,
            retired_story_ids=sorted(retired, key=common.story_number),
            stories=entries,
        )
    else:
        new_state = build_state(ctx, doc, entries, [], {}, retired, highest, ctx.register is None, detailed_file_hash)
    new_state["schema_version"] = common.STATE_SCHEMA_VERSION
    new_state["last_successful_sync"] = common.now_stamp()
    if same_state(state, new_state):
        result = {"state_changed": False, "note": "The story state already matches the document and the detailed stories; nothing to reconcile.", "stories": len(entries)}
        return result, finish(paths, result)
    result = {
        "state_changed": True,
        "stories": len(entries),
        "retired": sorted(retire | rename_from, key=common.story_number),
        "renamed": [{"from": o, "to": n} for o, n in renames],
        "recovered_from_document": state is None,
        "document_modified": False,
    }
    if detailed_rewrite is not None:
        original = ctx.detailed.raw
        result["detailed_backup"] = make_backup(paths, paths.detailed_file, original)
        expected = {story_id: story for story_id, story in detailed_now.items() if story_id not in gone}
        expected.update({moved["story_id"]: moved for moved in moves.values()})
        write_detailed_file(paths, detailed_rewrite.encode("utf-8"), expected, original)
        result["detailed_renamed"] = [{"from": old, "to": moved["story_id"]} for old, moved in moves.items()]
        result["detailed_removed"] = sorted(gone - set(moves), key=common.story_number)
    try:
        save_state(paths, new_state)
    except IOFailure as exc:
        raise IOFailure(str(exc))
    return result, finish(paths, result)


# -------------------------------------------------------------------------- CLI


def cmd_inspect(paths, args):
    return inspect_project(load_context(paths, args.target, args.ignore_gaps)), 0


def cmd_summary(paths, args):
    """Real counts for the execution summaries, from the saved document, state and register."""
    ctx = load_context(paths, args.target, args.ignore_gaps)
    gap_status = ctx.gaps["status"]
    if gap_status == "INVALID":  # a summary still works; it just cannot say anything about gaps
        ctx.gaps = dict(ctx.gaps, status="IGNORED")
    require_ready(ctx)
    if ctx.state is None or ctx.doc.section_state != "present":
        raise Refused("No synchronised stories exist yet. Run /sdlc-pipeline:ba-generate-stories first.")
    state, doc = ctx.state, ctx.doc
    covered = sorted({r for e in state["stories"] for r in e.get("source_requirement_ids", [])}, key=common.requirement_number)
    listed = state.get("not_covered_requirements", [])
    unexplained = [r for r in uncovered_requirements(ctx)]
    statuses = {g["gap_id"]: g["status"] for g in ctx.register or []}
    referenced = sorted({g for e in state["stories"] for g in e.get("related_gap_ids", [])})
    errors, warnings, pair = validator.validate_story_set(doc.stories, doc.problems, ctx.detailed, ctx.requirements, state, ctx.legacy_files)
    report_exists = os.path.isfile(paths.report)
    pair_in_sync = not (pair["detailed_missing"] or pair["detailed_extra"] or pair["detailed_edited"] or pair["detailed_untracked"] or pair["lean_edited"] or pair["lean_stale"])
    known_hash = state.get("detailed_document_hash")
    detailed_in_sync = not known_hash or (ctx.detailed.exists and ctx.detailed.file_hash == known_hash)
    return {
        "target": ctx.target,
        "stories": len(doc.stories),
        "requirements": {
            "analysed": len(ctx.requirements), "covered": len(covered), "not_covered": listed, "uncovered_unexplained": unexplained,
        },
        "gaps": {
            "status": gap_status,
            "referenced": {s: sum(1 for g in referenced if statuses.get(g) == s) for s in ("open", "skipped", "resolved")},
            "register_counts": None if ctx.register is None else {s: sum(1 for v in statuses.values() if v == s) for s in ("open", "skipped", "resolved")},
        },
        "detailed": {
            "file": common.DETAILED_RELATIVE,
            "file_exists": ctx.detailed.exists,
            "stories": len(ctx.detailed.stories),
            "missing": pair["detailed_missing"],
            "without_lean_story": pair["detailed_extra"],
            "edited_since_sync": pair["detailed_edited"],
            "lean_needs_update": pair["lean_stale"],
            "legacy_files": ctx.legacy_files,
        },
        "validation": {"passed": not errors, "errors": errors, "warnings": warnings},
        "in_sync": doc.section_hash == state["managed_section_hash"] and pair_in_sync and detailed_in_sync,
        "report": {"path": "report/phase3-report.html", "exists": report_exists},
    }, 0


def cmd_regenerate(paths, args):
    code, message = reporter.generate(paths)
    return {"report": {"generated": code == 0, "path": "report/phase3-report.html", "message": message}}, code


def build_parser():
    parser = argparse.ArgumentParser(description="Safe persistence for development stories.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, **kwargs):
        p = sub.add_parser(name, **kwargs)
        p.add_argument("--project-root", default=os.getcwd())
        return p

    for name in ("inspect", "export", "summary"):
        p = add(name)
        p.add_argument("--target")
        p.add_argument("--ignore-gaps", action="store_true")
        if name == "export":
            p.add_argument("--draft-out")
    apply = add("apply")
    apply.add_argument("--draft", required=True)
    apply.add_argument("--target")
    apply.add_argument("--ignore-gaps", action="store_true")
    apply.add_argument("--expected-source-sha256")
    apply.add_argument("--overwrite", default="")
    apply.add_argument("--allow-remove", default="")
    apply.add_argument("--restore", default="")
    apply.add_argument("--acknowledge-changes", action="store_true")
    apply.add_argument("--change-target", action="store_true")
    apply.add_argument("--dry-run", action="store_true")
    accept = add("accept")
    accept.add_argument("--target")
    accept.add_argument("--expected-source-sha256")
    accept.add_argument("--mappings")
    accept.add_argument("--rename", default="")
    accept.add_argument("--retire", default="")
    add("regenerate-report")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    paths = common.Paths(args.project_root)
    handlers = {"inspect": cmd_inspect, "summary": cmd_summary, "export": cmd_export, "apply": cmd_apply, "accept": cmd_accept, "regenerate-report": cmd_regenerate}
    try:
        result, code = handlers[args.command](paths, args)
        result = {"ok": code in (0, 3), **result}
    except Refused as exc:
        result, code = {"ok": False, "error": str(exc), "details": exc.details, **exc.data}, 1
    except IOFailure as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
