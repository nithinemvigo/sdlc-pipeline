#!/usr/bin/env python3
"""Validate development stories (ba-requirements plugin, Phase 3).

Two modes, standard library only:

  validate-development-stories.py <draft.json | -> [--project-root DIR]
                                  [--requirements F] [--gaps F] [--no-gaps]
      Validate the structured draft the Story Generation Agent produces (see
      schemas/development-stories.schema.json): structure, IDs, source requirement
      references, applied decisions, duplicates, coverage, the ultra-lean story (Story ID,
      short summary, high-level functional criteria) and the detailed story (functional and
      non-functional detail), and that both survive a write-and-parse round trip as Markdown.

  validate-development-stories.py --document FILE [--project-root DIR]
      Validate the managed '# Development Stories' section of a Markdown document (the
      ultra-lean stories) against the lean story contract, the consolidated
      <project-root>/stories/detailed_stories.md against the detailed story contract, and that
      the two match by Story ID and summary and are current in the story state.

A schema-valid story is not automatically a good story: semantic review (coherent capability,
testable criteria, no invented decisions) is the agent's job and is specified in rules/ and
skills/. This script prints a few lint warnings (vague wording, a summary that is not short, a
long lean criterion); warnings never fail validation. Lean rules enforced on a draft: lean criteria are one
plain functional statement, not Given/When/Then scenarios, and neither the summary nor the lean criteria (nor a story's
whole functional behaviour) may be a non-functional requirement. In a saved document the non-functional check is advice. Detailed criteria are plain statements too (a Given/When/Then wording only draws a warning).

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
STORY_KEYS = ("story_id", "summary", "lean_acceptance_criteria", "detailed", "lean_reviewed", "source_requirement_ids", "applied_decisions")
STORY_REQUIRED = ("summary", "lean_acceptance_criteria", "detailed", "source_requirement_ids")
DETAILED_REQUIRED = common.DETAILED_REQUIRED
OUTCOMES = ("incorporated", "no_change_required")
MAX_REPORTED = 40
VAGUE_PHRASES = ("handle appropriately", "as expected", "user-friendly", "user friendly", "as appropriate", "tbd", "to be determined")
_NUMBERING_RE = re.compile(r"^\s*(?:[0-9]+[.)]|[-*+])\s")

# Ultra-lean lint (rules/story-writing-rules.md). Advisory except for the Gherkin rule and the one-statement rule.
MIN_SUMMARY_WORDS = 2
MAX_SUMMARY_WORDS = 7
MAX_LEAN_CRITERION_WORDS = 30
_GHERKIN_RE = re.compile(r"^\s*given\b.*\bwhen\b.*\bthen\b", re.IGNORECASE | re.DOTALL)
# Quality attributes (accessibility, performance, availability, compliance, security-in-operation). They belong in the
# detailed story's Non-Functional Requirements, never in a summary or lean criterion of the requirements document.
# Terms that are often a business feature on their own (audit, availability of a product, a performance review) are not listed.
_NON_FUNCTIONAL_RE = re.compile(
    r"\b(?:accessib\w*|keyboard|screen[- ]?readers?|assistive|wcag|aria|colou?r contrast|contrast ratios?|focus order|tab order|"
    r"label+ed\s+(?:fields?|inputs?|controls?)|"
    r"performance(?!\s+(?:review|appraisal|rating|management))|latency|throughput|uptime|(?:system|service)\s+availability|availability\s+(?:target|of the (?:system|service))|\d+(?:\.\d+)?\s*%\s+availability|"
    r"scalab\w*|concurrent\s+(?:users|sessions|requests)|concurrency|response times?|load times?|page loads?|fail-?over|disaster recovery|\bRTO\b|\bRPO\b|"
    r"within\s+\d+(?:\.\d+)?\s*(?:ms|milliseconds?|seconds?)|\d+(?:\.\d+)?\s*(?:ms|milliseconds)|"
    r"gdpr|hipaa|pci[- ]?dss|soc\s?2|iso\s?27001|cross-browser|supported browsers?|encrypt\w*\s+(?:at rest|in transit)|at rest|in transit)\b",
    re.IGNORECASE,
)
_ABBREVIATION_RE = re.compile(r"\b(?:e\.g|i\.e|etc|vs)\.", re.IGNORECASE)
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def _sentence_count(text):
    text = _ABBREVIATION_RE.sub(lambda m: m.group(0).replace(".", ""), text)
    return len([part for part in _SENTENCE_BREAK_RE.split(" ".join(text.split())) if part.strip()])


def lean_warnings(label, summary, criteria, include_nfr=True):
    """Advisory warnings for an ultra-lean story that is longer or less functional than the standard asks.

    include_nfr=False leaves out the non-functional warning where the caller reports it as an error instead."""
    found = []
    words = len(summary.split())
    if _sentence_count(summary) > 1 or words > MAX_SUMMARY_WORDS:
        found.append(f"{label}: the summary is not concise ({words} words); use a concise label (typically 3-{MAX_SUMMARY_WORDS} words) of the core capability and leave detail to the acceptance criteria.")
    elif words < MIN_SUMMARY_WORDS:
        found.append(f"{label}: the summary is too vague ({words} word); use a concise label (typically 3-{MAX_SUMMARY_WORDS} words) that identifies the core capability.")
    if len(criteria) > 1:
        found.append(f"{label}: the acceptance criteria are a list of {len(criteria)} items; combine them into one statement.")
    for item in criteria:
        if len(item.split()) > MAX_LEAN_CRITERION_WORDS:
            found.append(f"{label}: the acceptance criteria statement is long ({len(item.split())} words); keep only the primary functional outcome and leave conditions, rules and scenarios to the detailed story.")
        if include_nfr and _NON_FUNCTIONAL_RE.search(item):
            found.append(f"{label}: the acceptance criteria statement looks like a non-functional requirement; non-functional detail belongs in the detailed story only.")
    return found


def non_functional_errors(label, summary, criteria, behaviours):
    """Errors for a story that carries a quality attribute into the requirements document, or is nothing but one.

    The requirements document holds functional stories only. A non-functional requirement is never a story of its own:
    it goes in the Non-Functional Requirements of the functional stories it constrains, in the detailed story."""
    found = []
    hit = _NON_FUNCTIONAL_RE.search(summary)
    if hit:
        found.append(f"{label}: the summary names a non-functional requirement ('{hit.group(0)}'). A non-functional requirement is not a story: remove this story and state the requirement in the Non-Functional Requirements of each functional story it constrains.")
    for item in criteria:
        hit = _NON_FUNCTIONAL_RE.search(item)
        if hit:
            found.append(f"{label}: the lean acceptance criteria statement is or contains a non-functional requirement ('{hit.group(0)}'). The requirements document holds functional outcomes only; move the quality target to the detailed story's Non-Functional Requirements.")
    if behaviours and all(_NON_FUNCTIONAL_RE.search(item) for item in behaviours):
        found.append(f"{label}: every functional behaviour item is a quality attribute, so this story has no functional behaviour. Attach the requirement to the functional stories it constrains as a Non-Functional Requirement instead of making it a story.")
    return found


SECURITY_BASELINE_PREFIX = "Security (baseline):"


def security_baseline_warnings(label, non_functional, is_new):
    """Advisory warnings for the baseline security entries (rules/security-baseline-rules.md).

    Every new story is expected to carry the baseline entries its behaviour calls for. Existing stories are not
    flagged here: adding to them is proposed to the user, not done silently. A baseline entry states a control
    without any business value, so a digit in one is flagged as a probable invented value."""
    found = []
    baseline = [item for item in non_functional if item.lower().startswith(SECURITY_BASELINE_PREFIX.lower())]
    if is_new and not baseline:
        found.append(f"{label}: no '{SECURITY_BASELINE_PREFIX}' entry in the Non-Functional Requirements. Security is always derived; add the baseline entries this story's behaviour calls for, or say in the report why none applies.")
    for item in baseline:
        if re.search(r"\d", item):
            found.append(f"{label}: the baseline security entry '{item}' contains a number. A baseline entry states a control without an invented value; a value is a business decision (gap or confirmed decision).")
    return found


def gherkin_criteria(criteria):
    return [number for number, item in enumerate(criteria, start=1) if _GHERKIN_RE.match(item)]


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


def _check_text_list(items, label, name, errors, required, check_numbering=True):
    """Validate an array of plain-text items. Returns True when it is usable."""
    if not isinstance(items, list) or (required and not items):
        errors.append(f"{label}: '{name}' must be {'a non-empty' if required else 'an'} array of strings.")
        return False
    usable = True
    for number, item in enumerate(items, start=1):
        if not _is_text(item):
            errors.append(f"{label}: {name} item {number} must be a non-empty string.")
            usable = False
        elif check_numbering and _NUMBERING_RE.match(item):
            errors.append(f"{label}: {name} item {number} starts with its own numbering or bullet; numbering and bullets are added when the story is written.")
            usable = False
    return usable


def _roundtrip_lean_error(story):
    probe = {"story_id": "US-001", "summary": story["summary"], "acceptance_criteria": story["acceptance_criteria"]}
    stories, problems = common.parse_section(common.render_section([common.render_lean(probe)]))
    if problems or len(stories) != 1:
        return "; ".join(problems) or "the story does not parse back as one story"
    if common.canonical_lean(stories[0]) != common.canonical_lean(probe):
        return "the text does not survive being written as Markdown and read back"
    return None


def _roundtrip_detailed_error(story):
    probe = dict(story, story_id="US-001")
    stories, problems = common.parse_detailed_document(common.render_detailed_document([common.render_detailed(probe)]))
    if problems or len(stories) != 1:
        return "; ".join(problems) or "the story does not parse back as one story"
    if common.canonical_detailed(stories[0]) != common.canonical_detailed(probe):
        return "the text does not survive being written as Markdown and read back"
    return None


def _dependency_story_errors(stories):
    """A dependency names another story as [[Summary of that story]] (or by an existing ID); both must exist in the draft."""
    usable = [s for s in stories if isinstance(s, dict) and isinstance(s.get("summary"), str) and isinstance(s.get("detailed"), dict)]
    by_summary = {common.story_reference_key(s["summary"]): s for s in usable}
    known_ids = {s["story_id"] for s in usable if isinstance(s.get("story_id"), str)}
    errors = []
    for position, story in enumerate(stories, start=1):
        if story not in usable or not isinstance(story["detailed"].get("dependencies"), list):
            continue
        label = f"Story {position}" + (f" ({story['story_id']})" if isinstance(story.get("story_id"), str) else "")
        own = common.story_reference_key(story["summary"])
        for number, item in enumerate(story["detailed"]["dependencies"], start=1):
            if not isinstance(item, str):
                continue
            for name in common.STORY_REF_RE.findall(item):
                key = common.story_reference_key(name)
                if key == own:
                    errors.append(f"{label}: dependencies item {number} makes the story depend on itself.")
                elif key not in by_summary:
                    errors.append(f"{label}: dependencies item {number} refers to [[{name}]], which is not the summary of any story in the draft; copy the exact summary of the story it depends on.")
            for story_id in common.STORY_ID_IN_TEXT_RE.findall(item):
                if story_id not in known_ids:
                    errors.append(f"{label}: dependencies item {number} names {story_id}, which is not a story in the draft; write [[Summary of the story]] for a new story.")
                elif story_id == story.get("story_id"):
                    errors.append(f"{label}: dependencies item {number} makes the story depend on itself.")
    return errors


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

    for position, story in enumerate(stories, start=1):
        label = f"Story {position}"
        if not isinstance(story, dict):
            errors.append(f"{label}: must be an object, found {type(story).__name__}.")
            continue
        story_id = story.get("story_id")
        if isinstance(story_id, str):
            label = f"Story {position} ({story_id})"
        before = len(errors)
        _check_keys(story, STORY_KEYS, STORY_REQUIRED, label, errors)

        if story_id is not None:
            if not isinstance(story_id, str) or not common.STORY_ID_RE.match(story_id):
                errors.append(f"{label}: story_id must be null (a new story) or match ^US-[0-9]{{3,}}$.")
            elif story_id in seen_ids:
                errors.append(f"{label}: duplicate story_id (also story {seen_ids[story_id]}).")
            else:
                seen_ids[story_id] = position

        summary = story.get("summary")
        if "summary" in story:
            if not _is_text(summary):
                errors.append(f"{label}: 'summary' must be a non-empty string.")
            elif "\n" in summary or "\r" in summary:
                errors.append(f"{label}: 'summary' must be a single line.")

        lean_criteria = story.get("lean_acceptance_criteria")
        if "lean_acceptance_criteria" in story:
            if _check_text_list(lean_criteria, label, "lean criterion", errors, required=True):
                if len(lean_criteria) != 1:
                    errors.append(
                        f"{label}: 'lean_acceptance_criteria' must hold exactly one statement ({len(lean_criteria)} given); "
                        "combine them into a single short statement of the primary functional outcome."
                    )
                for number in gherkin_criteria(lean_criteria):
                    errors.append(
                        f"{label}: lean criterion {number} is a Given/When/Then scenario. The lean acceptance criteria are one concise statement "
                        "of the observable functional outcome; scenarios belong in the detailed story."
                    )

        detail = story.get("detailed")
        canon_detail = None
        if "detailed" in story:
            if not isinstance(detail, dict):
                errors.append(f"{label}: 'detailed' must be an object with the detailed story fields.")
            else:
                _check_keys(detail, common.DETAILED_KEYS, DETAILED_REQUIRED, f"{label} detailed", errors)
                if "description" in detail and not _is_text(detail["description"]):
                    errors.append(f"{label}: detailed 'description' must be a non-empty string.")
                for key in common.DETAILED_LIST_KEYS:
                    if key in detail:
                        _check_text_list(detail[key], label, f"detailed {key}", errors, required=key in DETAILED_REQUIRED)

        if "lean_reviewed" in story and not isinstance(story["lean_reviewed"], bool):
            errors.append(f"{label}: 'lean_reviewed' must be true or false.")

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

        if len(errors) != before:
            continue

        lean_story = common.lean_view(story)
        full_story = common.detailed_view(story)
        canon_lean = common.canonical_lean(lean_story)
        canon_detail = common.canonical_detailed(full_story)
        problem = _roundtrip_lean_error(lean_story)
        if problem:
            errors.append(f"{label}: the lean story cannot be written as readable Markdown: {problem}")
        problem = _roundtrip_detailed_error(full_story)
        if problem:
            errors.append(f"{label}: the detailed story cannot be written as readable Markdown: {problem}")
        for name, items in (("lean criteria", canon_lean["acceptance_criteria"]), ("detailed acceptance criteria", canon_detail["acceptance_criteria"])):
            folded = [c.casefold() for c in items]
            if len(set(folded)) != len(folded):
                errors.append(f"{label}: duplicate {name}.")
        key = canon_lean["summary"].casefold()
        if key in seen_summary:
            errors.append(f"{label}: summary duplicates story {seen_summary[key]}; merge them or make each state a different capability.")
        else:
            seen_summary[key] = position
        key = canon_detail["description"].casefold()
        if key in seen_description:
            errors.append(f"{label}: detailed description duplicates story {seen_description[key]}.")
        else:
            seen_description[key] = position
        key = frozenset(c.casefold() for c in canon_lean["acceptance_criteria"])
        if key in seen_criteria:
            errors.append(f"{label}: lean criteria are identical to story {seen_criteria[key]}.")
        else:
            seen_criteria[key] = position
        text = " ".join([canon_lean["summary"], canon_detail["description"]] + canon_lean["acceptance_criteria"] + canon_detail["acceptance_criteria"]
                        + canon_detail["functional_behaviour"] + canon_detail["business_rules"] + canon_detail["scenarios"]
                        + canon_detail["non_functional_requirements"]).lower()
        for phrase in VAGUE_PHRASES:
            if phrase in text:
                warnings.append(f"{label}: contains the vague phrase '{phrase}'; make it measurable or remove it.")
        if not re.search(r"\bas an?\b", canon_detail["description"], re.IGNORECASE):
            warnings.append(f"{label}: the detailed description does not use the 'As a ..., I want ..., so that ...' form; use a neutral formulation only when the actor or value is unclear.")
        warnings.extend(lean_warnings(label, canon_lean["summary"], canon_lean["acceptance_criteria"], include_nfr=False))
        warnings.extend(security_baseline_warnings(label, canon_detail["non_functional_requirements"], story_id is None))
        errors.extend(non_functional_errors(label, canon_lean["summary"], canon_lean["acceptance_criteria"], canon_detail["functional_behaviour"]))
        for number in gherkin_criteria(canon_detail["acceptance_criteria"]):
            warnings.append(f"{label}: detailed criterion {number} is written as Given/When/Then; write it as a plain statement of the condition and the expected outcome.")

    errors.extend(_dependency_story_errors(stories))

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
    """Validate the ultra-lean stories parsed from a document. Returns (errors, warnings)."""
    errors = list(problems)
    warnings = []
    for story in stories:
        if story.get("legacy"):
            errors.append(
                f"{story['story_id']}: uses the layout of an earlier plugin version (Summary and Detailed Description fields). "
                "Run /sdlc-pipeline:ba-generate-stories to rewrite it as an ultra-lean story with a detailed story in stories/detailed_stories.md."
            )
            continue
        text = " ".join([story["summary"]] + story["acceptance_criteria"]).lower()
        for phrase in VAGUE_PHRASES:
            if phrase in text:
                warnings.append(f"{story['story_id']}: contains the vague phrase '{phrase}'.")
        warnings.extend(lean_warnings(story["story_id"], story["summary"], story["acceptance_criteria"]))
        for number in gherkin_criteria(story["acceptance_criteria"]):
            warnings.append(f"{story['story_id']}: lean criterion {number} is a Given/When/Then scenario; the lean acceptance criteria are one concise statement.")
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


def validate_story_set(doc_stories, doc_problems, detailed, requirements, state=None, legacy_files=None):
    """Validate the ultra-lean stories of the document together with stories/detailed_stories.md.

    detailed is a story_common.DetailedFile. Returns (errors, warnings, status). Errors are structural:
    a story without a detailed story, a detailed story without a lean story, an invalid file, differing
    summaries. Hash divergence (a version edited since the last synchronisation) is reported as warnings
    and in the returned pair status.
    """
    errors, warnings = validate_managed_section(doc_stories, doc_problems, requirements, state)
    errors.extend(detailed.problems)
    status = common.pair_status(doc_stories, detailed.stories, state)
    if not detailed.exists:
        if doc_stories:
            errors.append(f"{common.DETAILED_RELATIVE} does not exist; every story needs its detailed story in that single file.")
    else:
        for story_id in status["detailed_missing"]:
            errors.append(f"{story_id}: there is no detailed story in {common.DETAILED_RELATIVE}.")
        for story_id in status["detailed_extra"]:
            errors.append(f"{story_id}: {common.DETAILED_RELATIVE} has a detailed story but the document has no matching story.")
    for name in legacy_files or []:
        warnings.append(f"{name} was written by an earlier plugin version and is no longer used; all detailed stories are in {common.DETAILED_RELATIVE}. Remove it once you have checked nothing is missing.")
    for story in doc_stories:
        story_id = story["story_id"]
        full = detailed.stories.get(story_id)
        if full is None or story.get("legacy"):
            continue
        if common.collapse(story["summary"]).casefold() != common.collapse(full["summary"]).casefold():
            errors.append(f"{story_id}: the summary differs between the requirements document and the detailed story.")
        text = " ".join([full["summary"], full["description"]] + full["functional_behaviour"] + full["business_rules"]
                        + full["acceptance_criteria"] + full["scenarios"] + full["non_functional_requirements"]).lower()
        warnings.extend(f"{story_id}: the detailed story contains the vague phrase '{phrase}'." for phrase in VAGUE_PHRASES if phrase in text)
        for number in gherkin_criteria(full["acceptance_criteria"]):
            warnings.append(f"{story_id}: detailed criterion {number} is written as Given/When/Then; write it as a plain statement of the condition and the expected outcome.")
        for dependency in full["dependencies"]:
            for other in common.STORY_ID_IN_TEXT_RE.findall(dependency):
                if other not in detailed.stories:
                    warnings.append(f"{story_id}: a dependency names {other}, which is not in {common.DETAILED_RELATIVE}.")
    for story_id in status["lean_edited"]:
        warnings.append(f"{story_id}: the story in the requirements document was edited since the last synchronisation.")
    for story_id in status["detailed_edited"]:
        warnings.append(f"{story_id}: the detailed story was edited since the last synchronisation.")
    for story_id in status["lean_stale"]:
        warnings.append(f"{story_id}: the detailed story changed after its lean story was written; update the lean story from it.")
    for story_id in status["detailed_untracked"]:
        warnings.append(f"{story_id}: the story state has no record of this detailed story yet.")
    return errors, warnings, status


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
    parser.add_argument("--document", help="Validate the managed section of this Markdown document (and the detailed stories file) instead.")
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
            errors, warnings, _ = validate_story_set(
                doc.stories, doc.problems, common.scan_detailed(paths), requirements, state, common.scan_legacy_files(paths)
            )
            subject = f"{len(doc.stories)} ultra-lean story(ies) in the managed section and their detailed stories in {common.DETAILED_RELATIVE}"
        else:
            draft = _read_json(args.draft)
            gaps = common.load_gaps(paths, requirements, ignore=args.no_gaps)
            if gaps["status"] == "INVALID":
                print("FAILED: the gap register is invalid; fix it or use --no-gaps.", file=sys.stderr)
                for message in gaps["errors"][:MAX_REPORTED]:
                    print(f"  - {message}", file=sys.stderr)
                return 1
            errors, warnings = validate_draft(draft, requirements, gaps["register"])
            subject = f"{len(draft.get('stories', [])) if isinstance(draft, dict) and isinstance(draft.get('stories'), list) else 0} draft story(ies)"
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
