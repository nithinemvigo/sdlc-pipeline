#!/usr/bin/env python3
"""Shared helpers for the Phase 3 story scripts (ba-requirements plugin).

Markdown section handling (locate, parse, render, hash) for the ultra-lean stories in the
requirements document and for the consolidated stories/detailed_stories.md, project paths,
safe file writes, and loading of the Phase 1 / Phase 2 inputs and the story state.
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
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SECTION_TITLE = "Development Stories"
DETAILED_FILENAME = "detailed_stories.md"
DETAILED_RELATIVE = "stories/detailed_stories.md"
STATE_SCHEMA_VERSION = "2.0"
SUPPORTED_STATE_VERSIONS = ("2.0",)
STORY_ID_RE = re.compile(r"^US-([0-9]{3,})$")
REQ_ID_RE = re.compile(r"^REQ-([0-9]{3,})$")
GAP_ID_RE = re.compile(r"^GAP-([0-9]{3,})$")


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
        self.detailed_file = os.path.join(self.stories_dir, DETAILED_FILENAME)
        self.backups = os.path.join(self.stories_dir, "backups")
        self.report_dir = os.path.join(self.root, "report")
        self.report = os.path.join(self.report_dir, "phase3-report.html")
        # Left by earlier plugin versions; reported, never read or written.
        self.legacy_detailed_dir = os.path.join(self.stories_dir, "detailed")
        self.legacy_lean_file = os.path.join(self.stories_dir, "lean-stories.md")


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
#
# A story exists in two representations that share one stable Story ID and one Summary:
#
#   * the ultra-lean story in the requirements document: Story ID, Summary, high-level functional
#     acceptance criteria (parse_section / render_lean);
#   * the detailed story in the single file stories/detailed_stories.md: the full functional and
#     non-functional detail (parse_detailed_document / render_detailed).
#
# Both start with the same heading, "## US-001 — Summary". Mappings and hashes live in the state.

HEADING_SEPARATOR = " — "
_STORY_HEADING_RE = re.compile(r"^(US-[0-9]+)(?:[ \t]*(?:—|–|-|:)[ \t]*(.*))?$")
_LABEL_RE = re.compile(r"^\*\*([^*\n]+?):\*\*[ \t]*(.*)$")
_ITEM_RE = re.compile(r"^ ?(?:[0-9]{1,4}[.)]|[-*+])[ \t]+(.*)$")
NOT_SPECIFIED = "Not specified."

# Field specifications: (key, label, kind, required). "text" is one or more paragraphs, "list" a bullet
# list, "numbered" a numbered list, "statement" one inline statement (a bullet list written by an earlier
# plugin version is still read, as several items). The order is the order in the file.
LEAN_FIELDS = (("acceptance_criteria", "Acceptance Criteria", "statement", True),)
LEGACY_FIELDS = (
    ("summary", "Summary", "text", True),
    ("description", "Detailed Description", "text", True),
    ("acceptance_criteria", "Acceptance Criteria", "numbered", True),
)
DETAILED_FIELDS = (
    ("description", "Description", "text", True),
    ("preconditions", "Preconditions", "list", False),
    ("functional_behaviour", "Functional Behaviour", "list", True),
    ("business_rules", "Business Rules", "list", False),
    ("acceptance_criteria", "Acceptance Criteria", "numbered", True),
    ("scenarios", "Alternate and Error Scenarios", "list", False),
    ("non_functional_requirements", "Non-Functional Requirements", "list", False),
    ("dependencies", "Dependencies", "list", False),
)
DETAILED_KEYS = tuple(spec[0] for spec in DETAILED_FIELDS)
DETAILED_LIST_KEYS = tuple(spec[0] for spec in DETAILED_FIELDS if spec[2] != "text")
DETAILED_REQUIRED = tuple(spec[0] for spec in DETAILED_FIELDS if spec[3])
LEGACY_LABELS = ("Summary", "Detailed Description")
DETAILED_TITLE = "Detailed Stories"
DETAILED_NOTE = (
    "<!-- Maintained by the sdlc-pipeline plugin (BA requirements analysis). Each story has the same Story ID and summary as its "
    "entry in the Development Stories section of the requirements document. -->"
)


def split_story_heading(title):
    """Split the text of a '## ' heading into (story_id, summary or None). A heading that is not a story heading is returned whole."""
    match = _STORY_HEADING_RE.match(title.strip())
    if not match:
        return title.strip(), None
    summary = collapse(match.group(2) or "")
    return match.group(1), summary or None


def story_heading(story_id, summary):
    return f"## {story_id}{HEADING_SEPARATOR}{collapse(summary)}"


def _parse_items(lines, problems, where, label):
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
            problems.append(f"{where}: text outside a list item in {label}: {body.strip()[:60]!r}.")
        after_blank = False
    parsed = []
    for item in items:
        text = collapse(" ".join(item))
        if not text:
            problems.append(f"{where}: an item in {label} is empty.")
        else:
            parsed.append(text)
    return parsed


def _read_fields(block, specs, problems, where, hint):
    """Split a story block into its labelled fields. Returns (buckets, seen_keys)."""
    labels = {label: key for key, label, _, _ in specs}
    order = [key for key, _, _, _ in specs]
    buckets = {key: [] for key in order}
    seen = []
    field = None
    for body, masked in block["body"]:
        if not masked:
            match = _LABEL_RE.match(body)
            if match:
                label = match.group(1).strip()
                key = labels.get(label)
                if key is None:
                    problems.append(f"{where}: extra story field '{label}'. {hint}")
                    field = "ignored"
                    continue
                if key in seen:
                    problems.append(f"{where}: the '{label}' field appears more than once.")
                elif seen and order.index(key) < order.index(seen[-1]):
                    problems.append(f"{where}: '{label}' is out of order ({', '.join(spec[1] for spec in specs)}).")
                seen.append(key)
                field = key
                if match.group(2).strip():
                    buckets[key].append(match.group(2))
                continue
        if field is None:
            if body.strip():
                problems.append(f"{where}: text before the first field: {body.strip()[:60]!r}.")
        elif field != "ignored":
            buckets[field].append(body)
    return buckets, seen


def _field_values(specs, buckets, seen, problems, where):
    values = {}
    for key, label, kind, required in specs:
        if kind == "text":
            value = canonical_description("\n".join(buckets[key]))
            empty = not value
        elif kind == "statement" and not any(_ITEM_RE.match(line) for line in buckets[key]):
            statement = collapse(" ".join(buckets[key]))
            value = [statement] if statement else []
            empty = not value
        elif collapse(" ".join(buckets[key])).casefold() == NOT_SPECIFIED.casefold():
            value = []
            empty = True
        else:
            value = _parse_items(buckets[key], problems, where, f"'{label}'")
            empty = not value
        values[key] = value
        if required and key not in seen:
            problems.append(f"{where}: the '{label}' field is missing.")
        elif required and empty:
            problems.append(f"{where}: the '{label}' field is empty.")
    return values


def _raw_block(block):
    raw_lines = [block["heading_line"]] + list(block["raw_body"])
    while raw_lines and not strip_eol(raw_lines[-1]).strip():
        raw_lines.pop()
    return normalise_eol("".join(raw_lines)).rstrip("\n")


def _collect_blocks(lines, base_line, problems, kind):
    """Split a document into story blocks at its '## ' headings. kind is 'lean' or 'detailed'."""
    where = "inside the Development Stories section" if kind == "lean" else "in the detailed stories file"
    blocks = []
    current = None
    title_seen = False
    in_comment = False
    for index, offset, line, masked in iter_structure(lines):
        body = strip_eol(line)
        line_no = base_line + index
        if kind == "lean" and index == 0:
            continue
        if current is None:
            # An HTML comment before the first story (the file's maintenance note) is not content.
            if in_comment:
                in_comment = "-->" not in body
                continue
            if body.lstrip().startswith("<!--"):
                in_comment = "-->" not in body
                continue
        heading = None if masked else heading_of(body)
        if heading:
            level, title = heading
            if level == 2:
                story_id, summary = split_story_heading(title)
                if not STORY_ID_RE.match(story_id):
                    problems.append(f"line {line_no}: the heading '## {title}' is not a valid story heading (expected '## US-001{HEADING_SEPARATOR}Short summary').")
                current = {"story_id": story_id, "summary": summary, "line": line_no, "heading_line": line, "body": [], "raw_body": []}
                blocks.append(current)
                continue
            if kind == "detailed" and level == 1 and not blocks and not title_seen:
                title_seen = True
                continue
            problems.append(f"line {line_no}: unexpected heading '{'#' * level} {title}' {where}.")
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
    return blocks


def _check_unique(stories, blocks, problems):
    seen_ids = {}
    for story, block in zip(stories, blocks):
        if story["story_id"] in seen_ids:
            problems.append(f"{story['story_id']} (line {block['line']}): duplicate story ID (first on line {seen_ids[story['story_id']]}).")
        else:
            seen_ids[story["story_id"]] = block["line"]


def _parse_lean_block(block, problems):
    story_id = block["story_id"]
    where = f"{story_id} (line {block['line']})"
    legacy = any(
        (match := _LABEL_RE.match(body)) and match.group(1).strip() in LEGACY_LABELS
        for body, masked in block["body"] if not masked
    )
    summary = block["summary"] or ""
    if legacy:
        buckets, seen = _read_fields(block, LEGACY_FIELDS, [], where, "")
        legacy_problems = []
        values = _field_values(LEGACY_FIELDS, buckets, seen, legacy_problems, where)
        story = {"story_id": story_id, "summary": collapse(values["summary"]), "acceptance_criteria": values["acceptance_criteria"], "legacy": True}
    else:
        buckets, seen = _read_fields(
            block, LEAN_FIELDS, problems, where,
            "A story in the requirements document holds only the Story ID, the short summary in its heading and the Acceptance Criteria; "
            "detail lives in stories/detailed_stories.md and traceability in stories/story-generation-state.json.",
        )
        values = _field_values(LEAN_FIELDS, buckets, seen, problems, where)
        if not summary:
            problems.append(f"{where}: the heading has no short summary (expected '## {story_id}{HEADING_SEPARATOR}Short summary').")
        story = {"story_id": story_id, "summary": summary, "acceptance_criteria": values["acceptance_criteria"]}
    story.update(line=block["line"], raw=_raw_block(block))
    return story


def parse_section(section_text, base_line=1):
    """Parse the managed section. Returns (stories, problems); problems are human-readable strings."""
    lines = split_lines(section_text)
    problems = []
    blocks = _collect_blocks(lines, base_line, problems, "lean")
    stories = [_parse_lean_block(block, problems) for block in blocks]
    _check_unique(stories, blocks, problems)
    return stories, problems


def _parse_detailed_block(block, problems):
    story_id = block["story_id"]
    where = f"{story_id} (line {block['line']})"
    buckets, seen = _read_fields(
        block, DETAILED_FIELDS, problems, where,
        "A detailed story holds only: " + ", ".join(spec[1] for spec in DETAILED_FIELDS) + "; traceability lives in stories/story-generation-state.json.",
    )
    values = _field_values(DETAILED_FIELDS, buckets, seen, problems, where)
    if not block["summary"]:
        problems.append(f"{where}: the heading has no short summary (expected '## {story_id}{HEADING_SEPARATOR}Short summary').")
    story = {"story_id": story_id, "summary": block["summary"] or "", **values}
    story.update(line=block["line"], raw=_raw_block(block))
    return story


def parse_detailed_document(text):
    """Parse the consolidated detailed stories file. Returns (stories in file order, problems)."""
    lines = split_lines(normalise_eol(text.lstrip("﻿")))
    problems = []
    blocks = _collect_blocks(lines, 1, problems, "detailed")
    stories = [_parse_detailed_block(block, problems) for block in blocks]
    _check_unique(stories, blocks, problems)
    return stories, problems


# --------------------------------------------------- canonical forms, hashes and rendering


def canonical_lean(story):
    return {"summary": collapse(story["summary"]), "acceptance_criteria": [collapse(item) for item in story["acceptance_criteria"]]}


def canonical_detailed(story):
    out = {"summary": collapse(story["summary"]), "description": canonical_description(story["description"])}
    for key in DETAILED_LIST_KEYS:
        out[key] = [collapse(item) for item in story.get(key) or []]
    return out


def lean_hash(story):
    """Hash of the lean story's content only (not its ID), so a renamed story keeps its hash."""
    c = canonical_lean(story)
    return sha256_text(json.dumps([c["summary"], c["acceptance_criteria"]], ensure_ascii=False))


