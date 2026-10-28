#!/usr/bin/env python3
"""Checkpoint and resume state for /sdlc-pipeline:ba-run (ba-requirements plugin).

One place for every read and write of <project root>/.ba-requirements/pipeline-state.json, so the
master command never hand-edits it: schema validation, crash-safe writes (temporary file, then
atomic replace), input and output fingerprints, change detection with downstream invalidation, and
the Critical/High story-generation gate. Standard library only. The phase artifacts (atomic
requirements, gap register, stories, report) are only ever read; the checkpoint never copies their
content.

Usage (all commands take --project-root, default: the current directory):

  inspect                       Read-only. NO_STATE | CORRUPT | INCOMPATIBLE | INCOMPLETE | COMPLETED,
                                the verdict of every operation (valid | invalid | not_completed) and
                                where a resume would continue.
  begin [--replace]             Start a new run. Refuses when a checkpoint exists unless --replace;
                                the old file is archived under .ba-requirements/history/, never deleted.
  resume                        Validate the completed operations, invalidate the first invalid one and
                                everything after it, and continue the run from there.
  start --operation OP [--sources P ...]
                                Persist OP as in_progress with its input fingerprints. Refuses when an
                                earlier operation is not completed or, for generate_stories, when any
                                Critical or High gap is unresolved.
  check-inputs --operation OP   Read-only unless an input changed: then OP is blocked (stale results
                                must not be applied) and the exit status is 1.
  complete --operation OP [--sources P ...] [--note TEXT]
                                Verify the operation's result and persist it as completed. For
                                gate_validation this evaluates the gate itself: unresolved Critical or
                                High gaps leave the operation blocked (exit 1, `blockers` listed).
  fail --operation OP --error TEXT [--detail TEXT]
  block --operation OP --reason TEXT [--detail TEXT]
  triage-event --gap-id G --action presented|resolved|revised|skipped|reopened
                                Persist one triage answer, skip or status change immediately.
  invalidate --from OP --reason TEXT
                                Reset OP and every later operation to pending.
  refresh                       For the individual phase commands: re-validate an unfinished run and
                                invalidate whatever those commands changed. Quiet when no run exists.
  gate                          Read-only. Evaluate the Critical/High story-generation gate.
  summary                       Run facts for the final or stopped summary, with live gap, story and
                                report figures.

Results are printed as JSON. Exit status: 0 = success, 1 = refused, blocked or invalid (see `error`),
2 = a file could not be read or written.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import sys
import tempfile
from datetime import datetime

SCHEMA_VERSION = "1.0"
STATE_DIRNAME = ".ba-requirements"
STATE_FILENAME = "pipeline-state.json"
RUN_STATUSES = ("in_progress", "completed", "blocked", "failed")
OP_STATUSES = ("pending", "in_progress", "completed", "blocked", "failed")
TRIAGE_ACTIONS = ("presented", "resolved", "revised", "skipped", "reopened")
STATUS_AFTER = {"resolved": "resolved", "revised": "resolved", "skipped": "skipped", "reopened": "open"}
GATE_PRIORITIES = ("Critical", "High")

OPERATIONS = (
    ("resolve_source", "Resolve and validate requirements source"),
    ("atomic_requirements", "Generate and validate atomic requirements"),
    ("gap_analysis", "Run gap analysis and validate the gap register"),
    ("gap_triage", "Interactive gap triage"),
    ("gate_validation", "Validate the Critical/High gap gate"),
    ("generate_stories", "Generate development stories"),
    ("enrich_stories", "Enrich stories using confirmed resolved-gap decisions"),
    ("phase3_report", "Generate/refresh the Phase 3 HTML report"),
    ("final_validation", "Final validation and completion summary"),
)
OP_NAMES = [name for name, _ in OPERATIONS]
OP_LABELS = dict(OPERATIONS)

# Fingerprints that are compared when an operation's completion is re-validated or its inputs are
# guarded, and the output fingerprints that must still match. Outputs that their own later phases
# legitimately rewrite (the register during triage, the stories during enrichment) are recorded for
# information only and checked through the live checks below instead.
INPUTS = {
    "resolve_source": ("sources",),
    "atomic_requirements": ("sources",),
    "gap_analysis": ("atomic_requirements",),
    "gap_triage": ("register_analysis",),
    "gate_validation": ("register_gate",),
    "generate_stories": ("atomic_requirements", "register_gate"),
    "enrich_stories": ("atomic_requirements", "register_decisions"),
    "phase3_report": ("register_full", "stories_state", "stories_section", "stories_detailed"),
    "final_validation": ("atomic_requirements", "register_full", "stories_state", "stories_section", "stories_detailed"),
}
RECORDED_OUTPUTS = {
    "atomic_requirements": ("atomic_requirements",),
    "gap_analysis": ("register_analysis", "gap_report_html"),
    "gap_triage": ("register_full",),
    "generate_stories": ("stories_state",),
    "enrich_stories": ("stories_state", "stories_section", "stories_detailed"),
    "phase3_report": ("report_html",),
}
ENFORCED_OUTPUTS = {
    "atomic_requirements": ("atomic_requirements",),
    "gap_analysis": ("register_analysis",),
    "phase3_report": ("report_html",),
}


def _load(filename, name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The same module names the other scripts use, so a shared interpreter never loads a script twice.
store = _load("gap-register-store.py", "ba_pipeline_gap_store")
sync = _load("sync-development-stories.py", "ba_pipeline_sync_stories")
common = sync.common


class Refused(Exception):
    """The request is not allowed or the data is invalid; nothing was changed."""

    def __init__(self, message, details=None, data=None):
        super().__init__(message)
        self.details = details or []
        self.data = data or {}


class IOFailure(Exception):
    """A file could not be read or written."""


# ----------------------------------------------------------------------------- basics


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_json(value):
    return sha256_bytes(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def to_json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


class Layout:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.dir = os.path.join(self.root, STATE_DIRNAME)
        self.state = os.path.join(self.dir, STATE_FILENAME)
        self.history = os.path.join(self.dir, "history")
        self.store = store.Paths(self.root)
        self.stories = common.Paths(self.root)
        self.gap_report = self.store.report
        self.report = self.stories.report


def atomic_write(path, payload):
    """Write to a temporary file in the same directory, flush it to disk, then replace the target."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("wb", dir=directory, prefix=".pipeline-state-", suffix=".tmp", delete=False)
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


