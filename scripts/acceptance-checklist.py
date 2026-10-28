#!/usr/bin/env python3
"""Acceptance checklist and report for the /pipeline-all acceptance gate (standard library only).

  build   --out FILE [--export FILE] [--requirements FILE] [--tasks DIR]
          Write the checklist: one item per acceptance criterion.
            --export        the stories export JSON (sync-development-stories.py export --draft-out):
                            items US-001.1, US-001.2, ... from each story's detailed acceptance criteria
            --requirements  the requirements Markdown: items AC-001, ... from its `### AC-NNN` blocks
            --tasks         a plan directory: items T01.1, ... from the bullets under
                            `## Acceptance criteria` in task-NN-*.md
          At least one source is required.
  render  --checklist FILE --verdicts FILE --out-dir DIR
          Validate the verdicts (exactly one per checklist item; status met | not_met | cannot_verify |
          accepted_followup; `met` needs evidence of type test | qa | code; `accepted_followup` needs
          a note), then write DIR/acceptance-report.md and DIR/acceptance-report.json.

Verdicts file: {"verdicts": [{"id", "status", "evidence": [{"type", "ref", "detail"}], "fix_hint", "note"}]}

Results are printed as JSON. Exit status: 0 = success and nothing open, 1 = render found not_met or
cannot_verify items (reports are still written), 2 = invalid input or a file could not be read/written.
"""

import argparse
import json
import os
import re
import sys
import tempfile

STATUSES = ("met", "not_met", "cannot_verify", "accepted_followup")
EVIDENCE_TYPES = ("test", "qa", "code")
OPEN_STATUSES = ("not_met", "cannot_verify")

AC_HEADING = re.compile(r"^###\s+(AC-\d+)\s*(?:[—–-]+\s*(.*?))?\s*$")
AC_LABEL = re.compile(r"^\*\*(Covers|Given|When|Then):?\*\*:?\s*(.*)$")
ANY_HEADING = re.compile(r"^#{1,3}\s")
TASK_FILE = re.compile(r"^task-(\d+)-.*\.md$")
TASKS_HEADING = re.compile(r"^##\s+Acceptance criteria\s*$", re.IGNORECASE)
LEVEL2_HEADING = re.compile(r"^##\s")
BULLET = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")


class Fail(Exception):
    """Invalid input or an unreadable/unwritable file: exit status 2."""

    def __init__(self, message, problems=None):
        super().__init__(message)
        self.problems = problems or []


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise Fail(f"Cannot read {path}: {exc}")


def read_json(path):
    try:
        return json.loads(read_text(path))
    except ValueError as exc:
        raise Fail(f"{path} is not valid JSON: {exc}")


def atomic_write(path, text):
    """Write to a temporary file in the same directory, flush it to disk, then replace the target."""
    directory = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=directory,
                                             prefix=".acceptance-", suffix=".tmp", delete=False)
        try:
            with handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise Fail(f"Cannot write {path}: {exc}")


