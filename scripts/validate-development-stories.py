#!/usr/bin/env python3
"""Validate development stories (ba-requirements plugin, Phase 3).

Two modes, standard library only:

  validate-development-stories.py <draft.json | -> [--project-root DIR]
                                  [--requirements F] [--gaps F] [--no-gaps]
      Validate the structured draft the Story Generation Agent produces (see
      schemas/development-stories.schema.json): structure, IDs, source requirement
      references, applied decisions, duplicates, coverage, and that every story
      survives a write-and-parse round trip as Markdown.

  validate-development-stories.py --document FILE [--project-root DIR]
      Validate the managed '# Development Stories' section of a Markdown document
      against the strict four-field story contract.

A schema-valid story is not automatically a good story: semantic review (coherent
capability, testable criteria, no invented decisions) is the agent's job and is
specified in rules/ and skills/. This script prints a few lint warnings for vague
wording; warnings never fail validation.

Exit status: 0 = valid, 1 = validation failed, 2 = a file could not be read.
"""

import argparse
import json
import os
import re
import sys

import importlib.util


def _load_common():
    name = "ba_story_common"
    if name in sys.modules:
        return sys.modules[name]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "story_common.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load_common()

DRAFT_KEYS = ("stories", "not_covered_requirements", "decisions_reviewed")
STORY_KEYS = ("story_id", "summary", "description", "acceptance_criteria", "source_requirement_ids", "applied_decisions")
STORY_REQUIRED = ("summary", "description", "acceptance_criteria", "source_requirement_ids")
OUTCOMES = ("incorporated", "no_change_required")
MAX_REPORTED = 40
VAGUE_PHRASES = ("handle appropriately", "as expected", "user-friendly", "user friendly", "as appropriate", "tbd", "to be determined")
_NUMBERING_RE = re.compile(r"^\s*(?:[0-9]+[.)]|[-*+])\s")


class InputError(Exception):
    """A file could not be read (exit 2)."""


def _is_text(value):
    return isinstance(value, str) and bool(value.strip())


def _check_keys(obj, allowed, required, label, errors):
    missing = [key for key in required if key not in obj]
    extra = [key for key in obj if key not in allowed]
    if missing:
        errors.append(f"{label}: missing required property: {', '.join(missing)}.")
    if extra:
        errors.append(
            f"{label}: unexpected property: {', '.join(extra)}. Only {', '.join(allowed)} are allowed; "
            "requirement and gap mappings are derived and kept in the internal state, never added to the story."
        )


def _roundtrip_error(story):
    probe = {
        "story_id": "US-001",
        "summary": story["summary"],
        "description": story["description"],
        "acceptance_criteria": story["acceptance_criteria"],
    }
    stories, problems = common.parse_section(common.render_section([common.render_story(probe)]))
    if problems or len(stories) != 1:
        return "; ".join(problems) or "the story does not parse back as one story"
    if common.canonical_story(stories[0]) != common.canonical_story(probe):
        return "the text does not survive being written as Markdown and read back"
    return None