def read_file(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def relative(layout, path):
    try:
        rel = os.path.relpath(path, layout.root)
    except ValueError:
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


# ------------------------------------------------------------------ checkpoint file


def new_operations():
    return [
        {
            "name": name, "label": label, "status": "pending", "attempts": 0,
            "started_at": None, "ended_at": None,
            "input_fingerprints": {}, "output_paths": [], "output_fingerprints": {},
            "warnings": [], "error": None,
        }
        for name, label in OPERATIONS
    ]


def new_state(layout, sources=None):
    stamp = now_stamp()
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "run-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3),
        "status": "in_progress",
        "project_root": layout.root,
        "source_files": list(sources or []),
        "current_operation": None,
        "last_completed_operation": None,
        "created_at": stamp,
        "updated_at": stamp,
        "operations": new_operations(),
        "triage": {"events": []},
        "invalidations": [],
        "resume_log": [],
    }


def validate_state(data):
    """Return a list of problems with a loaded checkpoint (empty = usable)."""
    if not isinstance(data, dict):
        return ["The checkpoint is not a JSON object."]
    problems = []
    for key, kind in (("run_id", str), ("status", str), ("source_files", list), ("operations", list), ("updated_at", str),
                      ("triage", dict), ("invalidations", list), ("resume_log", list)):
        if not isinstance(data.get(key), kind):
            problems.append(f"'{key}' is missing or not a {kind.__name__}.")
    if problems:
        return problems
    if not data["run_id"].strip():
        problems.append("'run_id' is empty.")
    if data["status"] not in RUN_STATUSES:
        problems.append(f"'status' is {data['status']!r}; expected one of {', '.join(RUN_STATUSES)}.")
    if not all(isinstance(p, str) for p in data["source_files"]):
        problems.append("'source_files' must hold paths.")
    for key in ("current_operation", "last_completed_operation"):
        value = data.get(key, "<absent>")
        if value != "<absent>" and value is not None and value not in OP_NAMES:
            problems.append(f"'{key}' names an unknown operation: {value!r}.")
        if value == "<absent>":
            problems.append(f"'{key}' is missing.")
    events = data["triage"].get("events")
    if not isinstance(events, list):
        problems.append("'triage.events' must be a list.")
    elif not all(isinstance(e, dict) and isinstance(e.get("gap_id"), str) and e.get("action") in TRIAGE_ACTIONS for e in events):
        problems.append("'triage.events' holds an entry without a gap_id and a known action.")
    if [op.get("name") if isinstance(op, dict) else None for op in data["operations"]] != OP_NAMES:
        problems.append("'operations' must list exactly the nine pipeline operations in order.")
        return problems
    for op in data["operations"]:
        where = f"operation {op['name']}"
        if op.get("status") not in OP_STATUSES:
            problems.append(f"{where}: status is {op.get('status')!r}.")
        for key in ("input_fingerprints", "output_fingerprints"):
            if not isinstance(op.get(key), dict):
                problems.append(f"{where}: '{key}' must be an object.")
        if not isinstance(op.get("output_paths"), list):
            problems.append(f"{where}: 'output_paths' must be a list.")
    if problems:
        return problems
    statuses = [op["status"] for op in data["operations"]]
    first_open = next((i for i, s in enumerate(statuses) if s != "completed"), len(statuses))
    if any(s == "completed" for s in statuses[first_open:]):
        problems.append("A completed operation follows an incomplete one.")
    if sum(1 for s in statuses if s == "in_progress") > 1:
        problems.append("More than one operation is in progress.")
    completed = [name for name, s in zip(OP_NAMES, statuses) if s == "completed"]
    expected_last = completed[-1] if completed else None
    if data["last_completed_operation"] != expected_last:
        problems.append(f"'last_completed_operation' is {data['last_completed_operation']!r} but the last completed operation is {expected_last!r}.")
    if data["status"] == "completed" and first_open != len(statuses):
        problems.append("The run is marked completed but not every operation is.")
    if data["status"] != "completed" and first_open == len(statuses):
        problems.append("Every operation is completed but the run is not marked completed.")
    return problems


