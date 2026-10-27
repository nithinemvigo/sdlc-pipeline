#!/usr/bin/env python3
"""Shared helpers for the Phase 3 story scripts (ba-requirements plugin).

Markdown section handling (locate, parse, render, hash), project paths, safe file
writes, and loading of the Phase 1 / Phase 2 inputs and the story state.
Standard library only. This is a library, not a command: validate-development-stories.py,
sync-development-stories.py and generate-phase3-report.py import it.
"""

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import textwrap
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECTION_TITLE = "Development Stories"
STATE_SCHEMA_VERSION = "1.0"
STORY_ID_RE = re.compile(r"^US-([0-9]{3,})$")
REQ_ID_RE = re.compile(r"^REQ-([0-9]{3,})$")
GAP_ID_RE = re.compile(r"^GAP-([0-9]{3,})$")
WRAP_WIDTH = 76


def load_script(filename, name):
    """Load a sibling script once per process, so every importer shares one module (and its exception classes)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPT_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


atomic_validator = load_script("validate-atomic-requirements.py", "ba_validate_atomic")
gap_validator = load_script("validate-gap-register.py", "ba_validate_gaps")


class Refused(Exception):
    """The request is not allowed or the data is invalid; nothing was written."""

    def __init__(self, message, details=None, data=None):
        super().__init__(message)
        self.details = details or []
        self.data = data or {}


class IOFailure(Exception):
    """A file could not be read or written."""


# ----------------------------------------------------------------------------- paths


class Paths:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.requirements = os.path.join(self.root, "atomic_requirements", "atomic_requirements.json")
        self.gaps_dir = os.path.join(self.root, "gaps")
        self.register = os.path.join(self.gaps_dir, "gaps.json")
        self.stories_dir = os.path.join(self.root, "stories")
        self.state = os.path.join(self.stories_dir, "story-generation-state.json")
        self.backups = os.path.join(self.stories_dir, "backups")
        self.report_dir = os.path.join(self.root, "report")
        self.report = os.path.join(self.report_dir, "phase3-report.html")


def now_stamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def to_json_bytes(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise IOFailure(f"cannot read {path}: {exc}")


def atomic_write_bytes(path, payload, prefix=".story-"):
    """Write to a temp file in the same directory, flush, then replace. The target is never half-written."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("wb", dir=directory, prefix=prefix, suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.exists(path):
            try:
                os.chmod(handle.name, os.stat(path).st_mode & 0o777)
            except OSError:
                pass
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


# ------------------------------------------------------------------------ text helpers

_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")


def split_lines(text):
    """Split into lines that keep their own line endings (only CR, LF and CRLF count as breaks)."""
    return _LINE_RE.findall(text)


def strip_eol(line):
    return line.rstrip("\r\n")