def detailed_hash(story):
    c = canonical_detailed(story)
    return sha256_text(json.dumps([c["summary"], c["description"]] + [c[key] for key in DETAILED_LIST_KEYS], ensure_ascii=False))


def lean_field_hashes(story):
    c = canonical_lean(story)
    return {"summary": sha256_text(c["summary"]), "acceptance_criteria": [sha256_text(item) for item in c["acceptance_criteria"]]}


def render_lean(story):
    """A story of the requirements document: the heading and the acceptance criteria as one statement."""
    c = canonical_lean(story)
    return "\n".join([story_heading(story["story_id"], c["summary"]), "", f"**Acceptance Criteria:** {' '.join(c['acceptance_criteria'])}"])


def render_section(blocks):
    return f"# {SECTION_TITLE}\n\n" + "\n\n".join(blocks) + "\n"


def render_detailed(story):
    """A story of stories/detailed_stories.md. The required fields are always present; an optional field with nothing to say is left out."""
    c = canonical_detailed(story)
    out = [story_heading(story["story_id"], c["summary"]), ""]
    for key, label, kind, required in DETAILED_FIELDS:
        if not required and not c[key]:
            continue
        out.append(f"**{label}:**")
        if kind == "text":
            out.append(c[key])
        elif kind == "numbered":
            out += [f"{number}. {item}" for number, item in enumerate(c[key], start=1)]
        else:
            out += [f"- {item}" for item in c[key]]
        out.append("")
    return "\n".join(out[:-1])


