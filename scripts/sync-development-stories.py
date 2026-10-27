#!/usr/bin/env python3
"""Safe section handling and persistence for development stories (ba-requirements plugin, Phase 3).

Every write to the requirements document, the story state and the Phase 3 report goes through
this script, so the commands never hand-edit them: boundary detection, hashing, manual-edit and
concurrency detection, backup, temp-file write with atomic replace, read-back verification and
state update (only after verification). Standard library only.

Usage (all commands take --project-root, default: the current directory):

  inspect  [--target DOC] [--ignore-gaps]
      Read-only. Input validity, target document and section status, stories found, manual
      changes since the last sync, atomic-requirement and gap-register changes, resolved
      decisions not yet reflected in stories, and requirements not covered by a story.
      Status: INPUT_MISSING | INPUT_INVALID | INPUT_EMPTY | TARGET_REQUIRED | TARGET_NOT_MARKDOWN |
      DOCUMENT_MISSING | DOCUMENT_UNREADABLE | SECTION_AMBIGUOUS | OK.

  export   [--target DOC] [--ignore-gaps] [--draft-out FILE]
      Read-only. The stories now in the document as a valid draft, plus their traceability context.

  apply    --draft FILE [--target DOC] [--ignore-gaps] [--expected-source-sha256 H]
           [--overwrite US-001,..] [--allow-remove US-001,..] [--restore US-001,..]
           [--acknowledge-changes] [--change-target] [--dry-run]
      Validate a structured draft (schemas/development-stories.schema.json) and write it as the
      managed '# Development Stories' section. New stories (story_id null) get the next unused ID.

  accept   [--target DOC] [--expected-source-sha256 H] [--mappings FILE]
           [--rename OLD=NEW,..] [--retire US-001,..]
      Reconcile manual edits to the section into the story state without touching the document.

  summary  [--target DOC] [--ignore-gaps]
      Read-only. Real counts for execution summaries: stories, requirement coverage, gaps
      referenced by status, validation result, synchronisation status.

  regenerate-report
      Rebuild report/phase3-report.html only. Nothing else changes.

Results are printed as JSON. Exit status: 0 = success, 1 = refused or invalid (nothing changed),
2 = a file could not be read or written (nothing changed), 3 = saved but the HTML report could not
be generated (run regenerate-report), 4 = the document was saved and verified but the state could
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
        if common.content_hash(story) == base[story_id]["story_content_hash"]:
            continue
        edited.append(story_id)
        known = base[story_id].get("field_hashes")
        detail = {}
        if known:
            now = common.field_hashes(story)
            detail["summary_changed"] = known.get("summary") != now["summary"]
            detail["description_changed"] = known.get("description") != now["description"]
            old_set, new_set = set(known.get("acceptance_criteria", [])), set(now["acceptance_criteria"])
            detail["criteria_added"] = [text for text, h in zip(story["acceptance_criteria"], now["acceptance_criteria"]) if h not in old_set]
            detail["criteria_removed_count"] = len(old_set - new_set)
        details[story_id] = detail
    added = sorted(set(cur) - set(base), key=common.story_number)
    removed = sorted(set(base) - set(cur), key=common.story_number)
    id_changes = []
    for old in removed:
        for new in added:
            if base[old]["story_content_hash"] == common.content_hash(cur[new]):
                id_changes.append({"from": old, "to": new})
    return {"edited": edited, "edited_details": details, "added": added, "removed": removed, "id_changes": id_changes}


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
        "paths": {"requirements": paths.requirements, "gaps": paths.register, "state": paths.state, "report": paths.report},
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
    }
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
        report["recoverable_from_document"] = doc.section_state == "present" and not doc.problems
    report["pending_decisions"] = pending_decisions(ctx)
    report["uncovered_requirements"] = uncovered_requirements(ctx)
    return report


# ----------------------------------------------------------------------------- export


def story_context(ctx, story, baseline):
    entry = baseline.get(story["story_id"])
    sources = list(entry.get("source_requirement_ids", [])) if entry else []
    return {
        "story_id": story["story_id"],
        "source_requirement_ids": sources,
        "related_gap_ids": common.derive_related_gaps(ctx.register, sources) if ctx.register is not None else list(entry.get("related_gap_ids", [])) if entry else [],
        "applied_decisions": list(entry.get("applied_decisions", [])) if entry else [],
        "edited_since_last_sync": entry is None or entry["story_content_hash"] != common.content_hash(story),
    }


def cmd_export(paths, args):
    ctx = load_context(paths, args.target, args.ignore_gaps)
    require_ready(ctx)
    if ctx.doc.problems:
        raise Refused("The managed section has structural problems; reconcile them with /sdlc-pipeline:ba-sync-stories first.", ctx.doc.problems)
    baseline = state_story_map(ctx)
    contexts = [story_context(ctx, s, baseline) for s in ctx.doc.stories]
    draft = {
        "stories": [
            {
                "story_id": s["story_id"],
                "summary": s["summary"],
                "description": s["description"],
                "acceptance_criteria": s["acceptance_criteria"],
                "source_requirement_ids": c["source_requirement_ids"],
                "applied_decisions": c["applied_decisions"],
            }
            for s, c in zip(ctx.doc.stories, contexts)
        ],
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
        "draft": draft,
        "story_context": contexts,
        "draft_written_to": args.draft_out,
    }, 0


# ----------------------------------------------------------------------------- state


def build_state(ctx, doc, entries, not_covered, ledger, retired, highest, preserve_gaps):
    paths = ctx.paths
    previous = ctx.state or {}
    state = {
        "schema_version": common.STATE_SCHEMA_VERSION,
        "target_document": common.target_for_state(paths, ctx.target),
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


def story_entry(story_id, story, sources, related, applied):
    return {
        "story_id": story_id,
        "source_requirement_ids": sorted(sources, key=common.requirement_number),
        "related_gap_ids": related,
        "applied_decisions": sorted(applied, key=lambda g: int(common.GAP_ID_RE.match(g).group(1))),
        "story_content_hash": common.content_hash(story),
        "field_hashes": common.field_hashes(story),
    }


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
        raise IOFailure(f"cannot create the backup {candidate}: {exc}. The document was not modified.")
    return candidate


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
    for story_id in restore:
        if story_id in doc_by_id or story_id not in baseline:
            raise Refused(f"{story_id} cannot be restored: it is not a story that was deleted from the document.")

    plan, conflicts = [], []
    for item in draft["stories"]:
        story_id = item.get("story_id")
        entry = {"draft": item, "story_id": story_id, "status": "created", "raw": None}
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
                    conflicts.append({"story_id": story_id, "reason": "deleted_by_hand", "message": "The story was deleted from the document by hand; restoring it needs --restore."})
            elif common.content_hash(item) == common.content_hash(current):
                entry.update(status="unchanged", raw=current["raw"])
            else:
                known = baseline.get(story_id, {}).get("story_content_hash")
                if known is not None and known == common.content_hash(current):
                    entry["status"] = "updated"
                elif story_id in overwrite:
                    entry["status"] = "overwritten"
                else:
                    conflicts.append({
                        "story_id": story_id,
                        "reason": "manual_edit" if known else "no_baseline",
                        "message": "The story differs from the last known version (edited by hand)." if known else "No synchronised baseline exists for this story, so existing content is not overwritten silently.",
                        "current": common.canonical_story(current),
                        "proposed": common.canonical_story(item),
                    })
        plan.append(entry)
    draft_ids = {e["story_id"] for e in plan if e["story_id"]}
    removed = []
    for story_id, current in doc_by_id.items():
        if story_id not in draft_ids:
            if story_id in allow_remove:
                removed.append(story_id)
            else:
                conflicts.append({"story_id": story_id, "reason": "would_be_removed", "message": "The story is in the document but not in the draft; removing it needs --allow-remove.", "current": common.canonical_story(current)})
    if conflicts:
        raise Refused(
            "The draft would overwrite or remove content that was changed or should not be dropped silently. Show the conflicts to the user and ask how to proceed.",
            [f"{c['story_id']}: {c['reason']}" for c in conflicts], {"conflicts": conflicts},
        )
    manually_deleted = sorted((s for s in baseline if s not in doc_by_id and s not in draft_ids), key=common.story_number)

    numbers = [common.story_number(s) for s in list(doc_by_id) + list(baseline) + list(retired)]
    highest = max([int((state or {}).get("highest_story_number", 0))] + numbers)
    for entry in plan:
        if entry["story_id"] is None:
            highest += 1
            entry["story_id"] = common.format_story_id(highest)
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
        entries.append(story_entry(e["story_id"], item, sources, related, applied))
    for review in draft.get("decisions_reviewed", []):
        version = common.decision_version(gaps_by_id[review["gap_id"]])
        old = ledger.get(review["gap_id"])
        if old and old.get("recorded_at") == version["recorded_at"] and old.get("decision_sha256") == version["decision_sha256"] and old.get("outcome") == review["outcome"]:
            continue
        ledger[review["gap_id"]] = {**version, "outcome": review["outcome"], "reviewed_at": common.now_stamp()}

    # Compose the section and decide whether the document changes.
    blocks = [e["raw"] if e["raw"] is not None else common.render_story({**e["draft"], "story_id": e["story_id"]}) for e in plan]
    section_lf = common.render_section(blocks)
    structure_changed = any(e["status"] != "unchanged" for e in plan) or bool(removed)
    document_changed = doc.section_state != "present" or structure_changed

    summary = {
        "story_count": len(plan),
        "created": [e["story_id"] for e in plan if e["status"] == "created"],
        "updated": [e["story_id"] for e in plan if e["status"] in ("updated", "overwritten")],
        "overwritten_manual_edits": [e["story_id"] for e in plan if e["status"] == "overwritten"],
        "restored": [e["story_id"] for e in plan if e["status"] == "restored"],
        "unchanged": [e["story_id"] for e in plan if e["status"] == "unchanged"],
        "removed": removed,
        "manually_deleted_kept_out": manually_deleted,
        "document_changed": document_changed,
        "warnings": warnings,
        "target": ctx.target,
    }
    if args.dry_run:
        summary["dry_run"] = True
        return summary, 0

    new_doc = doc
    backup = None
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
        try:
            common.atomic_write_bytes(ctx.target, new_raw, prefix=".story-doc-")
        except OSError as exc:
            raise IOFailure(f"cannot write {ctx.target}: {exc}. The document is unchanged.")
        problems = verify_written(ctx.target, new_raw, plan, doc, located["prefix"])
        if problems:
            try:
                common.atomic_write_bytes(ctx.target, doc.raw, prefix=".story-doc-")
            except OSError:
                pass
            raise Refused("The saved document failed read-back verification; the previous version was restored.", problems)
        new_doc = common.read_document(ctx.target)
        summary["backup"] = backup

    not_covered = list(draft.get("not_covered_requirements", []))
    new_state = build_state(ctx, new_doc, entries, not_covered, ledger, retired | set(removed) | set(manually_deleted), highest, preserve)
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
    wanted = {e["story_id"]: common.content_hash({**e["draft"], "story_id": e["story_id"]}) for e in plan}
    found = {s["story_id"]: common.content_hash(s) for s in doc.stories}
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
            "The section breaks the story contract (four fields only, valid unique IDs). Fix these in the document, or have the stories rewritten with apply --overwrite after the user agrees.",
            doc.problems,
        )
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
    entries, missing, bad = [], [], []
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
        entries.append(story_entry(story_id, story, sources, related, applied))
    if missing or bad:
        raise Refused(
            "Source requirement IDs are needed for stories that are new or have no recorded mapping. Work them out from the story text, confirm uncertain ones with the user, and pass --mappings.",
            [f"{s}: source requirement IDs are required (--mappings)." for s in missing] + bad, {"needs_mapping": missing},
        )

    retired = set((state or {}).get("retired_story_ids", [])) | retire | rename_from
    numbers = [common.story_number(s) for s in list(current) + list(baseline) + list(retired)]
    highest = max([int((state or {}).get("highest_story_number", 0))] + numbers)
    if state:
        new_state = copy.deepcopy(state)
        new_state.update(
            target_document=common.target_for_state(paths, ctx.target),
            source_document_hash=doc.sha256,
            outside_section_hash=doc.outside_hash,
            managed_section_hash=doc.section_hash,
            highest_story_number=highest,
            retired_story_ids=sorted(retired, key=common.story_number),
            stories=entries,
        )
    else:
        new_state = build_state(ctx, doc, entries, [], {}, retired, highest, ctx.register is None)
    new_state["last_successful_sync"] = common.now_stamp()
    if same_state(state, new_state):
        result = {"state_changed": False, "note": "The story state already matches the document; nothing to reconcile.", "stories": len(entries)}
        return result, finish(paths, result)
    result = {
        "state_changed": True,
        "stories": len(entries),
        "retired": sorted(retire | rename_from, key=common.story_number),
        "renamed": [{"from": o, "to": n} for o, n in renames],
        "recovered_from_document": state is None,
        "document_modified": False,
    }
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
    errors, warnings = validator.validate_managed_section(doc.stories, doc.problems, ctx.requirements, state)
    report_exists = os.path.isfile(paths.report)
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
        "validation": {"passed": not errors, "errors": errors, "warnings": warnings},
        "in_sync": doc.section_hash == state["managed_section_hash"],
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
