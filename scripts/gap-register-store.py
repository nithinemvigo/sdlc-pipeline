#!/usr/bin/env python3
"""Safe persistence for the gap register (ba-requirements plugin, Phase 2).

One place for every write to gaps/, so the commands never hand-edit JSON:
validate before and after, atomic replace, read-back, analysis-state hash,
HTML regeneration, and the invariants that keep decisions and IDs safe.
Standard library only. The atomic requirements file is only ever read.

Usage (all commands take --project-root, default: the current directory):

  inspect                      Input validity, input hash, register/state status and a
                               requirement diff. Status is one of: INPUT_MISSING,
                               INPUT_INVALID, INPUT_EMPTY, NO_REGISTER, REGISTER_INVALID,
                               NO_STATE, UNCHANGED, CHANGED.
  save --draft F --mode new|reconcile|reset
       [--confirmed GAP-001,...] [--retire GAP-004,... --retire-reason TEXT --approve-retirement]
       [--confirm-reset]       Validate a draft register and persist it with the analysis state.
  list                         Triage queue: open and skipped gaps, Critical > Low, then gap number.
  resolve --gap-id G --decision-file F|- [--revise]
  skip --gap-id G
  reopen --gap-id G            Triage actions; each saves, validates and regenerates the report.
  summary                      Counts for the execution or session summary.
  regenerate-report            Rebuild gap-analysis.html from gaps.json.

Results are printed as JSON. Exit status: 0 = success, 1 = refused or invalid (nothing
changed), 2 = file could not be read or written, 3 = register saved but the HTML report
could not be generated (run regenerate-report).
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_VERSION = 1
ANALYSIS_LOGIC_VERSION = "2.0.0"
REGISTER_SCHEMA = "gap-register/1"
PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
GAP_ID_RE = re.compile(r"^GAP-([0-9]{3,})$")


def _load(filename, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPT_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load("validate-gap-register.py", "validate_gap_register")
reporter = _load("generate-gap-report.py", "generate_gap_report")
atomic_validator = _load("validate-atomic-requirements.py", "validate_atomic_requirements")


class Refused(Exception):
    """The requested change is not allowed or the data is invalid; nothing was written."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or []


class IOFailure(Exception):
    """A file could not be read or written."""


# ----------------------------------------------------------------------------- paths


class Paths:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.requirements = os.path.join(self.root, "atomic_requirements", "atomic_requirements.json")
        self.gaps_dir = os.path.join(self.root, "gaps")
        self.register = os.path.join(self.gaps_dir, "gaps.json")
        self.report = os.path.join(self.gaps_dir, "gap-analysis.html")
        self.state = os.path.join(self.gaps_dir, "gap-analysis-state.json")
        self.retired = os.path.join(self.gaps_dir, "retired-gaps.json")


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def gap_number(gap_id):
    return int(GAP_ID_RE.match(gap_id).group(1))


def format_gap_id(number):
    return f"GAP-{number:03d}"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def to_json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


# ------------------------------------------------------------------- atomic file writes