# A dependency on another story is written in a draft as [[Summary of that story]]; it is replaced by the
# story's ID once every story of the draft has one (a new story is only given its ID when the draft is applied).
STORY_REF_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
STORY_ID_IN_TEXT_RE = re.compile(r"\bUS-[0-9]{3,}\b")


def story_reference_key(summary):
    return collapse(summary).casefold()


def resolve_story_references(items, ids_by_summary):
    """Replace every [[Summary]] in the items by 'US-001 (Summary)'. A reference that matches no story is left as it is."""
    def replace(match):
        found = ids_by_summary.get(story_reference_key(match.group(1)))
        return f"{found[0]} ({found[1]})" if found else match.group(0)
    return [STORY_REF_RE.sub(replace, item) for item in items]


def render_detailed_document(blocks):
    return f"# {DETAILED_TITLE}\n\n{DETAILED_NOTE}\n\n" + "\n\n".join(blocks) + "\n"


# --------------------------------------------------- lean and detailed views of a draft item
#
# A draft story (schemas/development-stories.schema.json) carries both representations.


def lean_view(item):
    """The ultra-lean story of a draft item: summary and the one acceptance-criteria statement."""
    return {"story_id": item.get("story_id"), "summary": item["summary"], "acceptance_criteria": list(item["lean_acceptance_criteria"])}