def load_state(layout):
    """Return (kind, state, problems). kind: NO_STATE | CORRUPT | INCOMPATIBLE | OK."""
    if not os.path.isfile(layout.state):
        return "NO_STATE", None, []
    raw = read_file(layout.state)
    if raw is None:
        raise IOFailure(f"cannot read {layout.state}")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        return "CORRUPT", None, [f"The checkpoint is not valid JSON: {exc}."]
    if isinstance(data, dict) and isinstance(data.get("schema_version"), str):
        if data["schema_version"].split(".")[0] != SCHEMA_VERSION.split(".")[0]:
            return "INCOMPATIBLE", None, [f"The checkpoint uses schema {data['schema_version']}; this plugin reads schema {SCHEMA_VERSION}."]
    elif isinstance(data, dict):
        return "CORRUPT", None, ["'schema_version' is missing."]
    problems = validate_state(data)
    if problems:
        return "CORRUPT", None, problems
    return "OK", data, []


def save_state(layout, state):
    state["updated_at"] = now_stamp()
    problems = validate_state(state)
    if problems:  # a bug here must never reach the disk
        raise Refused("Refusing to write an inconsistent checkpoint.", problems)
    try:
        atomic_write(layout.state, to_json_bytes(state))
    except OSError as exc:
        raise IOFailure(f"cannot save {layout.state}: {exc}. The previous checkpoint is unchanged.")


def archive_existing(layout, label):
    """Copy the current checkpoint file to history/ before it is replaced. Never deletes."""
    if not os.path.isfile(layout.state):
        return None
    name = f"pipeline-state.{label}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    target = os.path.join(layout.history, name)
    try:
        os.makedirs(layout.history, exist_ok=True)
        shutil.copy2(layout.state, target)
    except OSError as exc:
        raise IOFailure(f"cannot archive the existing checkpoint: {exc}. Nothing was replaced.")
    return relative(layout, target)


def require_state(layout):
    kind, state, problems = load_state(layout)
    if kind != "OK":
        raise Refused(f"No usable checkpoint ({kind}). Start a new run.", problems, {"state_status": kind})
    return state


def op_of(state, name):
    if name not in OP_NAMES:
        raise Refused(f"{name!r} is not a pipeline operation. Use one of: {', '.join(OP_NAMES)}.")
    return state["operations"][OP_NAMES.index(name)]


def recompute(state):
    completed = [op["name"] for op in state["operations"] if op["status"] == "completed"]
    state["last_completed_operation"] = completed[-1] if completed else None


# --------------------------------------------------------------------- fingerprints


def source_fingerprint(path):
    """Hash of a source document outside its managed '# Development Stories' section.

    Phase 3 appends that section to the requirements document, so it must not count as a change to
    the requirements; trailing whitespace is ignored for the same reason.
    """
    raw = read_file(path)
    if raw is None:
        return "missing"
    try:
        doc = common.Document(path, raw)
        return common.sha256_text(doc.prefix.rstrip())
    except Exception:  # an undecodable file is still fingerprinted, by its bytes
        return "raw:" + sha256_bytes(raw)


def file_fingerprint(path):
    raw = read_file(path)
    return None if raw is None else sha256_bytes(raw)


def existence_fingerprint(path):
    raw = read_file(path)
    return "present" if raw else None


def load_register_data(layout):
    raw = read_file(layout.store.register)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, list) or not all(isinstance(g, dict) for g in data):
        return None
    return data


def latest_decision_hash(gap):
    decisions = gap.get("decisions_recorded")
    if not isinstance(decisions, list) or not decisions or not isinstance(decisions[-1], dict):
        return None
    last = decisions[-1]
    return sha256_json([last.get("recorded_at"), last.get("decision")])


def story_target(layout):
    """The recorded Development Stories document, or None."""
    state, status, _ = common.load_state(layout.stories)
    if state is None:
        return None
    return common.resolve_target(layout.stories, state["target_document"])


def fingerprint(layout, state, kind):
    """One named fingerprint of the current files. None means the artifact is absent or unreadable."""
    if kind == "sources":
        return {path: source_fingerprint(path) for path in state["source_files"]}
    if kind == "atomic_requirements":
        return file_fingerprint(layout.store.requirements)
    if kind == "register_full":
        return file_fingerprint(layout.store.register)
    if kind == "register_analysis":
        register = load_register_data(layout)
        if register is None:
            return None
        return sha256_json([{k: v for k, v in gap.items() if k not in ("status", "decisions_recorded")} for gap in register])
    if kind == "register_gate":
        register = load_register_data(layout)
        if register is None:
            return None
        rows = [
            [g.get("gap_id"), g.get("priority"), g.get("status"), latest_decision_hash(g)]
            for g in register if g.get("priority") in GATE_PRIORITIES
        ]
        return sha256_json(sorted(rows, key=lambda r: str(r[0])))
    if kind == "register_decisions":
        register = load_register_data(layout)
        if register is None:
            return None
        rows = [[g.get("gap_id"), latest_decision_hash(g)] for g in register if g.get("status") == "resolved"]
        return sha256_json(sorted(rows, key=lambda r: str(r[0])))
    if kind == "stories_state":
        return file_fingerprint(layout.stories.state)
    if kind == "stories_section":
        target = story_target(layout)
        if not target or not os.path.isfile(target):
            return None
        try:
            return common.read_document(target).section_hash
        except Exception:
            return None
    if kind == "stories_detailed":
        # The authoritative detailed stories: any change to the single file stories/detailed_stories.md counts.
        return file_fingerprint(layout.stories.detailed_file)
    if kind == "gap_report_html":
        return existence_fingerprint(layout.gap_report)
    if kind == "report_html":
        return existence_fingerprint(layout.report)
    raise ValueError(kind)


def fingerprints(layout, state, kinds):
    return {kind: fingerprint(layout, state, kind) for kind in kinds}