def to_json_text(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- build
def story_items(export_path):
    data = read_json(export_path)
    stories = data.get("stories") if isinstance(data, dict) else None
    if not isinstance(stories, list):
        raise Fail(f"{export_path} is not a stories export (expected an object with a `stories` list).")
    missing = [str(s.get("story_id")) for s in stories if isinstance(s, dict) and not isinstance(s.get("detailed"), dict)]
    if missing:
        raise Fail("These stories have no detailed story yet: " + ", ".join(missing)
                   + ". Sync or generate the detailed stories first, then export again.")
    items = []
    for story in stories:
        criteria = story["detailed"].get("acceptance_criteria") or []
        number = 0
        for text in criteria:
            if not isinstance(text, str) or not text.strip():
                continue
            number += 1
            items.append({
                "id": f"{story['story_id']}.{number}",
                "kind": "story",
                "story_id": story["story_id"],
                "summary": story.get("summary", ""),
                "text": text.strip(),
                "source_requirement_ids": list(story.get("source_requirement_ids") or []),
            })
    return items


def requirement_items(requirements_path):
    items = []
    block = None
    for line in read_text(requirements_path).splitlines():
        heading = AC_HEADING.match(line)
        if heading:
            block = {"id": heading.group(1), "name": heading.group(2) or "", "fields": {}, "current": None}
            items.append(block)
            continue
        if ANY_HEADING.match(line):
            block = None
            continue
        if block is None:
            continue
        label = AC_LABEL.match(line)
        if label:
            block["current"] = label.group(1)
            block["fields"][block["current"]] = [label.group(2).strip()]
        elif block["current"] and line.strip():
            block["fields"][block["current"]].append(line.strip())
    result = []
    for block in items:
        fields = {key: " ".join(part for part in parts if part) for key, parts in block["fields"].items()}
        text = " ".join(f"{key} {fields[key]}" for key in ("Given", "When", "Then") if fields.get(key))
        covers = [c.strip() for c in fields.get("Covers", "").split(",") if c.strip()]
        result.append({"id": block["id"], "kind": "requirement", "name": block["name"], "text": text, "covers": covers})
    return result


def task_items(plan_dir):
    if not os.path.isdir(plan_dir):
        raise Fail(f"{plan_dir} is not a directory.")
    files = sorted((TASK_FILE.match(name).group(1), name) for name in os.listdir(plan_dir) if TASK_FILE.match(name))
    items = []
    for number, name in files:
        in_section = False
        index = 0
        for line in read_text(os.path.join(plan_dir, name)).splitlines():
            if TASKS_HEADING.match(line):
                in_section = True
            elif LEVEL2_HEADING.match(line):
                in_section = False
            elif in_section:
                bullet = BULLET.match(line)
                if bullet:
                    index += 1
                    items.append({"id": f"T{number}.{index}", "kind": "task", "task": name, "text": bullet.group(1)})
    return items


def cmd_build(args):
    if not (args.export or args.requirements or args.tasks):
        raise Fail("Give at least one source: --export, --requirements or --tasks.")
    items = []
    if args.export:
        items += story_items(args.export)
    if args.requirements:
        items += requirement_items(args.requirements)
    if args.tasks:
        items += task_items(args.tasks)
    if not items:
        raise Fail("No acceptance criteria found in the given sources.")
    seen, dupes = set(), []
    for item in items:
        if item["id"] in seen and item["id"] not in dupes:
            dupes.append(item["id"])
        seen.add(item["id"])
    if dupes:
        raise Fail("Duplicate criterion IDs: " + ", ".join(dupes))
    atomic_write(args.out, to_json_text({"items": items}))
    return {"ok": True, "checklist": os.path.abspath(args.out), "total": len(items)}, 0


# ---------------------------------------------------------------- render
def load_checklist(path):
    data = read_json(path)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) and i.get("id") for i in items):
        raise Fail(f"{path} is not a checklist (expected an object with an `items` list of items with an `id`).")
    return items


def validate_verdicts(items, verdicts_data):
    """Return (verdicts by id, problems). Every problem is listed, not just the first."""
    problems = []
    raw = verdicts_data.get("verdicts") if isinstance(verdicts_data, dict) else None
    if not isinstance(raw, list):
        return {}, ["The verdicts file must be an object with a `verdicts` list."]
    known = {item["id"] for item in items}
    by_id = {}
    for position, verdict in enumerate(raw, 1):
        if not isinstance(verdict, dict) or not isinstance(verdict.get("id"), str):
            problems.append(f"Verdict #{position} has no `id`.")
            continue
        vid = verdict["id"]
        if vid not in known:
            problems.append(f"{vid}: unknown ID, not in the checklist.")
            continue
        if vid in by_id:
            problems.append(f"{vid}: more than one verdict.")
            continue
        by_id[vid] = verdict
        status = verdict.get("status")
        if status not in STATUSES:
            problems.append(f"{vid}: status {status!r} is not one of {', '.join(STATUSES)}.")
            continue
        if status == "met":
            evidence = verdict.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                problems.append(f"{vid}: `met` needs at least one evidence entry.")
            else:
                for entry in evidence:
                    kind = entry.get("type") if isinstance(entry, dict) else None
                    ref = entry.get("ref") if isinstance(entry, dict) else None
                    if kind not in EVIDENCE_TYPES:
                        problems.append(f"{vid}: evidence type {kind!r} is not one of {', '.join(EVIDENCE_TYPES)}.")
                    elif not isinstance(ref, str) or not ref.strip():
                        problems.append(f"{vid}: evidence entry has no `ref`.")
        if status == "accepted_followup" and not str(verdict.get("note") or "").strip():
            problems.append(f"{vid}: `accepted_followup` needs the client's note.")
    for item in items:
        if item["id"] not in by_id:
            problems.append(f"{item['id']}: no verdict.")
    return by_id, problems