def detailed_view(item):
    """The detailed story of a draft item."""
    detail = item["detailed"]
    view = {"story_id": item.get("story_id"), "summary": item["summary"], "description": detail["description"]}
    for key in DETAILED_LIST_KEYS:
        view[key] = list(detail.get(key) or [])
    return view


def draft_item(lean, detailed):
    """Build a draft story from a story of the document and its detailed story (used by export)."""
    item = {"story_id": lean["story_id"], "summary": lean["summary"], "lean_acceptance_criteria": list(lean["acceptance_criteria"])}
    item["detailed"] = {key: (detailed[key] if key == "description" else list(detailed[key])) for key in DETAILED_KEYS}
    return item


# ------------------------------------------------------------ the detailed stories file


class DetailedFile:
    """stories/detailed_stories.md, read once: its stories (by ID and in file order), problems and hashes."""

    def __init__(self, path, raw):
        self.path = path
        self.exists = raw is not None
        self.raw = raw
        self.stories = {}
        self.order = []
        self.raw_blocks = {}
        self.problems = []
        self.text = ""
        if raw is None:
            return
        try:
            self.text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            self.problems.append(f"stories/detailed_stories.md is not valid UTF-8 ({exc}).")
            return
        stories, self.problems = parse_detailed_document(self.text)
        for story in stories:
            if story["story_id"] in self.stories:
                continue
            self.stories[story["story_id"]] = story
            self.order.append(story["story_id"])
            self.raw_blocks[story["story_id"]] = story["raw"]

    @property
    def file_hash(self):
        if not self.exists:
            return None
        return sha256_text(normalise_eol(self.text).rstrip() + "\n")