def atomic_write_bytes(path, payload):
    """Write to a temp file in the same directory, flush, then replace. The target is never half-written."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("wb", dir=directory, prefix=".gaps-", suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise IOFailure(f"cannot read {path}: {exc}")


# ----------------------------------------------------------------------- input handling


def load_input(paths):
    """Return (status, errors, requirements, raw_bytes). status None means usable."""
    if not os.path.isfile(paths.requirements):
        return "INPUT_MISSING", [f"{paths.requirements} does not exist. Run /sdlc-pipeline:ba-start-analysis first."], None, None
    try:
        raw = read_bytes(paths.requirements)
        text = raw.decode("utf-8-sig")
    except (IOFailure, UnicodeDecodeError) as exc:
        return "INPUT_INVALID", [f"cannot read atomic requirements: {exc}"], None, None
    duplicate_keys = []
    try:
        data = atomic_validator.parse_json(text, duplicate_keys)
    except json.JSONDecodeError as exc:
        return "INPUT_INVALID", [f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."], None, None
    if isinstance(data, list) and not data:
        return "INPUT_EMPTY", ["The atomic requirements array is empty; there are no requirements to analyse."], None, raw
    errors = atomic_validator.validate(data, duplicate_keys, check_sequence=False)
    if errors:
        return "INPUT_INVALID", errors, None, raw
    requirements = {item["requirement_id"]: item for item in data}
    return None, [], requirements, raw


def requirement_fingerprint(item):
    return sha256_bytes(json.dumps([item["title"], item["description"]], ensure_ascii=False).encode("utf-8"))


def requirement_snapshot(requirements):
    return {
        req_id: {"title": item["title"], "sha256": requirement_fingerprint(item)}
        for req_id, item in requirements.items()
    }


def diff_requirements(old_snapshot, requirements):
    added = sorted(req_id for req_id in requirements if req_id not in old_snapshot)
    removed = sorted(req_id for req_id in old_snapshot if req_id not in requirements)
    changed = sorted(
        req_id
        for req_id in requirements
        if req_id in old_snapshot and old_snapshot[req_id].get("sha256") != requirement_fingerprint(requirements[req_id])
    )
    return {"added": added, "changed": changed, "removed": removed}


# ------------------------------------------------------------------- state and archive


def load_state(paths):
    """Return the state dict, or None if absent or unusable."""
    if not os.path.isfile(paths.state):
        return None
    try:
        data, _ = validator.read_json(paths.state)
    except validator.InputError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("input_sha256"), str):
        return None
    if not isinstance(data.get("requirements"), dict) or not isinstance(data.get("highest_gap_number"), int):
        return None
    return data


def load_retired(paths):
    if not os.path.isfile(paths.retired):
        return []
    try:
        data, _ = validator.read_json(paths.retired)
    except validator.InputError as exc:
        raise Refused(f"The retired-gap archive is unreadable: {exc}")
    if not isinstance(data, list):
        raise Refused(f"{paths.retired} must be a JSON array.")
    return data


def highest_gap_number(register, state, retired):
    numbers = [gap_number(gap["gap_id"]) for gap in register or []]
    if state:
        numbers.append(state["highest_gap_number"])
    for entry in retired:
        gap_id = entry.get("gap", {}).get("gap_id", "") if isinstance(entry, dict) else ""
        if GAP_ID_RE.match(gap_id):
            numbers.append(gap_number(gap_id))
    return max(numbers, default=0)


# -------------------------------------------------------------------------- inspection


def load_register(paths, requirements, allow_stale):
    """Return (register or None, errors, warnings, raw_bytes). Reads gaps.json only."""
    try:
        raw = read_bytes(paths.register)
        data, duplicate_keys = validator.read_json(paths.register)
    except (IOFailure, validator.InputError) as exc:
        return None, [str(exc)], [], None
    errors, warnings = validator.validate_register(data, duplicate_keys, requirements and {k: v["description"] for k, v in requirements.items()}, allow_stale)
    return (None if errors else data), errors, warnings, raw


def inspect_project(paths):
    """Describe the project's analysis state. Returns (report dict, internals dict)."""
    report = {
        "project_root": paths.root,
        "requirements_path": paths.requirements,
        "register_path": paths.register,
        "report_path": paths.report,
        "state_path": paths.state,
    }
    status, errors, requirements, raw = load_input(paths)
    internals = {"requirements": requirements, "input_bytes": raw, "register": None, "state": None, "retired": []}
    if status:
        report.update(status=status, errors=errors)
        return report, internals

    report["requirement_count"] = len(requirements)
    report["input_sha256"] = sha256_bytes(raw)
    state = load_state(paths)
    internals["state"] = state
    internals["retired"] = load_retired(paths)

    if not os.path.isfile(paths.register):
        report.update(status="NO_REGISTER", next_gap_id=format_gap_id(highest_gap_number(None, state, internals["retired"]) + 1))
        report["stray_state_found"] = state is not None
        return report, internals

    register, errors, warnings, _ = load_register(paths, requirements, allow_stale=True)
    if register is None:
        report.update(status="REGISTER_INVALID", errors=errors)
        return report, internals
    internals["register"] = register
    report["gap_count"] = len(register)
    report["warnings"] = warnings
    report["next_gap_id"] = format_gap_id(highest_gap_number(register, state, internals["retired"]) + 1)

    if state is None:
        report.update(status="NO_STATE", changes=None)
        return report, internals

    if state["input_sha256"] == report["input_sha256"]:
        # Same input: references must match exactly, not merely be tolerated.
        strict_errors, _ = validator.validate_register(
            register, [], {k: v["description"] for k, v in requirements.items()}, allow_stale=False
        )
        if strict_errors:
            report.update(status="REGISTER_INVALID", errors=strict_errors)
            return report, internals
        report.update(status="UNCHANGED", changes={"added": [], "changed": [], "removed": []})
        return report, internals

    report.update(status="CHANGED", changes=diff_requirements(state["requirements"], requirements))
    return report, internals