def validate_draft(draft, requirements, register):
    """Validate a structured draft. Returns (errors, warnings).

    requirements: {requirement_id: item} from Phase 1. register: the Phase 2 list, or None when
    gap context is unavailable (stories may then not claim any applied decision).
    """
    errors, warnings = [], []
    if not isinstance(draft, dict):
        return [f"The root value must be an object with a 'stories' array, found {type(draft).__name__}."], []
    _check_keys(draft, DRAFT_KEYS, ("stories",), "Draft", errors)
    stories = draft.get("stories")
    if not isinstance(stories, list) or not stories:
        errors.append("'stories' must be a non-empty array.")
        return errors, warnings

    gaps = {gap["gap_id"]: gap for gap in register or []}
    seen_ids = {}
    seen_summary, seen_description, seen_criteria = {}, {}, {}
    covered = set()
    valid_stories = []

    for position, story in enumerate(stories, start=1):
        label = f"Story {position}"
        if not isinstance(story, dict):
            errors.append(f"{label}: must be an object, found {type(story).__name__}.")
            continue
        story_id = story.get("story_id")
        if isinstance(story_id, str):
            label = f"Story {position} ({story_id})"
        _check_keys(story, STORY_KEYS, STORY_REQUIRED, label, errors)
        before = len(errors)

        if story_id is not None:
            if not isinstance(story_id, str) or not common.STORY_ID_RE.match(story_id):
                errors.append(f"{label}: story_id must be null (a new story) or match ^US-[0-9]{{3,}}$.")
            elif story_id in seen_ids:
                errors.append(f"{label}: duplicate story_id (also story {seen_ids[story_id]}).")
            else:
                seen_ids[story_id] = position

        summary, description, criteria = story.get("summary"), story.get("description"), story.get("acceptance_criteria")
        if "summary" in story and not _is_text(summary):
            errors.append(f"{label}: 'summary' must be a non-empty string.")
        if "description" in story and not _is_text(description):
            errors.append(f"{label}: 'description' must be a non-empty string.")
        if "acceptance_criteria" in story:
            if not isinstance(criteria, list) or not criteria:
                errors.append(f"{label}: 'acceptance_criteria' must be a non-empty array of strings.")
            else:
                for number, item in enumerate(criteria, start=1):
                    if not _is_text(item):
                        errors.append(f"{label}: acceptance criterion {number} must be a non-empty string.")
                    elif _NUMBERING_RE.match(item):
                        errors.append(f"{label}: acceptance criterion {number} starts with its own numbering or bullet; numbering is added when the story is written.")

        sources = story.get("source_requirement_ids")
        if "source_requirement_ids" in story:
            if not isinstance(sources, list) or not sources:
                errors.append(f"{label}: 'source_requirement_ids' must be a non-empty array.")
            else:
                seen_sources = set()
                for req_id in sources:
                    if not isinstance(req_id, str) or not common.REQ_ID_RE.match(req_id):
                        errors.append(f"{label}: source requirement {req_id!r} is not a REQ-001 style ID.")
                    elif req_id in seen_sources:
                        errors.append(f"{label}: source requirement {req_id} is listed more than once.")
                    elif req_id not in requirements:
                        errors.append(f"{label}: source requirement {req_id} does not exist in the current atomic requirements.")
                    else:
                        covered.add(req_id)
                    if isinstance(req_id, str):
                        seen_sources.add(req_id)

        applied = story.get("applied_decisions", [])
        if not isinstance(applied, list):
            errors.append(f"{label}: 'applied_decisions' must be an array of gap IDs.")
        else:
            related = set(common.derive_related_gaps(register, sources if isinstance(sources, list) else []))
            seen_applied = set()
            for gap_id in applied:
                if not isinstance(gap_id, str) or not common.GAP_ID_RE.match(gap_id):
                    errors.append(f"{label}: applied decision {gap_id!r} is not a GAP-001 style ID.")
                    continue
                if gap_id in seen_applied:
                    errors.append(f"{label}: applied decision {gap_id} is listed more than once.")
                seen_applied.add(gap_id)
                if register is None:
                    errors.append(f"{label}: applied decision {gap_id} cannot be claimed because the gap register is unavailable.")
                elif gap_id not in gaps:
                    errors.append(f"{label}: applied decision {gap_id} is not in the gap register.")
                elif gaps[gap_id]["status"] != "resolved" or not gaps[gap_id]["decisions_recorded"]:
                    errors.append(f"{label}: {gap_id} is {gaps[gap_id]['status']}; only a resolved gap with a recorded decision can be applied.")
                elif gap_id not in related:
                    errors.append(f"{label}: {gap_id} does not affect any requirement this story is built from.")

        if len(errors) == before and isinstance(criteria, list):
            canon = common.canonical_story(story)
            problem = _roundtrip_error(story)
            if problem:
                errors.append(f"{label}: cannot be written as readable Markdown: {problem}")
            key = canon["summary"].casefold()
            if key in seen_summary:
                errors.append(f"{label}: summary duplicates story {seen_summary[key]}; merge them or make each state a different capability.")
            else:
                seen_summary[key] = position
            key = canon["description"].casefold()
            if key in seen_description:
                errors.append(f"{label}: description duplicates story {seen_description[key]}.")
            else:
                seen_description[key] = position
            folded = [c.casefold() for c in canon["acceptance_criteria"]]
            if len(set(folded)) != len(folded):
                errors.append(f"{label}: duplicate acceptance criteria.")
            key = frozenset(folded)
            if key in seen_criteria:
                errors.append(f"{label}: acceptance criteria are identical to story {seen_criteria[key]}.")
            else:
                seen_criteria[key] = position
            text = " ".join([canon["summary"], canon["description"]] + canon["acceptance_criteria"]).lower()
            for phrase in VAGUE_PHRASES:
                if phrase in text:
                    warnings.append(f"{label}: contains the vague phrase '{phrase}'; make it measurable or remove it.")
            if not re.search(r"\bas an?\b", canon["description"], re.IGNORECASE):
                warnings.append(f"{label}: the description does not use the 'As a ..., I want ..., so that ...' form; use a neutral formulation only when the actor or value is unclear.")
            valid_stories.append(story)

    not_covered = draft.get("not_covered_requirements", [])
    listed = set()
    if not isinstance(not_covered, list):
        errors.append("'not_covered_requirements' must be an array.")
    else:
        for position, entry in enumerate(not_covered, start=1):
            label = f"Not-covered entry {position}"
            if not isinstance(entry, dict):
                errors.append(f"{label}: must be an object.")
                continue
            _check_keys(entry, ("requirement_id", "reason"), ("requirement_id", "reason"), label, errors)
            req_id, reason = entry.get("requirement_id"), entry.get("reason")
            if not isinstance(req_id, str) or req_id not in requirements:
                errors.append(f"{label}: {req_id!r} is not in the current atomic requirements.")
            elif req_id in covered:
                errors.append(f"{label}: {req_id} is covered by a story, so it cannot also be reported as not suitable.")
            elif req_id in listed:
                errors.append(f"{label}: {req_id} is listed more than once.")
            if not _is_text(reason):
                errors.append(f"{label}: a reason is required.")
            if isinstance(req_id, str):
                listed.add(req_id)

    for req_id in sorted(requirements, key=common.requirement_number):
        if req_id not in covered and req_id not in listed:
            errors.append(f"{req_id} is not covered by any story and is not reported as unsuitable for a story.")

    reviewed = draft.get("decisions_reviewed", [])
    if not isinstance(reviewed, list):
        errors.append("'decisions_reviewed' must be an array.")
    else:
        applied_somewhere = {g for s in stories if isinstance(s, dict) and isinstance(s.get("applied_decisions"), list) for g in s["applied_decisions"]}
        seen_reviewed = set()
        for position, entry in enumerate(reviewed, start=1):
            label = f"Reviewed decision {position}"
            if not isinstance(entry, dict):
                errors.append(f"{label}: must be an object.")
                continue
            _check_keys(entry, ("gap_id", "outcome"), ("gap_id", "outcome"), label, errors)
            gap_id, outcome = entry.get("gap_id"), entry.get("outcome")
            if outcome not in OUTCOMES:
                errors.append(f"{label}: outcome must be one of {', '.join(OUTCOMES)}.")
            if register is None:
                errors.append(f"{label}: cannot review {gap_id} because the gap register is unavailable.")
            elif not isinstance(gap_id, str) or gap_id not in gaps:
                errors.append(f"{label}: {gap_id!r} is not in the gap register.")
            elif gaps[gap_id]["status"] != "resolved" or not gaps[gap_id]["decisions_recorded"]:
                errors.append(f"{label}: {gap_id} is {gaps[gap_id]['status']}; only a resolved gap with a recorded decision can be reviewed.")
            elif outcome == "incorporated" and gap_id not in applied_somewhere:
                errors.append(f"{label}: {gap_id} is reported as incorporated but no story lists it in applied_decisions.")
            if gap_id in seen_reviewed:
                errors.append(f"{label}: {gap_id} is listed more than once.")
            seen_reviewed.add(gap_id)
    return errors, warnings