def describe_change(kind, before, after):
    if kind == "sources":
        before, after = before or {}, after or {}
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        return "source file changed or missing: " + ", ".join(changed)
    if after is None:
        return f"{kind} is now missing or unreadable"
    return f"{kind} changed"


def changed_inputs(layout, state, op):
    recorded = op["input_fingerprints"]
    changes = []
    for kind in INPUTS[op["name"]]:
        if kind not in recorded:
            changes.append(f"{kind} was not recorded")
            continue
        now = fingerprint(layout, state, kind)
        if now != recorded[kind]:
            changes.append(describe_change(kind, recorded[kind], now))
    return changes


# ------------------------------------------------------------------------ live checks


def gate_status(layout):
    """Evaluate the Critical/High gate from the gap store. Returns a dict (never raises)."""
    try:
        _, internals = store.require_current(layout.store)
    except store.Refused as exc:
        return {"passed": False, "verifiable": False, "blockers": [], "error": str(exc), "details": exc.details}
    except store.IOFailure as exc:
        return {"passed": False, "verifiable": False, "blockers": [], "error": str(exc), "details": []}
    blockers = [
        {"gap_id": g["gap_id"], "priority": g["priority"], "status": g["status"], "gap_definition": g["gap_definition"]}
        for g in store.sorted_queue(internals["register"]) if g["priority"] in GATE_PRIORITIES
    ]
    return {"passed": not blockers, "verifiable": True, "blockers": blockers, "error": None, "details": []}


def check_sources(layout, state):
    problems = []
    if not state["source_files"]:
        return ["No source files are recorded."]
    for path in state["source_files"]:
        if not os.path.isfile(path):
            problems.append(f"source file not found: {path}")
        elif not path.lower().endswith(".md"):
            problems.append(f"source file is not Markdown: {path}")
    return problems


def check_atomic(layout, state):
    status, errors, _, _ = common.load_atomic(layout.stories)
    return [] if status is None else [f"atomic requirements {status}: {e}" for e in (errors or [status])[:5]]


def check_register(layout, state, warnings):
    info, _ = store.inspect_project(layout.store)
    problems = []
    if info["status"] != "UNCHANGED":
        problems.append(f"gap register status is {info['status']}, expected UNCHANGED")
        problems.extend(str(e) for e in (info.get("errors") or [])[:5])
    elif not os.path.isfile(layout.gap_report):
        warnings.append("gaps/gap-analysis.html is missing; run gap-register-store.py regenerate-report (the JSON register is intact)")
    return problems


def check_gate(layout, state):
    gate = gate_status(layout)
    if gate["passed"]:
        return []
    if not gate["verifiable"]:
        return [f"the story-generation gate cannot be verified: {gate['error']}"]
    return [f"{b['gap_id']} ({b['priority']}) is {b['status']}" for b in gate["blockers"]]


def stories_context(layout):
    ctx = sync.load_context(layout.stories)
    sync.require_ready(ctx)
    if ctx.state is None or ctx.doc.section_state != "present":
        raise common.Refused("No synchronised stories exist yet.")
    return ctx


def check_stories(layout, state, need_decisions_applied):
    try:
        ctx = stories_context(layout)
    except (common.Refused, common.IOFailure) as exc:
        return [str(exc)] + [str(d) for d in getattr(exc, "details", [])[:5]]
    problems = []
    errors, _, _ = sync.validator.validate_story_set(ctx.doc.stories, ctx.doc.problems, ctx.detailed, ctx.requirements, ctx.state, ctx.legacy_files)
    problems.extend(errors[:5])
    uncovered = sync.uncovered_requirements(ctx)
    if uncovered:
        problems.append("requirements without a story or an explanation: " + ", ".join(uncovered))
    if need_decisions_applied:
        pending = sync.pending_decisions(ctx)
        if pending:
            problems.append("resolved decisions not yet reflected in the stories: " + ", ".join(sorted({p["gap_id"] for p in pending})))
    return problems


def check_report(layout, state):
    return [] if existence_fingerprint(layout.report) else ["report/phase3-report.html is missing or empty"]


def live_problems(layout, state, name, warnings):
    """What is wrong with the operation's result right now. Empty = the result is sound."""
    if name == "resolve_source":
        return check_sources(layout, state)
    if name == "atomic_requirements":
        return check_atomic(layout, state)
    if name in ("gap_analysis", "gap_triage"):
        return check_register(layout, state, warnings)
    if name == "gate_validation":
        return check_gate(layout, state)
    if name == "generate_stories":
        return check_gate(layout, state) or check_stories(layout, state, need_decisions_applied=False)
    if name == "enrich_stories":
        return check_stories(layout, state, need_decisions_applied=True)
    if name == "phase3_report":
        return check_report(layout, state)
    if name == "final_validation":
        problems = []
        for earlier in OP_NAMES[:-1]:
            problems.extend(live_problems(layout, state, earlier, warnings))
        return problems
    raise ValueError(name)


def evaluate_completed(layout, state, op):
    """Problems that invalidate a completed operation (inputs, enforced outputs, live checks), plus warnings."""
    problems, warnings = [], []
    problems.extend(changed_inputs(layout, state, op))
    for kind in ENFORCED_OUTPUTS.get(op["name"], ()):
        recorded = op["output_fingerprints"].get(kind)
        now = fingerprint(layout, state, kind)
        if recorded != now:
            problems.append(f"output {kind} " + ("is missing" if now is None else "changed since it was recorded"))
    problems.extend(live_problems(layout, state, op["name"], warnings))
    return problems, warnings