# ---------------------------------------------------------------------- persistence core


def regenerate_report(paths):
    code, message = reporter.generate(paths.register, paths.report, paths.requirements)
    return code == 0, message


def write_register(paths, requirements, register, previous_bytes):
    """Validate, atomically replace gaps.json, read it back and validate again.

    On a failed read-back the previous file contents are restored.
    """
    description_map = {k: v["description"] for k, v in requirements.items()}
    errors, _ = validator.validate_register(register, [], description_map, allow_stale=False)
    if errors:
        raise Refused("The updated register is invalid; nothing was saved.", errors)
    payload = to_json_bytes(register)
    try:
        atomic_write_bytes(paths.register, payload)
    except OSError as exc:
        raise IOFailure(f"cannot save {paths.register}: {exc}. The last valid register is unchanged.")
    try:
        saved = read_bytes(paths.register)
        reloaded, duplicate_keys = validator.read_json(paths.register)
        readback_errors, _ = validator.validate_register(reloaded, duplicate_keys, description_map, allow_stale=False)
        if saved != payload:
            readback_errors = readback_errors + ["The saved file does not match what was validated."]
    except (IOFailure, validator.InputError) as exc:
        readback_errors = [str(exc)]
    if readback_errors:
        if previous_bytes is not None:
            try:
                atomic_write_bytes(paths.register, previous_bytes)
            except OSError:
                pass
        raise Refused("The saved register failed read-back verification; the previous version was restored.", readback_errors)
    return sha256_bytes(payload)


def write_state(paths, raw_input, requirements, register, retired):
    state = {
        "state_version": STATE_VERSION,
        "register_schema": REGISTER_SCHEMA,
        "analysis_logic_version": ANALYSIS_LOGIC_VERSION,
        "input_sha256": sha256_bytes(raw_input),
        "analysed_at": now_stamp(),
        "requirement_count": len(requirements),
        "requirements": requirement_snapshot(requirements),
        "highest_gap_number": highest_gap_number(register, load_state(paths), retired),
    }
    try:
        atomic_write_bytes(paths.state, to_json_bytes(state))
    except OSError as exc:
        raise IOFailure(f"cannot save {paths.state}: {exc}")
    return state


def finish(paths, result):
    """Regenerate the report and set the exit code. The JSON stays authoritative if this fails."""
    ok, message = regenerate_report(paths)
    result["html_generated"] = ok
    result["html_message"] = message
    if not ok:
        result["warning"] = "The register was saved, but the HTML report could not be generated. Run regenerate-report."
    return 0 if ok else 3


# --------------------------------------------------------------------------- save modes


def parse_id_list(text):
    ids = [part.strip().upper() for part in (text or "").split(",") if part.strip()]
    for gap_id in ids:
        if not GAP_ID_RE.match(gap_id):
            raise Refused(f"{gap_id!r} is not a valid gap ID (expected GAP-001 format).")
    return ids


def check_new_register(draft):
    errors = []
    numbers = sorted(gap_number(gap["gap_id"]) for gap in draft)
    if numbers != list(range(1, len(draft) + 1)):
        errors.append("A new register must use sequential IDs GAP-001, GAP-002, ... with no gaps.")
    for gap in draft:
        if gap["status"] != "open":
            errors.append(f"{gap['gap_id']}: new gaps must have status 'open'.")
        if gap["decisions_recorded"]:
            errors.append(f"{gap['gap_id']}: gap analysis must not record decisions.")
    return errors


