#!/usr/bin/env python3
"""Validate a gap register JSON file (ba-requirements plugin, Phase 2).

Structural checks mirror schemas/gap-register.schema.json. Semantic checks cover
what a schema cannot express: unique gap IDs, valid and current requirement
references, decision/status consistency and duplicate gap definitions.

The standard library only. Nothing is repaired or guessed; every problem is
reported with the gap it belongs to.

Usage:
    validate-gap-register.py <gaps.json> [--requirements <atomic_requirements.json>]
                             [--structure-only] [--allow-stale]

By default the requirements file is <project>/atomic_requirements/atomic_requirements.json,
found relative to the gap register (gaps/gaps.json -> ../atomic_requirements/...).

--allow-stale   Report requirement references that no longer match the current
                requirements (unknown ID, changed description) as warnings
                instead of errors. Only the reconciliation workflow uses this,
                to read an existing register against changed requirements.

Exit status: 0 = valid, 1 = validation failed (including invalid JSON syntax in the
register), 2 = a file could not be read or the requirements file is unusable.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

GAP_ID_PATTERN = re.compile(r"^GAP-[0-9]{3,}$")
REQ_ID_PATTERN = re.compile(r"^REQ-[0-9]{3,}$")
PRIORITIES = ("Critical", "High", "Medium", "Low")
STATUSES = ("open", "skipped", "resolved")
GAP_KEYS = ("gap_id", "priority", "status", "gap_definition", "decisions_recorded", "affected_requirements")
DECISION_KEYS = ("decision", "recorded_at")
REF_KEYS = ("requirement_id", "description")
MAX_REPORTED = 40

TIMESTAMP_PATTERN = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?(Z|[+-]\d{2}(?::?\d{2})?)?$"
)


class InputError(Exception):
    """A file could not be read or does not have the expected shape (exit 2)."""


class JsonSyntaxError(InputError):
    """A file was read but is not valid JSON (exit 1, like the Phase 1 validator)."""


def parse_timestamp(value):
    """Return a datetime for an ISO 8601 date-time string, or None if it is not one."""
    if not isinstance(value, str):
        return None
    match = TIMESTAMP_PATTERN.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    tzinfo = None
    if zone:
        if zone == "Z":
            tzinfo = timezone.utc
        else:
            digits = zone[1:].replace(":", "")
            offset_hours = int(digits[:2])
            offset_minutes = int(digits[2:4]) if len(digits) > 2 else 0
            if offset_hours > 23 or offset_minutes > 59:
                return None
            delta = timedelta(hours=offset_hours, minutes=offset_minutes)
            tzinfo = timezone(delta if zone[0] == "+" else -delta)
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second or 0), micro, tzinfo=tzinfo
        )
    except ValueError:
        return None


def read_json(path):
    """Parse a JSON file. Returns (data, duplicate_keys). Raises InputError."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}")

    duplicate_keys = []

    def pairs_hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                duplicate_keys.append(key)
            seen.add(key)
        return dict(pairs)

    try:
        return json.loads(text, object_pairs_hook=pairs_hook), duplicate_keys
    except json.JSONDecodeError as exc:
        raise JsonSyntaxError(f"invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}.")


def load_requirements(path):
    """Return {requirement_id: description} from the Phase 1 file. Raises InputError."""
    data, _ = read_json(path)
    if not isinstance(data, list) or not data:
        raise InputError(
            f"{path} must be a non-empty array of atomic requirements. "
            "Run /sdlc-pipeline:ba-start-analysis or run scripts/validate-atomic-requirements.py on it."
        )
    requirements = {}
    for position, item in enumerate(data, start=1):
        if not (
            isinstance(item, dict)
            and isinstance(item.get("requirement_id"), str)
            and isinstance(item.get("description"), str)
            and isinstance(item.get("title"), str)
        ):
            raise InputError(
                f"{path}: item {position} is not a valid atomic requirement "
                "(requirement_id, title and description are required strings). "
                "Run scripts/validate-atomic-requirements.py on it."
            )
        requirements[item["requirement_id"]] = item["description"]
    return requirements