def evaluate_run(layout, state):
    """Verdict of every operation. Returns (rows, first index to (re)run, warnings)."""
    rows, run_from, warnings = [], None, []
    for index, op in enumerate(state["operations"]):
        row = {"name": op["name"], "recorded_status": op["status"]}
        if op["status"] != "completed" or run_from is not None:
            if op["status"] == "completed":  # valid on its own, but it follows an invalid operation
                row.update(verdict="invalid", problems=["follows an operation that must be rerun"])
            else:
                row.update(verdict="not_completed", problems=[])
            if run_from is None:
                run_from = index
        else:
            problems, op_warnings = evaluate_completed(layout, state, op)
            warnings.extend(f"{op['name']}: {w}" for w in op_warnings)
            row.update(verdict="invalid" if problems else "valid", problems=problems)
            if problems:
                run_from = index
        rows.append(row)
    return rows, run_from, warnings


def invalidate_from(state, index, reason):
    stamp = now_stamp()
    names, errors = [], {}
    for op in state["operations"][index:]:
        if op["status"] != "pending":
            names.append(op["name"])
        if op["error"]:
            errors[op["name"]] = op["error"]
        op.update(status="pending", started_at=None, ended_at=None, input_fingerprints={}, output_paths=[],
                  output_fingerprints={}, warnings=[], error=None)
    state["current_operation"] = None
    state["status"] = "in_progress"
    recompute(state)
    if names:
        state["invalidations"].append({"operations": names, "reason": reason, "at": stamp, **({"errors": errors} if errors else {})})
    return names


# --------------------------------------------------------------------------- triage


def triage_summary(state):
    events = state["triage"]["events"]
    by_gap = {}
    for event in events:
        by_gap.setdefault(event["gap_id"], []).append(event)
    last = {gap_id: items[-1] for gap_id, items in by_gap.items()}
    return {
        "events": len(events),
        "presented": len(by_gap),
        "resolved": sum(1 for e in last.values() if e["status_after"] == "resolved"),
        "skipped": sum(1 for e in last.values() if e["status_after"] == "skipped"),
        "reopened": sum(1 for e in last.values() if e["status_after"] == "open" and e["action"] == "reopened"),
        "last_event": events[-1] if events else None,
    }


def triage_drift(layout, state):
    """Gaps whose register status differs from the last recorded triage event (the register wins)."""
    register = load_register_data(layout)
    if register is None:
        return []
    status = {g.get("gap_id"): g.get("status") for g in register}
    last = {}
    for event in state["triage"]["events"]:
        if event.get("status_after"):
            last[event["gap_id"]] = event["status_after"]
    return sorted(
        f"{gap_id}: checkpoint says {recorded}, register says {status.get(gap_id)}"
        for gap_id, recorded in last.items() if gap_id in status and status[gap_id] != recorded
    )


# ------------------------------------------------------------------------- commands


def run_view(state):
    return {
        "run_id": state["run_id"], "run_status": state["status"], "source_files": state["source_files"],
        "current_operation": state["current_operation"], "last_completed_operation": state["last_completed_operation"],
        "updated_at": state["updated_at"], "checkpoint_path": STATE_DIRNAME + "/" + STATE_FILENAME,
    }


def cmd_inspect(layout, args):
    kind, state, problems = load_state(layout)
    if kind == "NO_STATE":
        return {"state_status": "NO_STATE", "recommended_action": "start_new_run"}, 0
    if kind != "OK":
        return {
            "state_status": kind, "errors": problems, "recommended_action": "offer_fresh_run",
            "note": "The checkpoint was not changed. A fresh run archives it under .ba-requirements/history/; nothing is assumed complete.",
            "checkpoint_path": STATE_DIRNAME + "/" + STATE_FILENAME,
        }, 0
    rows, run_from, warnings = evaluate_run(layout, state)
    result = {**run_view(state), "operations": rows, "warnings": warnings, "triage": triage_summary(state)}
    drift = triage_drift(layout, state)
    if drift:
        result["triage_drift"] = drift
    if state["status"] == "completed":
        result.update(
            state_status="COMPLETED", recommended_action="offer_new_run",
            artifacts_still_valid=run_from is None,
            artifact_problems=[p for row in rows for p in row["problems"]],
        )
    else:
        names = [row["name"] for row in rows]
        result.update(
            state_status="INCOMPLETE", recommended_action="ask_resume_or_new_run",
            resume_from=names[run_from] if run_from is not None else None,
            reusable=[row["name"] for row in rows if row["verdict"] == "valid"],
            would_invalidate=[row["name"] for row in rows if row["verdict"] == "invalid"],
        )
    return result, 0


def cmd_begin(layout, args):
    kind, state, problems = load_state(layout)
    archived = None
    if kind != "NO_STATE":
        if not args.replace:
            raise Refused(
                f"A checkpoint already exists ({kind}). Ask the user whether to resume it or start a new run, then pass --replace for a new run.",
                problems, {"state_status": kind},
            )
        archived = archive_existing(layout, state["run_id"] if state else kind.lower())
    fresh = new_state(layout)
    save_state(layout, fresh)
    return {**run_view(fresh), "archived_previous": archived}, 0