def normalise_eol(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def detect_eol(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    return "\r\n" if crlf > 0 and crlf >= lf else "\n"


def collapse(text):
    return " ".join(text.split())


def canonical_description(text):
    """Paragraphs separated by one blank line; whitespace inside a paragraph collapsed."""
    paragraphs, current = [], []
    for line in normalise_eol(text).split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append(collapse(" ".join(current)))
            current = []
    if current:
        paragraphs.append(collapse(" ".join(current)))
    return "\n\n".join(paragraphs)


def canonical_story(story):
    return {
        "summary": collapse(story["summary"]),
        "description": canonical_description(story["description"]),
        "acceptance_criteria": [collapse(item) for item in story["acceptance_criteria"]],
    }


def content_hash(story):
    """Hash of the story's content only (not its ID), so a renamed story keeps its content hash."""
    c = canonical_story(story)
    return sha256_text(json.dumps([c["summary"], c["description"], c["acceptance_criteria"]], ensure_ascii=False))


def field_hashes(story):
    c = canonical_story(story)
    return {
        "summary": sha256_text(c["summary"]),
        "description": sha256_text(c["description"]),
        "acceptance_criteria": [sha256_text(item) for item in c["acceptance_criteria"]],
    }


def section_hash(section_text):
    """Hash of the managed section, independent of line endings and trailing blank lines."""
    return sha256_text(normalise_eol(section_text).rstrip() + "\n")


def story_number(story_id):
    return int(STORY_ID_RE.match(story_id).group(1))


def format_story_id(number):
    return f"US-{number:03d}"


def requirement_number(req_id):
    return int(REQ_ID_RE.match(req_id).group(1))


def decode_document(raw):
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = (raw[3:] if bom else raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refused(
            f"The document is not valid UTF-8 ({exc}). Phase 3 only edits UTF-8 files so the encoding is preserved; "
            "convert the file to UTF-8 or choose another document."
        )
    return text, bom


# ----------------------------------------------------------- Markdown structure scanning

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_H1_RE = re.compile(r"^ {0,3}=+[ \t]*$")


def iter_structure(lines):
    """Yield (index, offset, line, masked). Masked lines are inside a code fence or an HTML comment."""
    fence = None
    in_comment = False
    offset = 0
    for index, line in enumerate(lines):
        body = strip_eol(line)
        masked = False
        if fence is not None:
            masked = True
            closing = _FENCE_CLOSE_RE.match(body)
            if closing and closing.group(1)[0] == fence[0] and len(closing.group(1)) >= len(fence):
                fence = None
        elif in_comment:
            masked = True
            if "-->" in body:
                in_comment = False
        else:
            opening = _FENCE_OPEN_RE.match(body)
            if opening:
                fence = opening.group(1)
                masked = True
            elif "<!--" in body:
                tail = body.split("<!--", 1)[1]
                if "-->" not in tail:
                    in_comment = True
                masked = body.lstrip().startswith("<!--")
        yield index, offset, line, masked
        offset += len(line)


def heading_of(body):
    """Return (level, title) for an ATX heading line, else None."""
    match = _HEADING_RE.match(body)
    if not match:
        return None
    title = re.sub(r"[ \t]+#+$", "", match.group(2) or "")
    if match.group(2) is not None and re.fullmatch(r"#+", match.group(2).strip()):
        title = ""
    return len(match.group(1)), title.strip()


class SectionAmbiguous(Exception):
    """The Development Stories section cannot be located safely."""


def _level_one_headings(lines):
    found = []
    entries = list(iter_structure(lines))
    skip_next = False
    for position, (index, offset, line, masked) in enumerate(entries):
        if skip_next:
            skip_next = False
            continue
        if masked:
            continue
        body = strip_eol(line)
        heading = heading_of(body)
        if heading and heading[0] == 1:
            found.append({"index": index, "offset": offset, "title": heading[1], "kind": "atx"})
            continue
        if body.strip() and not body.startswith("    ") and position + 1 < len(entries):
            nxt = entries[position + 1]
            if not nxt[3] and _SETEXT_H1_RE.match(strip_eol(nxt[2])):
                found.append({"index": index, "offset": offset, "title": body.strip(), "kind": "setext"})
                skip_next = True
    return found


def locate_section(text):
    """Find the managed '# Development Stories' section.

    Returns {"state": "absent"} or {"state": "present", "start": offset, "line": 1-based, "prefix", "section"}.
    The managed section always runs to the end of the document. Raises SectionAmbiguous when it
    cannot be located safely (duplicates, look-alike headings, or any top-level heading after it).
    """
    lines = split_lines(text)
    headings = _level_one_headings(lines)
    exact = [h for h in headings if collapse(h["title"]) == SECTION_TITLE]
    lookalike = [h for h in headings if collapse(h["title"]).casefold() == SECTION_TITLE.casefold() and h not in exact]
    if lookalike:
        raise SectionAmbiguous(
            f"Line {lookalike[0]['index'] + 1} has a heading that looks like the managed section but is not exactly "
            f"'# {SECTION_TITLE}'. Rename or remove it before Phase 3 can safely update the document."
        )
    if not exact:
        return {"state": "absent"}
    if len(exact) > 1:
        raise SectionAmbiguous(
            f"The document has {len(exact)} '# {SECTION_TITLE}' headings (lines "
            + ", ".join(str(h["index"] + 1) for h in exact)
            + "). Remove the duplicates by hand; Phase 3 will not guess which one to keep."
        )
    mine = exact[0]
    if mine["kind"] == "setext":
        raise SectionAmbiguous(
            f"The '{SECTION_TITLE}' heading on line {mine['index'] + 1} uses underline style. Change it to '# {SECTION_TITLE}'."
        )
    later = [h for h in headings if h["offset"] > mine["offset"]]
    if later:
        raise SectionAmbiguous(
            f"The top-level heading '{later[0]['title']}' (line {later[0]['index'] + 1}) comes after '# {SECTION_TITLE}'. "
            "The managed section must be the last section of the document so no other content can be consumed. "
            "Move that content above the section, or tell Phase 3 which document should hold the stories."
        )
    return {
        "state": "present",
        "start": mine["offset"],
        "line": mine["index"] + 1,
        "prefix": text[: mine["offset"]],
        "section": text[mine["offset"] :],
    }


# ------------------------------------------------------------- story parsing and rendering

_LABEL_RE = re.compile(r"^\*\*([^*\n]+?):\*\*[ \t]*(.*)$")
_ITEM_RE = re.compile(r"^ ?(?:[0-9]{1,4}[.)]|[-*+])[ \t]+(.*)$")
FIELD_LABELS = {"Summary": "summary", "Detailed Description": "description", "Acceptance Criteria": "criteria"}
FIELD_ORDER = ("summary", "description", "criteria")


def _parse_criteria(lines, problems, where):
    items = []
    current = None
    after_blank = False
    for body in lines:
        if not body.strip():
            after_blank = True
            continue
        match = _ITEM_RE.match(body)
        if match:
            current = [match.group(1)]
            items.append(current)
        elif current is not None and (body[:1] in (" ", "\t") or not after_blank):
            current.append(body.strip())
        else:
            problems.append(f"{where}: text outside a numbered acceptance criterion: {body.strip()[:60]!r}.")
        after_blank = False
    criteria = []
    for item in items:
        text = collapse(" ".join(item))
        if not text:
            problems.append(f"{where}: an acceptance criterion is empty.")
        else:
            criteria.append(text)
    return criteria


def _parse_block(block, problems):
    story_id = block["story_id"]
    where = f"{story_id} (line {block['line']})"
    buckets = {"summary": [], "description": [], "criteria": []}
    seen = []
    field = None
    for body, masked in block["body"]:
        if not masked:
            match = _LABEL_RE.match(body)
            if match:
                label = match.group(1).strip()
                key = FIELD_LABELS.get(label)
                if key is None:
                    problems.append(
                        f"{where}: extra story field '{label}'. A story holds only Summary, Detailed Description and "
                        "Acceptance Criteria; traceability lives in stories/story-generation-state.json."
                    )
                    field = "ignored"
                    continue
                if key in seen:
                    problems.append(f"{where}: the '{label}' field appears more than once.")
                elif seen and FIELD_ORDER.index(key) < FIELD_ORDER.index(seen[-1]):
                    problems.append(f"{where}: '{label}' is out of order (Summary, Detailed Description, Acceptance Criteria).")
                seen.append(key)
                field = key
                if match.group(2).strip():
                    buckets[key].append(match.group(2))
                continue
        if field is None:
            if body.strip():
                problems.append(f"{where}: text before the Summary field: {body.strip()[:60]!r}.")
        elif field != "ignored":
            buckets[field].append(body)
    for key, label in (("summary", "Summary"), ("description", "Detailed Description"), ("criteria", "Acceptance Criteria")):
        if key not in seen:
            problems.append(f"{where}: the '{label}' field is missing.")
    summary = collapse(" ".join(buckets["summary"]))
    description = canonical_description("\n".join(buckets["description"]))
    criteria = _parse_criteria(buckets["criteria"], problems, where)
    if "summary" in seen and not summary:
        problems.append(f"{where}: the Summary is empty.")
    if "description" in seen and not description:
        problems.append(f"{where}: the Detailed Description is empty.")
    if "criteria" in seen and not criteria:
        problems.append(f"{where}: there is no acceptance criterion.")
    raw_lines = [block["heading_line"]] + [body_line for body_line in block["raw_body"]]
    while raw_lines and not strip_eol(raw_lines[-1]).strip():
        raw_lines.pop()
    return {
        "story_id": story_id,
        "summary": summary,
        "description": description,
        "acceptance_criteria": criteria,
        "line": block["line"],
        "raw": normalise_eol("".join(raw_lines)).rstrip("\n"),
    }


def parse_section(section_text, base_line=1):
    """Parse the managed section. Returns (stories, problems); problems are human-readable strings."""
    lines = split_lines(section_text)
    problems = []
    blocks = []
    current = None
    for index, offset, line, masked in iter_structure(lines):
        body = strip_eol(line)
        line_no = base_line + index
        if index == 0:
            continue
        heading = None if masked else heading_of(body)
        if heading:
            level, title = heading
            if level == 2:
                if not STORY_ID_RE.match(title):
                    problems.append(f"line {line_no}: the heading '## {title}' is not a valid story ID (expected US-001 style).")
                current = {"story_id": title, "line": line_no, "heading_line": line, "body": [], "raw_body": []}
                blocks.append(current)
                continue
            problems.append(f"line {line_no}: unexpected heading '{'#' * level} {title}' inside the Development Stories section.")
            if current is not None:
                current["body"].append((body, masked))
                current["raw_body"].append(line)
            continue
        if current is None:
            if body.strip():
                problems.append(f"line {line_no}: unexpected content before the first story: {body.strip()[:60]!r}.")
            continue
        current["body"].append((body, masked))
        current["raw_body"].append(line)
    stories = []
    seen_ids = {}
    for block in blocks:
        story = _parse_block(block, problems)
        if story["story_id"] in seen_ids:
            problems.append(f"{story['story_id']} (line {block['line']}): duplicate story ID (first on line {seen_ids[story['story_id']]}).")
        else:
            seen_ids[story["story_id"]] = block["line"]
        stories.append(story)
    return stories, problems


def _wrap(text, initial="", subsequent=""):
    return textwrap.fill(
        text, width=WRAP_WIDTH, initial_indent=initial, subsequent_indent=subsequent,
        break_long_words=False, break_on_hyphens=False,
    )


def render_story(story):
    c = canonical_story(story)
    out = [f"## {story['story_id']}", "", f"**Summary:** {c['summary']}", "", "**Detailed Description:**"]
    for position, paragraph in enumerate(c["description"].split("\n\n")):
        if position:
            out.append("")
        out.append(_wrap(paragraph))
    out += ["", "**Acceptance Criteria:**", ""]
    for number, criterion in enumerate(c["acceptance_criteria"], start=1):
        prefix = f"{number}. "
        out.append(_wrap(criterion, prefix, " " * len(prefix)))
        out.append("")
    return "\n".join(out[:-1])


def render_section(blocks):
    return f"# {SECTION_TITLE}\n\n" + "\n\n".join(blocks) + "\n"


# ------------------------------------------------------------------------ document model


class Document:
    """A requirements Markdown document, split into the content outside and inside the managed section."""

    def __init__(self, path, raw):
        self.path = path
        self.raw = raw
        self.sha256 = sha256_bytes(raw)
        self.text, self.bom = decode_document(raw)
        self.eol = detect_eol(self.text)
        self.ambiguity = None
        self.section_state = "absent"
        self.prefix = self.text
        self.section = ""
        self.stories = []
        self.problems = []
        try:
            located = locate_section(self.text)
        except SectionAmbiguous as exc:
            self.ambiguity = str(exc)
            self.section_state = "ambiguous"
            return
        self.section_state = located["state"]
        if located["state"] == "present":
            self.prefix = located["prefix"]
            self.section = located["section"]
            self.stories, self.problems = parse_section(self.section, located["line"])

    @property
    def outside_hash(self):
        return sha256_text(self.prefix)

    @property
    def section_hash(self):
        return section_hash(self.section) if self.section_state == "present" else None


def read_document(path):
    return Document(path, read_bytes(path))


def compose_document(doc, section_lf):
    """The full document text with the managed section replaced or appended. Everything else is untouched."""
    section = section_lf.replace("\n", doc.eol)
    if doc.section_state == "present":
        return doc.prefix + section
    text = doc.text
    if not text:
        return section
    separator = ""
    if not text.endswith(("\n", "\r")):
        separator += doc.eol
    lines = split_lines(text + separator)
    if lines and strip_eol(lines[-1]).strip():
        separator += doc.eol
    return text + separator + section


def document_bytes(doc, text):
    return (b"\xef\xbb\xbf" if doc.bom else b"") + text.encode("utf-8")


# ------------------------------------------------------------------------- input loading


def load_atomic(paths):
    """Return (status, errors, requirements {id: item}, raw). status is None when usable."""
    if not os.path.isfile(paths.requirements):
        return "INPUT_MISSING", [f"{paths.requirements} does not exist. Run /sdlc-pipeline:ba-start-analysis (Phase 1) first."], None, None
    try:
        raw = read_bytes(paths.requirements)
        text = raw.decode("utf-8-sig")
    except (IOFailure, UnicodeDecodeError) as exc:
        return "INPUT_INVALID", [f"cannot read atomic requirements: {exc}"], None, None
    duplicate_keys = []
    try:
        data = atomic_validator.parse_json(text, duplicate_keys)
    except ValueError as exc:
        return "INPUT_INVALID", [f"invalid JSON: {exc}."], None, raw
    if isinstance(data, list) and not data:
        return "INPUT_EMPTY", ["The atomic requirements array is empty; there is nothing to write stories for."], None, raw
    errors = atomic_validator.validate(data, duplicate_keys, check_sequence=False)
    if errors:
        return "INPUT_INVALID", errors, None, raw
    return None, [], {item["requirement_id"]: item for item in data}, raw


def requirement_fingerprint(item):
    return sha256_text(json.dumps([item["title"], item["description"]], ensure_ascii=False))


def load_gaps(paths, requirements, ignore=False):
    """Load the optional gap register. Returns a dict with status OK | MISSING | INVALID | IGNORED."""
    result = {"status": "MISSING", "register": None, "errors": [], "warnings": [], "sha256": None}
    if ignore:
        result["status"] = "IGNORED"
        return result
    if not os.path.isfile(paths.register):
        return result
    try:
        raw = read_bytes(paths.register)
        data, duplicate_keys = gap_validator.read_json(paths.register)
    except (IOFailure, gap_validator.InputError) as exc:
        result.update(status="INVALID", errors=[str(exc)])
        return result
    descriptions = None if requirements is None else {k: v["description"] for k, v in requirements.items()}
    errors, warnings = gap_validator.validate_register(data, duplicate_keys, descriptions, allow_stale=True)
    result["warnings"] = warnings
    if errors:
        result.update(status="INVALID", errors=errors)
        return result
    result.update(status="OK", register=data, sha256=sha256_bytes(raw))
    return result


def derive_related_gaps(register, source_ids):
    """Gap IDs whose affected requirements include any of the given requirement IDs."""
    wanted = set(source_ids)
    return sorted(
        (gap["gap_id"] for gap in register or [] if wanted & {ref["requirement_id"] for ref in gap["affected_requirements"]}),
        key=lambda gap_id: int(GAP_ID_RE.match(gap_id).group(1)),
    )


def decision_version(gap):
    """Identify the current (latest) decision of a gap, or None if it has none."""
    if not gap["decisions_recorded"]:
        return None
    latest = gap["decisions_recorded"][-1]
    return {"recorded_at": latest["recorded_at"], "decision_sha256": sha256_text(latest["decision"])}


# ------------------------------------------------------------------------------ state

_STATE_REQUIRED = ("schema_version", "target_document", "last_successful_sync", "source_document_hash",
                   "managed_section_hash", "atomic_requirements_hash", "stories")


def check_state(state):
    errors = []
    if not isinstance(state, dict):
        return ["The state root must be a JSON object."]
    for key in _STATE_REQUIRED:
        if key not in state:
            errors.append(f"missing property: {key}.")
    if errors:
        return errors
    if state["schema_version"] != STATE_SCHEMA_VERSION:
        errors.append(f"unsupported schema_version {state['schema_version']!r} (expected {STATE_SCHEMA_VERSION}).")
    for key in ("target_document", "source_document_hash", "managed_section_hash", "atomic_requirements_hash"):
        if not isinstance(state[key], str) or not state[key].strip():
            errors.append(f"'{key}' must be a non-empty string.")
    if not isinstance(state["stories"], list):
        errors.append("'stories' must be an array.")
        return errors
    seen = set()
    for position, entry in enumerate(state["stories"], start=1):
        label = f"stories[{position}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object.")
            continue
        story_id = entry.get("story_id")
        if not isinstance(story_id, str) or not STORY_ID_RE.match(story_id):
            errors.append(f"{label}: story_id must match ^US-[0-9]{{3,}}$.")
        elif story_id in seen:
            errors.append(f"{label}: duplicate story_id {story_id}.")
        else:
            seen.add(story_id)
        if not isinstance(entry.get("story_content_hash"), str):
            errors.append(f"{label}: story_content_hash must be a string.")
        for key in ("source_requirement_ids", "related_gap_ids", "applied_decisions"):
            if not isinstance(entry.get(key, []), list):
                errors.append(f"{label}: '{key}' must be an array.")
    for key in ("requirement_snapshot", "gap_snapshot", "decision_ledger"):
        if not isinstance(state.get(key, {}), dict):
            errors.append(f"'{key}' must be an object.")
    for key in ("retired_story_ids", "not_covered_requirements"):
        if not isinstance(state.get(key, []), list):
            errors.append(f"'{key}' must be an array.")
    return errors


def load_state(paths):
    """Return (state or None, status NONE | VALID | INVALID, errors)."""
    if not os.path.isfile(paths.state):
        return None, "NONE", []
    try:
        data = json.loads(read_bytes(paths.state).decode("utf-8-sig"))
    except (IOFailure, UnicodeDecodeError, ValueError) as exc:
        return None, "INVALID", [f"cannot read the story state: {exc}"]
    errors = check_state(data)
    if errors:
        return None, "INVALID", errors
    return data, "VALID", []


def target_for_state(paths, target):
    """Store the target relative to the project root when it lies inside it."""
    absolute = os.path.abspath(target)
    try:
        relative = os.path.relpath(absolute, paths.root)
    except ValueError:  # different drive
        return absolute
    if relative.startswith("..") or os.path.isabs(relative):
        return absolute
    return relative.replace(os.sep, "/")


def resolve_target(paths, value):
    return os.path.abspath(os.path.join(paths.root, value))