def cell(value):
    return str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("|", "\\|")


def evidence_text(verdict):
    parts = []
    for entry in verdict.get("evidence") or []:
        text = f"{entry.get('type')}: {entry.get('ref')}"
        if entry.get("detail"):
            text += f" ({entry['detail']})"
        parts.append(text)
    if verdict.get("fix_hint"):
        parts.append(f"fix: {verdict['fix_hint']}")
    if verdict.get("note"):
        parts.append(f"note: {verdict['note']}")
    return "; ".join(parts)


def markdown_report(summary, merged):
    lines = [
        "# Acceptance report",
        "",
        f"{summary['met']}/{summary['total']} met · {summary['accepted_followup']} follow-ups"
        f" · {len(summary['open'])} open",
        "",
        "| ID | Criterion | Status | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for item in merged:
        lines.append(f"| {cell(item['id'])} | {cell(item.get('text', ''))} | {cell(item['status'])} | {cell(evidence_text(item))} |")
    return "\n".join(lines) + "\n"


def cmd_render(args):
    items = load_checklist(args.checklist)
    by_id, problems = validate_verdicts(items, read_json(args.verdicts))
    if problems:
        raise Fail(f"The verdicts are invalid ({len(problems)} problems).", problems)
    merged = []
    for item in items:
        verdict = by_id[item["id"]]
        merged.append({**item, "status": verdict["status"], "evidence": verdict.get("evidence") or [],
                       "fix_hint": verdict.get("fix_hint") or "", "note": verdict.get("note") or ""})
    summary = {"total": len(merged)}
    for status in STATUSES:
        summary[status] = sum(1 for m in merged if m["status"] == status)
    summary["open"] = [m["id"] for m in merged if m["status"] in OPEN_STATUSES]
    md_path = os.path.join(args.out_dir, "acceptance-report.md")
    json_path = os.path.join(args.out_dir, "acceptance-report.json")
    atomic_write(md_path, markdown_report(summary, merged))
    atomic_write(json_path, to_json_text({"summary": summary, "items": merged}))
    return {"ok": True, **summary, "report_md": os.path.abspath(md_path), "report_json": os.path.abspath(json_path)}, \
        (1 if summary["open"] else 0)


# ---------------------------------------------------------------- cli
def build_parser():
    parser = argparse.ArgumentParser(description="Acceptance checklist and report for the acceptance gate.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Write the checklist of acceptance criteria.")
    build.add_argument("--export", help="Stories export JSON.")
    build.add_argument("--requirements", help="Requirements Markdown file (section 19 acceptance criteria).")
    build.add_argument("--tasks", help="Plan directory holding task-NN-*.md files.")
    build.add_argument("--out", required=True, help="Checklist JSON to write.")
    render = sub.add_parser("render", help="Validate verdicts and write the acceptance report.")
    render.add_argument("--checklist", required=True)
    render.add_argument("--verdicts", required=True)
    render.add_argument("--out-dir", required=True)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        result, code = {"build": cmd_build, "render": cmd_render}[args.command](args)
    except Fail as exc:
        result, code = {"ok": False, "error": str(exc)}, 2
        if exc.problems:
            result["problems"] = exc.problems
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