def cmd_resume(layout, args):
    state = require_state(layout)
    if state["status"] == "completed":
        raise Refused("The previous run is completed. Start a new run; a completed run is never reused as a new execution.")
    rows, run_from, warnings = evaluate_run(layout, state)
    reused = [r["name"] for r in rows if r["verdict"] == "valid"]
    rerun, reasons = [], []
    for index, row in enumerate(rows):
        if run_from is not None and index >= run_from and row["recorded_status"] != "pending":
            rerun.append(row["name"])
            if row["problems"]:
                reasons.extend(f"{row['name']}: {p}" for p in row["problems"])
    if run_from is not None and state["operations"][run_from]["status"] == "completed":
        invalidate_from(state, run_from, "resume validation: " + "; ".join(reasons))
    # An interrupted, failed or blocked operation keeps its recorded error until it is started again;
    # everything after it is already pending.
    state["status"] = "in_progress"
    state["resume_log"].append({
        "at": now_stamp(), "reused": reused, "rerun": rerun,
        "resume_from": OP_NAMES[run_from] if run_from is not None else None,
    })
    save_state(layout, state)
    return {
        **run_view(state), "resume_from": OP_NAMES[run_from] if run_from is not None else None,
        "reused": reused, "rerun": rerun, "reasons": reasons, "warnings": warnings,
        "operations": rows, "triage": triage_summary(state),
    }, 0


def parse_sources(values):
    return [os.path.abspath(p.strip()) for p in values or [] if p.strip()]


def mark_blocked(state, op, error, status="blocked"):
    op.update(status=status, ended_at=now_stamp(), error=error)
    state["current_operation"] = op["name"]
    state["status"] = status


def cmd_start(layout, args):
    state = require_state(layout)
    if state["status"] == "completed":
        raise Refused("The run is completed. Start a new run.")
    op = op_of(state, args.operation)
    index = OP_NAMES.index(op["name"])
    if op["status"] == "completed":
        raise Refused(f"{op['name']} is already completed and its result is still recorded as valid; it is not repeated. Use `invalidate` first if it must be rerun.")
    earlier = [o["name"] for o in state["operations"][:index] if o["status"] != "completed"]
    if earlier:
        raise Refused(f"{op['name']} cannot start: {', '.join(earlier)} must be completed first.", [], {"incomplete_before": earlier})
    if op["name"] == "resolve_source":
        # The sources are only candidates until `complete` records the confirmed set.
        state["source_files"] = parse_sources(args.sources) or state["source_files"]
    if op["name"] == "generate_stories":
        gate = gate_status(layout)
        if not gate["passed"]:
            gate_op = op_of(state, "gate_validation")
            invalidate_from(state, OP_NAMES.index("gate_validation"), "story-generation gate does not pass")
            mark_blocked(state, gate_op, {
                "message": "Story generation is blocked: " + ("the gate cannot be verified." if not gate["verifiable"] else "unresolved Critical or High gaps."),
                "blockers": [f"{b['gap_id']} {b['priority']} {b['status']}" for b in gate["blockers"]],
            })
            save_state(layout, state)
            raise Refused(
                "Story generation is blocked: every Critical and High gap must be resolved first." if gate["verifiable"] else "The story-generation gate cannot be verified: " + str(gate["error"]),
                gate["details"], {"gate": gate, "blocked_operation": "gate_validation"},
            )
    if index and op["name"] != "resolve_source":
        stale = [c for o in state["operations"][:index] for c in changed_inputs(layout, state, o)]
        if stale:
            raise Refused(
                "An input of a completed operation changed since it ran. Run `resume` (or `refresh`) to invalidate the affected operations before continuing.",
                stale, {"stale": True},
            )
    op.update(
        status="in_progress", started_at=now_stamp(), ended_at=None, error=None, warnings=[],
        attempts=op["attempts"] + 1, input_fingerprints=fingerprints(layout, state, INPUTS[op["name"]]),
        output_paths=[], output_fingerprints={},
    )
    state["current_operation"] = op["name"]
    state["status"] = "in_progress"
    save_state(layout, state)
    return {"operation": op["name"], "status": "in_progress", "attempt": op["attempts"], "run_id": state["run_id"], "input_fingerprints": op["input_fingerprints"]}, 0


def guard(layout, state, op):
    """Block the operation when an input changed while it ran. Returns the list of changes."""
    changes = changed_inputs(layout, state, op)
    if changes:
        sources = any(c.startswith("source file") for c in changes)
        message = ("A source file changed during execution." if sources else "An upstream artifact changed during execution.") + " The results of this operation were not applied."
        mark_blocked(state, op, {"message": message, "changes": changes, "code": "INPUTS_CHANGED"})
        save_state(layout, state)
        raise Refused(
            message + " Ask the user whether to restart from source analysis (`invalidate --from resolve_source`).",
            changes, {"code": "INPUTS_CHANGED", "operation": op["name"], "restart_from": "resolve_source"},
        )
    return changes


def cmd_check_inputs(layout, args):
    state = require_state(layout)
    op = op_of(state, args.operation)
    if op["status"] != "in_progress":
        raise Refused(f"{op['name']} is {op['status']}, not in_progress; start it first.")
    guard(layout, state, op)
    return {"operation": op["name"], "inputs_unchanged": True}, 0


def output_paths(layout, op_name):
    paths = {
        "atomic_requirements": [layout.store.requirements],
        "gap_analysis": [layout.store.register, layout.gap_report, layout.store.state],
        "gap_triage": [layout.store.register],
        "phase3_report": [layout.report],
    }.get(op_name, [])
    if op_name in ("generate_stories", "enrich_stories"):
        paths = [layout.stories.state, layout.stories.detailed_file]
        target = story_target(layout)
        if target:
            paths.append(target)
    return [relative(layout, p) for p in paths]


