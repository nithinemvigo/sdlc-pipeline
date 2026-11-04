#!/usr/bin/env python3
"""Validate an atomic requirements JSON file (ba-requirements plugin, Phase 1).

Structural checks only, using the Python standard library. They mirror
schemas/atomic-requirement.schema.json and add the checks a schema cannot
express (unique and sequential IDs). Semantic checks such as atomicity,
duplicate meaning and source coverage are the analyst's responsibility.

Usage:
    validate-atomic-requirements.py <file | ->  [--no-sequence-check]

Exit status: 0 = valid, 1 = validation failed, 2 = file could not be read.
"""

import argparse
import json
import re
import sys

ID_PATTERN = re.compile(r"^REQ-[0-9]{3,}$")
REQUIRED_KEYS = ("requirement_id", "title", "description")
MAX_REPORTED = 25


def parse_json(text, duplicate_keys):
    def pairs_hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                duplicate_keys.append(key)
            seen.add(key)
        return dict(pairs)

    return json.loads(text, object_pairs_hook=pairs_hook)


def validate(data, duplicate_keys, check_sequence):
    errors = []

    if duplicate_keys:
        names = ", ".join(sorted(set(duplicate_keys)))
        errors.append(f"An object repeats a property name ({names}); each property may appear once.")

    if not isinstance(data, list):
        errors.append(
            f"The root value must be an array of requirement objects, found {type(data).__name__}. "
            "Do not wrap the array in another object."
        )
        return errors
    if not data:
        errors.append("The array is empty; at least one atomic requirement is expected.")
        return errors

    ids = []
    for position, item in enumerate(data, start=1):
        label = f"Item {position}"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object, found {type(item).__name__}.")
            continue

        missing = [key for key in REQUIRED_KEYS if key not in item]
        extra = [key for key in item if key not in REQUIRED_KEYS]
        if missing:
            errors.append(f"{label}: missing required propert{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}.")
        if extra:
            errors.append(
                f"{label}: unexpected propert{'y' if len(extra) == 1 else 'ies'}: {', '.join(extra)}. "
                f"Only {', '.join(REQUIRED_KEYS)} are allowed."
            )

        for key in REQUIRED_KEYS:
            if key not in item:
                continue
            value = item[key]
            if not isinstance(value, str):
                errors.append(f"{label}: '{key}' must be a string, found {type(value).__name__}.")
            elif not value.strip():
                errors.append(f"{label}: '{key}' must not be empty.")

        req_id = item.get("requirement_id")
        if isinstance(req_id, str) and req_id.strip():
            label = f"Item {position} ({req_id})"
            if not ID_PATTERN.match(req_id):
                errors.append(f"{label}: requirement_id must match ^REQ-[0-9]{{3,}}$ (for example REQ-001).")
            ids.append((position, req_id))

    seen = {}
    for position, req_id in ids:
        if req_id in seen:
            errors.append(f"Item {position}: duplicate requirement_id {req_id} (first used by item {seen[req_id]}).")
        else:
            seen[req_id] = position

    if check_sequence:
        for position, req_id in ids:
            expected = f"REQ-{position:03d}"
            if ID_PATTERN.match(req_id) and req_id != expected:
                errors.append(
                    f"Item {position}: requirement_id is {req_id} but initial generation expects {expected} "
                    "(sequential from REQ-001 with no gaps)."
                )

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate an atomic requirements JSON file.")
    parser.add_argument("path", help="Path to the JSON file, or - to read standard input.")
    parser.add_argument(
        "--no-sequence-check",
        action="store_true",
        help="Skip the sequential-ID check (for updates to an existing analysis).",
    )
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        if args.path == "-":
            text = sys.stdin.read()
        else:
            with open(args.path, "r", encoding="utf-8-sig") as handle:
                text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"FAILED: cannot read {args.path}: {exc}", file=sys.stderr)
        return 2

    duplicate_keys = []
    try:
        data = parse_json(text, duplicate_keys)
    except json.JSONDecodeError as exc:
        print(
            f"FAILED: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.",
            file=sys.stderr,
        )
        return 1

    errors = validate(data, duplicate_keys, check_sequence=not args.no_sequence_check)
    if errors:
        print(f"FAILED: {len(errors)} validation error(s).", file=sys.stderr)
        for message in errors[:MAX_REPORTED]:
            print(f"  - {message}", file=sys.stderr)
        if len(errors) > MAX_REPORTED:
            print(f"  ... and {len(errors) - MAX_REPORTED} more.", file=sys.stderr)
        return 1

    print(f"PASSED: {len(data)} atomic requirement(s) validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