def check_reconciliation(existing, draft, highest, changes, confirmed, retire_ids):
    """Enforce the safety invariants. Returns (errors, report)."""
    errors = []
    existing_by_id = {gap["gap_id"]: gap for gap in existing}
    draft_by_id = {gap["gap_id"]: gap for gap in draft}
    affected_by_change = None if changes is None else set(changes["changed"]) | set(changes["removed"])
    report = {"kept": [], "modified": [], "reopened": [], "new": [], "retired": [], "needs_confirmation": []}

    for gap_id in retire_ids:
        if gap_id not in existing_by_id:
            errors.append(f"Cannot retire {gap_id}: it is not in the existing register.")
        elif gap_id in draft_by_id:
            errors.append(f"{gap_id} is both retired and present in the draft; choose one.")
    for gap_id in existing_by_id:
        if gap_id not in draft_by_id and gap_id not in retire_ids:
            errors.append(
                f"{gap_id} was dropped from the draft. Existing gaps and their decision history are never deleted: "
                "keep it (update its references) or retire it with explicit user approval."
            )
    report["retired"] = [gap_id for gap_id in retire_ids if gap_id in existing_by_id]

    allowed = {("open", "open"), ("skipped", "skipped"), ("resolved", "resolved"), ("resolved", "open"), ("skipped", "open")}
    for gap_id, new in draft_by_id.items():
        old = existing_by_id.get(gap_id)
        if old is None:
            if gap_number(gap_id) <= highest:
                errors.append(f"{gap_id}: new gaps need IDs above {format_gap_id(highest)}; IDs of earlier or retired gaps are never reused.")
            if new["status"] != "open" or new["decisions_recorded"]:
                errors.append(f"{gap_id}: a new gap must be open with no decisions.")
            report["new"].append(gap_id)
            continue

        if new["decisions_recorded"] != old["decisions_recorded"]:
            errors.append(f"{gap_id}: decisions_recorded was altered. Gap analysis never adds, edits or removes decisions.")
        if (old["status"], new["status"]) not in allowed:
            errors.append(f"{gap_id}: status change {old['status']} -> {new['status']} is not allowed during gap analysis.")

        old_refs = {ref["requirement_id"] for ref in old["affected_requirements"]}
        new_refs = {ref["requirement_id"] for ref in new["affected_requirements"]}
        touched = affected_by_change is None or bool(old_refs & affected_by_change)
        meaning_changed = (
            new["gap_definition"] != old["gap_definition"] or new["priority"] != old["priority"] or new_refs != old_refs
        )
        if old["status"] == "resolved" and new["status"] == "open":
            report["reopened"].append(gap_id)
        elif old["status"] == "resolved" and (touched or meaning_changed):
            if gap_id in confirmed:
                report["modified"].append(gap_id)
            else:
                report["needs_confirmation"].append(gap_id)
                errors.append(
                    f"{gap_id}: resolved gap whose requirements or wording changed. Ask the user whether the recorded decision still "
                    "addresses it; keep it resolved only with --confirmed, otherwise set it back to open."
                )
        elif meaning_changed or touched:
            report["modified"].append(gap_id)
        else:
            report["kept"].append(gap_id)
    return errors, report


def retire_gaps(paths, existing, retire_ids, reason):
    archive = load_retired(paths)
    by_id = {gap["gap_id"]: gap for gap in existing}
    stamp = now_stamp()
    archived_ids = set()
    for entry in archive:
        entry_gap = entry.get("gap", {}) if isinstance(entry, dict) else {}
        archived_ids.add(entry_gap.get("gap_id"))
    for gap_id in retire_ids:
        if gap_id not in archived_ids:
            archive.append({"retired_at": stamp, "reason": reason, "gap": by_id[gap_id]})
    try:
        atomic_write_bytes(paths.retired, to_json_bytes(archive))
    except OSError as exc:
        raise IOFailure(f"cannot save {paths.retired}: {exc}")
    return archive