def cmd_complete(layout, args):
    state = require_state(layout)
    op = op_of(state, args.operation)
    if op["status"] != "in_progress":
        raise Refused(f"{op['name']} is {op['status']}; it must be started before it can be completed.")
    if op["name"] == "resolve_source":
        sources = parse_sources(args.sources)
        if not sources:
            raise Refused("resolve_source needs --sources: the confirmed absolute Markdown source paths.")
        state["source_files"] = sources
        op["input_fingerprints"] = fingerprints(layout, state, INPUTS[op["name"]])
    else:
        guard(layout, state, op)
        if op["name"] == "gate_validation":
            gate_complete(layout, state, op)
    warnings = []
    problems = live_problems(layout, state, op["name"], warnings)
    if problems:
        error = {"message": f"{op['name']} did not produce a valid result.", "problems": problems[:10]}
        op.update(status="failed", ended_at=now_stamp(), error=error)
        state["current_operation"], state["status"] = op["name"], "failed"
        save_state(layout, state)
        raise Refused(error["message"], problems, {"operation": op["name"], "recorded_status": "failed"})
    op.update(
        status="completed", ended_at=now_stamp(), error=None, warnings=warnings,
        output_paths=output_paths(layout, op["name"]),
        output_fingerprints=fingerprints(layout, state, RECORDED_OUTPUTS.get(op["name"], ())),
    )
    if args.note:
        op["note"] = args.note
    state["current_operation"] = None
    recompute(state)
    if op["name"] == "final_validation":
        state["status"] = "completed"
    save_state(layout, state)
    result = {
        "operation": op["name"], "status": "completed", "run_id": state["run_id"], "run_status": state["status"],
        "last_completed_operation": state["last_completed_operation"], "warnings": warnings,
    }
    return result, 0


def gate_complete(layout, state, op):
    """The gate operation does not fail: unresolved Critical/High gaps leave it blocked, which is resumable."""
    gate = gate_status(layout)
    if gate["passed"]:
        return None
    message = ("Unresolved Critical or High gaps block story generation." if gate["verifiable"]
               else "The story-generation gate cannot be verified: " + str(gate["error"]))
    mark_blocked(state, op, {"message": message, "blockers": [f"{b['gap_id']} {b['priority']} {b['status']}" for b in gate["blockers"]]})
    save_state(layout, state)
    raise Refused(message, gate["details"], {"operation": op["name"], "recorded_status": "blocked", "blockers": gate["blockers"], "gate": gate})


def cmd_fail(layout, args):
    state = require_state(layout)
    op = op_of(state, args.operation)
    if op["status"] == "completed":
        raise Refused(f"{op['name']} is completed; use `invalidate` to reset it.")
    op.update(status="failed", ended_at=now_stamp(), error={"message": args.error, **({"detail": args.detail} if args.detail else {})})
    state["current_operation"], state["status"] = op["name"], "failed"
    save_state(layout, state)
    return {"operation": op["name"], "status": "failed", "run_status": "failed", "error": args.error}, 0


def cmd_block(layout, args):
    state = require_state(layout)
    op = op_of(state, args.operation)
    if op["status"] == "completed":
        raise Refused(f"{op['name']} is completed; use `invalidate` to reset it.")
    mark_blocked(state, op, {"message": args.reason, **({"detail": args.detail} if args.detail else {})})
    save_state(layout, state)
    return {"operation": op["name"], "status": "blocked", "run_status": "blocked", "reason": args.reason}, 0


def cmd_triage_event(layout, args):
    state = require_state(layout)
    if state["status"] == "completed":
        raise Refused("The run is completed; triage answers are recorded in the gap register only.")
    index = OP_NAMES.index("gap_triage")
    if any(o["status"] != "completed" for o in state["operations"][:index]):
        raise Refused("Triage events are only recorded once gap analysis is completed.")
    gap_id = args.gap_id.strip().upper()
    register = load_register_data(layout)
    gap = next((g for g in register or [] if g.get("gap_id") == gap_id), None)
    if gap is None:
        raise Refused(f"{gap_id} is not in the gap register.")
    expected = STATUS_AFTER.get(args.action)
    if expected and gap.get("status") != expected:
        raise Refused(
            f"The register shows {gap_id} as {gap.get('status')}, not {expected}. Save the answer through gap-register-store.py first, then record the event.",
        )
    event = {
        "seq": len(state["triage"]["events"]) + 1, "gap_id": gap_id, "action": args.action,
        "status_after": gap.get("status"), "priority": gap.get("priority"),
        "decisions_in_register": len(gap.get("decisions_recorded") or []),
        "operation": state["current_operation"] or state["last_completed_operation"], "recorded_at": now_stamp(),
    }
    state["triage"]["events"].append(event)
    save_state(layout, state)
    return {"recorded": event, "triage": triage_summary(state)}, 0


def cmd_invalidate(layout, args):
    state = require_state(layout)
    if state["status"] == "completed":
        raise Refused("The run is completed. Start a new run.")
    op_of(state, args.from_operation)
    names = invalidate_from(state, OP_NAMES.index(args.from_operation), args.reason)
    save_state(layout, state)
    return {**run_view(state), "invalidated": names, "reason": args.reason}, 0