def scan_detailed(paths):
    """Read stories/detailed_stories.md. Returns a DetailedFile (exists False when the file is absent)."""
    try:
        raw = read_bytes(paths.detailed_file) if os.path.isfile(paths.detailed_file) else None
    except IOFailure as exc:
        detailed = DetailedFile(paths.detailed_file, None)
        detailed.problems.append(str(exc))
        return detailed
    return DetailedFile(paths.detailed_file, raw)


def scan_legacy_files(paths):
    """Per-story files and mirrors left by earlier plugin versions. They are never read or written any more."""
    found = []
    if os.path.isdir(paths.legacy_detailed_dir):
        found.append("stories/detailed/")
    if os.path.isfile(paths.legacy_lean_file):
        found.append("stories/lean-stories.md")
    try:
        found += sorted(f"stories/{name}" for name in os.listdir(paths.stories_dir) if re.fullmatch(r"US-[0-9]{3,}\.md", name))
    except OSError:
        pass
    return found


def pair_status(doc_stories, detailed, state):
    """How the lean (document) and detailed versions relate to each other and to the last synchronised state.

    detailed: {story_id: detailed story} (DetailedFile.stories)."""
    status = {"detailed_missing": [], "detailed_extra": [], "lean_edited": [], "detailed_edited": [],
              "detailed_untracked": [], "lean_stale": []}
    doc_ids = {s["story_id"] for s in doc_stories}
    status["detailed_missing"] = sorted((i for i in doc_ids if i not in detailed), key=story_number)
    status["detailed_extra"] = sorted((i for i in detailed if i not in doc_ids), key=story_number)
    if not state:
        return status
    entries = {e["story_id"]: e for e in state["stories"]}
    for story in doc_stories:
        story_id = story["story_id"]
        entry = entries.get(story_id)
        if entry is None:
            continue
        if lean_hash(story) != entry["story_content_hash"]:
            status["lean_edited"].append(story_id)
        full = detailed.get(story_id)
        known = entry.get("detailed_content_hash")
        if full is None:
            continue
        if known is None:
            status["detailed_untracked"].append(story_id)
            continue
        if detailed_hash(full) != known:
            status["detailed_edited"].append(story_id)
        if entry.get("lean_derived_from") != known:
            status["lean_stale"].append(story_id)
    status["lean_stale"] = sorted(set(status["lean_stale"]) | set(status["detailed_edited"]), key=story_number)
    return status


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
        self.legacy_ids = []
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
            self.legacy_ids = [story["story_id"] for story in self.stories if story.get("legacy")]

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
    if state["schema_version"] not in SUPPORTED_STATE_VERSIONS:
        errors.append(
            f"unsupported schema_version {state['schema_version']!r} (expected {STATE_SCHEMA_VERSION}); "
            "the state was written by an earlier plugin version and is not used."
        )
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
        for key in ("detailed_content_hash", "lean_derived_from"):
            if entry.get(key) is not None and not isinstance(entry[key], str):
                errors.append(f"{label}: '{key}' must be a string when present.")
        for key in ("source_requirement_ids", "related_gap_ids", "applied_decisions"):
            if not isinstance(entry.get(key, []), list):
                errors.append(f"{label}: '{key}' must be an array.")
    for key in ("detailed_document", "detailed_document_hash"):
        if state.get(key) is not None and not isinstance(state[key], str):
            errors.append(f"'{key}' must be a string when present.")
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