def validate_managed_section(stories, problems, requirements, state=None):
    """Validate stories parsed from a document. Returns (errors, warnings)."""
    errors = list(problems)
    warnings = []
    for story in stories:
        text = " ".join([story["summary"], story["description"]] + story["acceptance_criteria"]).lower()
        for phrase in VAGUE_PHRASES:
            if phrase in text:
                warnings.append(f"{story['story_id']}: contains the vague phrase '{phrase}'.")
    if state:
        in_doc = {s["story_id"] for s in stories}
        in_state = {s["story_id"] for s in state["stories"]}
        for story_id in sorted(in_state - in_doc):
            warnings.append(f"{story_id} is in the story state but not in the document.")
        for story_id in sorted(in_doc - in_state):
            warnings.append(f"{story_id} is in the document but not in the story state.")
        if requirements is not None:
            for entry in state["stories"]:
                for req_id in entry.get("source_requirement_ids", []):
                    if req_id not in requirements:
                        warnings.append(f"{entry['story_id']}: source requirement {req_id} no longer exists in the atomic requirements.")
    return errors, warnings


def _read_json(path):
    try:
        text = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8-sig").read()
    except (OSError, UnicodeDecodeError) as exc:
        raise InputError(f"cannot read {path}: {exc}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate development stories.")
    parser.add_argument("draft", nargs="?", help="Path to the structured draft JSON, or - for standard input.")
    parser.add_argument("--document", help="Validate the managed section of this Markdown document instead.")
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--requirements")
    parser.add_argument("--gaps")
    parser.add_argument("--no-gaps", action="store_true", help="Validate without gap context.")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if bool(args.draft) == bool(args.document):
        parser.error("give either a draft file or --document")

    paths = common.Paths(args.project_root)
    if args.requirements:
        paths.requirements = os.path.abspath(args.requirements)
    if args.gaps:
        paths.register = os.path.abspath(args.gaps)

    status, req_errors, requirements, _ = common.load_atomic(paths)
    if status:
        print(f"FAILED: atomic requirements unusable ({status}).", file=sys.stderr)
        for message in req_errors[:MAX_REPORTED]:
            print(f"  - {message}", file=sys.stderr)
        return 2 if status in ("INPUT_MISSING",) else 1

    try:
        if args.document:
            doc = common.read_document(os.path.abspath(args.document))
            if doc.ambiguity:
                print(f"FAILED: {doc.ambiguity}", file=sys.stderr)
                return 1
            if doc.section_state == "absent":
                print(f"FAILED: {args.document} has no '# {common.SECTION_TITLE}' section.", file=sys.stderr)
                return 1
            state, _, _ = common.load_state(paths)
            errors, warnings = validate_managed_section(doc.stories, doc.problems, requirements, state)
            subject = f"{len(doc.stories)} story(ies) in the managed section"
        else:
            draft = _read_json(args.draft)
            gaps = common.load_gaps(paths, requirements, ignore=args.no_gaps)
            if gaps["status"] == "INVALID":
                print("FAILED: the gap register is invalid; fix it or use --no-gaps.", file=sys.stderr)
                for message in gaps["errors"][:MAX_REPORTED]:
                    print(f"  - {message}", file=sys.stderr)
                return 1
            errors, warnings = validate_draft(draft, requirements, gaps["register"])
            subject = f"{len(draft.get('stories', [])) if isinstance(draft, dict) else 0} draft story(ies)"
    except common.Refused as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    except (InputError, common.IOFailure) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    for message in warnings[:MAX_REPORTED]:
        print(f"WARNING: {message}", file=sys.stderr)
    if errors:
        print(f"FAILED: {len(errors)} validation error(s).", file=sys.stderr)
        for message in errors[:MAX_REPORTED]:
            print(f"  - {message}", file=sys.stderr)
        if len(errors) > MAX_REPORTED:
            print(f"  ... and {len(errors) - MAX_REPORTED} more.", file=sys.stderr)
        return 1
    print(f"PASSED: {subject} validated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