def validate_structure(data, duplicate_keys):
    errors = []
    if duplicate_keys:
        errors.append(
            f"An object repeats a property name ({', '.join(sorted(set(duplicate_keys)))}); each property may appear once."
        )
    if not isinstance(data, list):
        errors.append(
            f"The root value must be an array of gap objects, found {type(data).__name__}. "
            "Do not wrap the array in another object."
        )
        return errors

    for position, gap in enumerate(data, start=1):
        label = f"Gap {position}"
        if not isinstance(gap, dict):
            errors.append(f"{label}: must be an object, found {type(gap).__name__}.")
            continue
        if isinstance(gap.get("gap_id"), str) and gap["gap_id"].strip():
            label = f"Gap {position} ({gap['gap_id']})"

        missing = [key for key in GAP_KEYS if key not in gap]
        extra = [key for key in gap if key not in GAP_KEYS]
        if missing:
            errors.append(f"{label}: missing required property: {', '.join(missing)}.")
        if extra:
            errors.append(f"{label}: unexpected property: {', '.join(extra)}. Only {', '.join(GAP_KEYS)} are allowed.")

        gap_id = gap.get("gap_id")
        if "gap_id" in gap:
            if not isinstance(gap_id, str):
                errors.append(f"{label}: 'gap_id' must be a string, found {type(gap_id).__name__}.")
            elif not GAP_ID_PATTERN.match(gap_id):
                errors.append(f"{label}: gap_id must match ^GAP-[0-9]{{3,}}$ (for example GAP-001).")

        priority = gap.get("priority")
        if "priority" in gap and priority not in PRIORITIES:
            errors.append(f"{label}: priority must be one of {', '.join(PRIORITIES)}, found {priority!r}.")

        status = gap.get("status")
        if "status" in gap and status not in STATUSES:
            errors.append(f"{label}: status must be one of {', '.join(STATUSES)}, found {status!r}.")

        if "gap_definition" in gap:
            definition = gap["gap_definition"]
            if not isinstance(definition, str):
                errors.append(f"{label}: 'gap_definition' must be a string, found {type(definition).__name__}.")
            elif not definition.strip():
                errors.append(f"{label}: 'gap_definition' must not be empty.")

        if "decisions_recorded" in gap:
            decisions = gap["decisions_recorded"]
            if not isinstance(decisions, list):
                errors.append(f"{label}: 'decisions_recorded' must be an array, found {type(decisions).__name__}.")
            else:
                for d_pos, decision in enumerate(decisions, start=1):
                    d_label = f"{label}, decision {d_pos}"
                    if not isinstance(decision, dict):
                        errors.append(f"{d_label}: must be an object, found {type(decision).__name__}.")
                        continue
                    d_missing = [key for key in DECISION_KEYS if key not in decision]
                    d_extra = [key for key in decision if key not in DECISION_KEYS]
                    if d_missing:
                        errors.append(f"{d_label}: missing required property: {', '.join(d_missing)}.")
                    if d_extra:
                        errors.append(
                            f"{d_label}: unexpected property: {', '.join(d_extra)}. "
                            f"Only {', '.join(DECISION_KEYS)} are allowed."
                        )
                    for key in DECISION_KEYS:
                        if key in decision:
                            value = decision[key]
                            if not isinstance(value, str):
                                errors.append(f"{d_label}: '{key}' must be a string, found {type(value).__name__}.")
                            elif not value.strip():
                                errors.append(f"{d_label}: '{key}' must not be empty.")

        if "affected_requirements" in gap:
            refs = gap["affected_requirements"]
            if not isinstance(refs, list):
                errors.append(f"{label}: 'affected_requirements' must be an array, found {type(refs).__name__}.")
            else:
                for r_pos, ref in enumerate(refs, start=1):
                    r_label = f"{label}, affected requirement {r_pos}"
                    if not isinstance(ref, dict):
                        errors.append(f"{r_label}: must be an object, found {type(ref).__name__}.")
                        continue
                    r_missing = [key for key in REF_KEYS if key not in ref]
                    r_extra = [key for key in ref if key not in REF_KEYS]
                    if r_missing:
                        errors.append(f"{r_label}: missing required property: {', '.join(r_missing)}.")
                    if r_extra:
                        errors.append(
                            f"{r_label}: unexpected property: {', '.join(r_extra)}. Only {', '.join(REF_KEYS)} are allowed."
                        )
                    for key in REF_KEYS:
                        if key in ref:
                            value = ref[key]
                            if not isinstance(value, str):
                                errors.append(f"{r_label}: '{key}' must be a string, found {type(value).__name__}.")
                            elif not value.strip():
                                errors.append(f"{r_label}: '{key}' must not be empty.")
                    req_id = ref.get("requirement_id")
                    if isinstance(req_id, str) and req_id.strip() and not REQ_ID_PATTERN.match(req_id):
                        errors.append(f"{r_label}: requirement_id must match ^REQ-[0-9]{{3,}}$ (for example REQ-001).")
    return errors