def cmd_save(paths, args):
    info, internals = inspect_project(paths)
    if info["status"] in ("INPUT_MISSING", "INPUT_INVALID", "INPUT_EMPTY"):
        raise Refused("The atomic requirements cannot be analysed.", info["errors"])
    requirements = internals["requirements"]
    description_map = {k: v["description"] for k, v in requirements.items()}

    try:
        draft, duplicate_keys = validator.read_json(args.draft)
    except validator.InputError as exc:
        raise Refused(f"The draft cannot be read: {exc}")
    errors, _ = validator.validate_register(draft, duplicate_keys, description_map, allow_stale=False)
    if errors:
        raise Refused("The draft register is invalid; nothing was saved.", errors)

    mode = args.mode
    register_exists = os.path.isfile(paths.register)
    state = internals["state"]
    retired = internals["retired"]
    previous_bytes = read_bytes(paths.register) if register_exists else None
    result = {"mode": mode, "gap_count": len(draft)}
    retire_ids = parse_id_list(args.retire)

    if mode == "new":
        if register_exists:
            raise Refused(
                "A gap register already exists and is never overwritten by a fresh analysis. "
                "Use --mode reconcile to update it, or --mode reset --confirm-reset to discard it."
            )
        if state is not None or retired:
            raise Refused(
                "A previous analysis state or retired-gap archive exists without a register. Gap IDs from that history must not be reused. "
                "Use --mode reset --confirm-reset to start over (the old files are backed up first)."
            )
        errors = check_new_register(draft)
        if errors:
            raise Refused("The draft is not a valid new register.", errors)
        if retire_ids:
            raise Refused("--retire applies only to --mode reconcile.")

    elif mode == "reset":
        if not args.confirm_reset:
            raise Refused(
                "Reset discards the current register, its decisions and its analysis state (they are backed up first). "
                "Explain this to the user and re-run with --confirm-reset only after explicit confirmation."
            )
        errors = check_new_register(draft)
        if errors:
            raise Refused("The draft is not a valid new register.", errors)
        backed_up = []
        if any(os.path.exists(p) for p in (paths.register, paths.state, paths.retired)):
            backup_dir = os.path.join(paths.gaps_dir, "backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
            os.makedirs(backup_dir, exist_ok=False)
            for source in (paths.register, paths.state, paths.retired, paths.report):
                if os.path.exists(source):
                    shutil.copy2(source, backup_dir)
                    backed_up.append(os.path.join(backup_dir, os.path.basename(source)))
            for source in (paths.state, paths.retired):
                if os.path.exists(source):
                    os.unlink(source)
            retired = []
            state = None
            result["backup"] = backed_up
        if retire_ids:
            raise Refused("--retire applies only to --mode reconcile.")

    elif mode == "reconcile":
        if not register_exists:
            raise Refused("There is no register to reconcile. Use --mode new.")
        existing, errors, _, _ = load_register(paths, requirements, allow_stale=True)
        if existing is None:
            raise Refused("The existing register is invalid and cannot be reconciled.", errors)
        if retire_ids:
            if not args.approve_retirement or not (args.retire_reason or "").strip():
                raise Refused(
                    "Retiring a gap moves it to gaps/retired-gaps.json, an extension of the agreed schema that needs the user's approval. "
                    "Ask the user, then pass --approve-retirement and --retire-reason."
                )
        changes = None if state is None else diff_requirements(state["requirements"], requirements)
        highest = highest_gap_number(existing, state, retired)
        errors, recon = check_reconciliation(existing, draft, highest, changes, set(parse_id_list(args.confirmed)), retire_ids)
        if errors:
            raise Refused("The reconciled draft breaks a safety rule; nothing was saved.", errors)
        result["reconciliation"] = recon
        result["requirement_changes"] = changes
        if retire_ids:
            retired = retire_gaps(paths, existing, retire_ids, args.retire_reason.strip())
    else:
        raise Refused(f"Unknown mode {mode!r}.")

    result["register_sha256"] = write_register(paths, requirements, draft, previous_bytes)
    state = write_state(paths, internals["input_bytes"], requirements, draft, retired)
    result["state"] = {"input_sha256": state["input_sha256"], "analysed_at": state["analysed_at"], "highest_gap_number": state["highest_gap_number"]}
    result["saved"] = {"register": paths.register, "state": paths.state}
    return result, finish(paths, result)


# ------------------------------------------------------------------------ triage actions


def require_current(paths):
    """Triage and updates only run against a register whose analysis matches the current input."""
    info, internals = inspect_project(paths)
    status = info["status"]
    if status == "UNCHANGED":
        return info, internals
    messages = {
        "NO_REGISTER": "No gap register exists. Run /sdlc-pipeline:ba-analyse-gaps first.",
        "REGISTER_INVALID": "The gap register is invalid; fix it before triage.",
        "CHANGED": "The atomic requirements changed since the last gap analysis. Run /sdlc-pipeline:ba-analyse-gaps to reconcile before triage.",
        "NO_STATE": "The analysis state file is missing. Run /sdlc-pipeline:ba-analyse-gaps to re-establish it before triage.",
    }
    raise Refused(messages.get(status, "The atomic requirements cannot be used: " + status), info.get("errors") or [])


def sorted_queue(register):
    eligible = [gap for gap in register if gap["status"] in ("open", "skipped")]
    return sorted(eligible, key=lambda gap: (PRIORITY_RANK[gap["priority"]], gap_number(gap["gap_id"])))


def counts(register):
    by_status = {status: sum(1 for gap in register if gap["status"] == status) for status in ("open", "skipped", "resolved")}
    by_priority = {p: sum(1 for gap in register if gap["priority"] == p) for p in PRIORITY_RANK}
    affected = {ref["requirement_id"] for gap in register for ref in gap["affected_requirements"]}
    return {
        "total": len(register),
        "open": by_status["open"],
        "skipped": by_status["skipped"],
        "resolved": by_status["resolved"],
        "by_priority": by_priority,
        "affected_requirements": len(affected),
    }


def cmd_list(paths, args):
    info, internals = require_current(paths)
    queue = sorted_queue(internals["register"])
    result = {
        "eligible_count": len(queue),
        "counts": counts(internals["register"]),
        "queue": queue,
        "register_path": paths.register,
        "report_path": paths.report,
    }
    return result, 0


def cmd_summary(paths, args):
    info, internals = inspect_project(paths)
    if internals["register"] is None:
        raise Refused(f"No usable register (status {info['status']}).", info.get("errors") or [])
    return {
        "status": info["status"],
        "counts": counts(internals["register"]),
        "requirement_count": info["requirement_count"],
        "register_path": paths.register,
        "report_path": paths.report,
        "state_path": paths.state,
    }, 0


def read_decision(source):
    try:
        if source == "-":
            text = sys.stdin.buffer.read().decode("utf-8-sig")
        else:
            with open(source, "r", encoding="utf-8-sig") as handle:
                text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise IOFailure(f"cannot read the decision text (UTF-8 expected): {exc}")
    text = text.strip()
    if not text:
        raise Refused("The decision text is empty.")
    return text


def apply_action(paths, args, action):
    info, internals = require_current(paths)
    register = json.loads(json.dumps(internals["register"]))  # deep copy; the loaded copy stays pristine
    gap_id = (args.gap_id or "").strip().upper()
    gap = next((g for g in register if g["gap_id"] == gap_id), None)
    if gap is None:
        raise Refused(f"{gap_id or 'No gap ID'} is not in the register.")
    before = gap["status"]
    changed = True

    if action == "resolve":
        if before == "resolved" and not args.revise:
            raise Refused(f"{gap_id} is already resolved. Use --revise to append a revised decision, or reopen it first.")
        gap["decisions_recorded"].append({"decision": read_decision(args.decision_file), "recorded_at": now_stamp()})
        gap["status"] = "resolved"
    elif action == "skip":
        if before == "resolved":
            raise Refused(f"{gap_id} is resolved and cannot be skipped. Reopen it first if it needs to be revisited.")
        changed = before != "skipped"
        gap["status"] = "skipped"
    elif action == "reopen":
        if before == "open":
            changed = False
        gap["status"] = "open"

    result = {"action": action, "gap_id": gap_id, "status_before": before, "status_after": gap["status"], "changed": changed}
    if not changed:
        result["note"] = "No change was needed; the register was not rewritten."
        return result, 0
    previous = read_bytes(paths.register)
    result["register_sha256"] = write_register(paths, internals["requirements"], register, previous)
    result["decision_count"] = len(gap["decisions_recorded"])
    result["counts"] = counts(register)
    return result, finish(paths, result)


def cmd_regenerate(paths, args):
    result = {}
    code = finish(paths, result)
    return result, code


# ------------------------------------------------------------------------------- CLI


def build_parser():
    parser = argparse.ArgumentParser(description="Safe persistence for the gap register.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, **kwargs):
        p = sub.add_parser(name, **kwargs)
        p.add_argument("--project-root", default=os.getcwd())
        return p

    add("inspect")
    save = add("save")
    save.add_argument("--draft", required=True)
    save.add_argument("--mode", required=True, choices=("new", "reconcile", "reset"))
    save.add_argument("--confirmed", default="")
    save.add_argument("--retire", default="")
    save.add_argument("--retire-reason", default="")
    save.add_argument("--approve-retirement", action="store_true")
    save.add_argument("--confirm-reset", action="store_true")
    add("list")
    resolve = add("resolve")
    resolve.add_argument("--gap-id", required=True)
    resolve.add_argument("--decision-file", required=True, help="File containing the confirmed decision text, or - for stdin.")
    resolve.add_argument("--revise", action="store_true")
    add("skip").add_argument("--gap-id", required=True)
    add("reopen").add_argument("--gap-id", required=True)
    add("summary")
    add("regenerate-report")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    paths = Paths(args.project_root)
    try:
        if args.command == "inspect":
            result, code = inspect_project(paths)[0], 0
        elif args.command == "save":
            result, code = cmd_save(paths, args)
        elif args.command == "list":
            result, code = cmd_list(paths, args)
        elif args.command in ("resolve", "skip", "reopen"):
            result, code = apply_action(paths, args, args.command)
        elif args.command == "summary":
            result, code = cmd_summary(paths, args)
        else:
            result, code = cmd_regenerate(paths, args)
        result = {"ok": code in (0, 3), **result}
    except Refused as exc:
        result, code = {"ok": False, "error": str(exc), "details": exc.details}, 1
    except IOFailure as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