def cmd_refresh(layout, args):
    kind, state, problems = load_state(layout)
    if kind == "NO_STATE":
        return {"refreshed": False, "state_status": "NO_STATE"}, 0
    if kind != "OK":
        return {"refreshed": False, "state_status": kind, "errors": problems,
                "note": "The checkpoint is unusable; the next /sdlc-pipeline:ba-run will explain and offer a fresh run."}, 0
    if state["status"] == "completed":
        return {"refreshed": False, "state_status": "COMPLETED", "note": "The last run is completed; a later run starts new."}, 0
    rows, run_from, _ = evaluate_run(layout, state)
    invalid = next((i for i, row in enumerate(rows) if row["verdict"] == "invalid" and row["recorded_status"] == "completed"), None)
    if invalid is None:
        return {"refreshed": True, "invalidated": [], **run_view(state)}, 0
    reasons = "; ".join(p for row in rows if row["verdict"] == "invalid" for p in row["problems"])
    names = invalidate_from(state, invalid, "changed outside the pipeline: " + reasons)
    save_state(layout, state)
    return {"refreshed": True, "invalidated": names, "reasons": reasons, **run_view(state)}, 0


def cmd_gate(layout, args):
    gate = gate_status(layout)
    return gate, 0


def cmd_summary(layout, args):
    state = require_state(layout)
    ops = state["operations"]
    reused = sorted({n for entry in state["resume_log"] for n in entry["reused"]}, key=OP_NAMES.index)
    rerun = sorted(
        {n for entry in state["resume_log"] for n in entry["rerun"]} | {o["name"] for o in ops if o["attempts"] > 1},
        key=OP_NAMES.index,
    )
    result = {
        **run_view(state),
        "operations": [{"name": o["name"], "status": o["status"], "attempts": o["attempts"], "error": o["error"]} for o in ops],
        "resumed_skipped_operations": reused, "operations_rerun": rerun, "resumes": len(state["resume_log"]),
        "invalidations": state["invalidations"], "triage": triage_summary(state),
    }
    info, internals = store.inspect_project(layout.store)
    if internals["register"] is not None:
        register = internals["register"]
        unresolved = {p: {s: sum(1 for g in register if g["priority"] == p and g["status"] == s) for s in ("open", "skipped")} for p in store.PRIORITY_RANK}
        result["gaps"] = {"counts": store.counts(register), "unresolved_by_priority": unresolved}
    else:
        result["gaps"] = None
    result["stories"] = None
    try:
        ctx = sync.load_context(layout.stories)
        sync.require_ready(ctx)
        if ctx.state is not None:
            covered = {r for entry in ctx.state["stories"] for r in entry.get("source_requirement_ids", [])}
            result["stories"] = {
                "in_document": len(ctx.doc.stories), "detailed_stories": len(ctx.detailed.stories),
                "requirements_covered": len(covered), "requirements_analysed": len(ctx.requirements),
            }
    except (common.Refused, common.IOFailure):
        pass
    exists = bool(existence_fingerprint(layout.report))
    stale = exists and state["operations"][OP_NAMES.index("phase3_report")]["status"] != "completed"
    result["report"] = {"path": relative(layout, layout.report), "exists": exists, "status": "GENERATED" if exists and not stale else "STALE" if exists else "UNAVAILABLE"}
    return result, 0


# ------------------------------------------------------------------------------- CLI


def build_parser():
    parser = argparse.ArgumentParser(description="Checkpoint and resume state for /sdlc-pipeline:ba-run.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name, **kwargs):
        p = sub.add_parser(name, **kwargs)
        p.add_argument("--project-root", default=os.getcwd())
        return p

    add("inspect")
    add("begin").add_argument("--replace", action="store_true")
    add("resume")
    start = add("start")
    start.add_argument("--operation", required=True)
    start.add_argument("--sources", nargs="*", default=[])
    add("check-inputs").add_argument("--operation", required=True)
    complete = add("complete")
    complete.add_argument("--operation", required=True)
    complete.add_argument("--sources", nargs="*", default=[])
    complete.add_argument("--note", default="")
    fail = add("fail")
    fail.add_argument("--operation", required=True)
    fail.add_argument("--error", required=True)
    fail.add_argument("--detail", default="")
    block = add("block")
    block.add_argument("--operation", required=True)
    block.add_argument("--reason", required=True)
    block.add_argument("--detail", default="")
    triage = add("triage-event")
    triage.add_argument("--gap-id", required=True)
    triage.add_argument("--action", required=True, choices=TRIAGE_ACTIONS)
    invalidate = add("invalidate")
    invalidate.add_argument("--from", dest="from_operation", required=True)
    invalidate.add_argument("--reason", required=True)
    add("refresh")
    add("gate")
    add("summary")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    layout = Layout(args.project_root)
    handlers = {
        "inspect": cmd_inspect, "begin": cmd_begin, "resume": cmd_resume, "start": cmd_start,
        "check-inputs": cmd_check_inputs, "complete": cmd_complete, "fail": cmd_fail, "block": cmd_block,
        "triage-event": cmd_triage_event, "invalidate": cmd_invalidate, "refresh": cmd_refresh,
        "gate": cmd_gate, "summary": cmd_summary,
    }
    try:
        result, code = handlers[args.command](layout, args)
        result = {"ok": True, **result}
    except Refused as exc:
        result, code = {"ok": False, "error": str(exc), "details": exc.details, **exc.data}, 1
    except IOFailure as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
    except (KeyError, TypeError, ValueError, AttributeError) as exc:  # a checkpoint shape the validation missed
        result, code = {"ok": False, "error": f"Unexpected error ({type(exc).__name__}: {exc}). Nothing was changed."}, 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