def normalise_definition(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def validate_semantics(data, requirements, allow_stale):
    """Return (errors, warnings). Call only on structurally valid data."""
    errors = []
    warnings = []

    seen_ids = {}
    seen_definitions = {}
    for position, gap in enumerate(data, start=1):
        gap_id = gap["gap_id"]
        label = f"Gap {gap_id}"

        if gap_id in seen_ids:
            errors.append(f"{label}: duplicate gap_id (also used by gap {seen_ids[gap_id]}). Gap IDs must be unique.")
        else:
            seen_ids[gap_id] = position

        key = normalise_definition(gap["gap_definition"])
        if key in seen_definitions and seen_definitions[key] != gap_id:
            errors.append(
                f"{label}: gap_definition duplicates {seen_definitions[key]}. "
                "Consolidate the two gaps, or reword so each states a different missing decision."
            )
        else:
            seen_definitions.setdefault(key, gap_id)

        refs = gap["affected_requirements"]
        if not refs:
            errors.append(f"{label}: at least one affected requirement is required.")
        seen_refs = set()
        for ref in refs:
            req_id = ref["requirement_id"]
            if req_id in seen_refs:
                errors.append(f"{label}: affected requirement {req_id} is listed more than once.")
            seen_refs.add(req_id)
            if requirements is None:
                continue
            if req_id not in requirements:
                message = f"{label}: affected requirement {req_id} does not exist in the current atomic requirements."
                (warnings if allow_stale else errors).append(message)
            elif ref["description"] != requirements[req_id]:
                message = (
                    f"{label}: description of {req_id} does not match the current atomic requirement "
                    "(the requirement changed, or the description was copied inexactly)."
                )
                (warnings if allow_stale else errors).append(message)

        decisions = gap["decisions_recorded"]
        if gap["status"] == "resolved" and not decisions:
            errors.append(f"{label}: status is resolved but no decision is recorded.")
        stamps = []
        for d_pos, decision in enumerate(decisions, start=1):
            parsed = parse_timestamp(decision["recorded_at"])
            if parsed is None:
                errors.append(
                    f"{label}, decision {d_pos}: recorded_at {decision['recorded_at']!r} is not a valid ISO 8601 "
                    "date-time (for example 2026-10-26T18:30:00+05:30)."
                )
            else:
                stamps.append(parsed)
        # Decision history is append-only; comparable only when both stamps carry (or both lack) an offset.
        for earlier, later in zip(stamps, stamps[1:]):
            if (earlier.tzinfo is None) == (later.tzinfo is None) and later < earlier:
                errors.append(f"{label}: decisions_recorded is not in chronological order; history must be append-only.")
                break
    return errors, warnings


def validate_register(data, duplicate_keys, requirements, allow_stale=False):
    """Full validation. Returns (errors, warnings). requirements may be None (structure only)."""
    errors = validate_structure(data, duplicate_keys)
    if errors:
        return errors, []
    return validate_semantics(data, requirements, allow_stale)


def default_requirements_path(gaps_path):
    gaps_dir = os.path.dirname(os.path.abspath(gaps_path))
    return os.path.join(os.path.dirname(gaps_dir), "atomic_requirements", "atomic_requirements.json")


def main():
    parser = argparse.ArgumentParser(description="Validate a gap register JSON file.")
    parser.add_argument("path", help="Path to gaps.json, or - to read standard input.")
    parser.add_argument("--requirements", help="Path to atomic_requirements.json (default: derived from the gap register path).")
    parser.add_argument("--structure-only", action="store_true", help="Skip checks against the atomic requirements.")
    parser.add_argument("--allow-stale", action="store_true", help="Report stale requirement references as warnings.")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.path == "-":
            try:
                data, duplicate_keys = json.loads(sys.stdin.read()), []
            except json.JSONDecodeError as exc:
                raise JsonSyntaxError(f"invalid JSON on standard input at line {exc.lineno}, column {exc.colno}: {exc.msg}.")
        else:
            data, duplicate_keys = read_json(args.path)
        requirements = None
        if not args.structure_only:
            req_path = args.requirements or (None if args.path == "-" else default_requirements_path(args.path))
            if req_path is None:
                raise InputError("--requirements is required when reading from standard input (or use --structure-only).")
            requirements = load_requirements(req_path)
    except JsonSyntaxError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except InputError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate_register(data, duplicate_keys, requirements, args.allow_stale)
    for message in warnings[:MAX_REPORTED]:
        print(f"WARNING: {message}", file=sys.stderr)
    if errors:
        print(f"FAILED: {len(errors)} validation error(s).", file=sys.stderr)
        for message in errors[:MAX_REPORTED]:
            print(f"  - {message}", file=sys.stderr)
        if len(errors) > MAX_REPORTED:
            print(f"  ... and {len(errors) - MAX_REPORTED} more.", file=sys.stderr)
        return 1

    scope = "structure only" if args.structure_only else "structure and semantics"
    print(f"PASSED: {len(data)} gap(s) validated ({scope}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
