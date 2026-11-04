#!/usr/bin/env python3
"""Generate the consolidated Phase 3 HTML report (ba-requirements plugin).

The report is a read-only view, never a source of truth. It is rebuilt from:
  - the consolidated detailed stories stories/detailed_stories.md (the full functional and
    non-functional story detail; the ultra-lean entries in the requirements document are not shown),
  - gaps/gaps.json (gaps and recorded decisions),
  - stories/story-generation-state.json (target document, traceability, hashes and sync metadata).
The managed '# Development Stories' section of the target document is read only to check that every
story has a matching entry and to report whether the two representations are in sync.

All source text is HTML-escaped. The page is self-contained: no server, CDN, database or
external resource; its small script only filters stories already in the page.
Unavailable values are shown as "Not recorded"; nothing is invented. Mappings are shown in a
separate traceability section and are never added to individual story entries.

Usage:
    generate-phase3-report.py [--project-root DIR]

Writes <project-root>/report/phase3-report.html (temp file, then replace; read back and checked).
A failed run leaves the previous report untouched.

Exit status: 0 = report written and verified, 1 = the report cannot be built (no story state,
document problems), 2 = a file could not be read or the report could not be written.
"""

import argparse
import html
import importlib.util
import os
import re
import sys

NOT_RECORDED = "Not recorded"
PRIORITIES = ("Critical", "High", "Medium", "Low")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
STATUS_LABEL = {"open": "Open", "resolved": "Resolved", "skipped": "Skipped"}
REQUIRED_MARKERS = ('id="overview"', 'id="stories"', 'id="gaps-open"', 'id="gaps-resolved"', 'id="gaps-skipped"', 'id="decisions"')


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


class ReportError(Exception):
    """The report cannot be built from the current project state."""


def esc(value):
    return html.escape(str(value), quote=True)


# ----------------------------------------------------------------------------- model


def build_model(paths):
    state, state_status, state_errors = common.load_state(paths)
    if state is None:
        reason = "There is no story state yet" if state_status == "NONE" else "The story state is invalid (" + "; ".join(state_errors[:3]) + ")"
        raise ReportError(f"{reason}. Run /sdlc-pipeline:ba-generate-stories first.")
    target = common.resolve_target(paths, state["target_document"])
    if not os.path.isfile(target):
        raise ReportError(f"The target document {state['target_document']} was not found. Locate it with /sdlc-pipeline:ba-sync-stories.")
    try:
        doc = common.read_document(target)
    except common.Refused as exc:
        raise ReportError(str(exc))
    if doc.ambiguity:
        raise ReportError(doc.ambiguity)
    if doc.section_state != "present":
        raise ReportError(f"{state['target_document']} has no '# {common.SECTION_TITLE}' section.")

    atomic_status, _, requirements, atomic_raw = common.load_atomic(paths)
    gaps = common.load_gaps(paths, requirements)
    detailed = common.scan_detailed(paths)
    legacy_files = common.scan_legacy_files(paths)
    errors, warnings, pair = validator.validate_story_set(doc.stories, doc.problems, detailed, requirements, state, legacy_files)

    notes = []
    differing = set()
    for key in ("detailed_missing", "detailed_extra", "detailed_untracked", "lean_edited", "lean_stale"):
        differing |= set(pair[key])
    known_hash = state.get("detailed_document_hash")
    file_modified = bool(known_hash) and detailed.exists and detailed.file_hash != known_hash
    out_of_sync = doc.section_hash != state["managed_section_hash"] or bool(differing or pair["detailed_edited"]) or file_modified
    if doc.section_hash != state["managed_section_hash"]:
        notes.append("The Development Stories section in the requirements document was edited since the last synchronisation. Run /sdlc-pipeline:ba-sync-stories to reconcile.")
    if pair["detailed_edited"]:
        notes.append("Detailed stories edited since the last synchronisation: " + ", ".join(pair["detailed_edited"]) + ". Run /sdlc-pipeline:ba-sync-stories to record them.")
    elif file_modified:
        notes.append(f"{common.DETAILED_RELATIVE} was changed since the last synchronisation. Run /sdlc-pipeline:ba-sync-stories to record it.")
    if pair["lean_stale"]:
        notes.append("The requirements document entry needs updating from its detailed story for: " + ", ".join(pair["lean_stale"]) + ". Run /sdlc-pipeline:ba-generate-stories to update it.")
    if not detailed.exists:
        notes.append(f"{common.DETAILED_RELATIVE} does not exist. Run /sdlc-pipeline:ba-generate-stories to create it.")
    elif pair["detailed_missing"]:
        notes.append(f"No detailed story exists in {common.DETAILED_RELATIVE} for: " + ", ".join(pair["detailed_missing"]) + ". Run /sdlc-pipeline:ba-generate-stories to create them.")
    if legacy_files:
        notes.append("Files from an earlier plugin version are no longer used: " + ", ".join(legacy_files) + ".")
    if atomic_status is None and common.sha256_bytes(atomic_raw) != state["atomic_requirements_hash"]:
        notes.append("The atomic requirements changed since the stories were last synchronised.")
    if gaps["status"] == "OK" and state.get("gap_register_hash") and gaps["sha256"] != state["gap_register_hash"]:
        notes.append("The gap register changed since the stories were last synchronised; run /sdlc-pipeline:ba-enrich-stories to review new decisions.")
    return {
        "generated_at": common.now_stamp(),
        "state": state,
        "target": state["target_document"],
        "doc": doc,
        "detailed": detailed,
        "legacy_files": legacy_files,
        "pair": pair,
        "differing": sorted(differing | set(pair["detailed_edited"]), key=common.story_number),
        "requirements": requirements,
        "gaps": gaps,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "notes": notes,
        "out_of_sync": out_of_sync,
    }


# ---------------------------------------------------------------------------- render


_LABEL_PARAGRAPH_RE = re.compile(r"^([A-Z][A-Za-z /&-]{2,40}):\s+(.*)$", re.DOTALL)


def paragraphs(text):
    out = []
    for part in text.split("\n\n"):
        if not part:
            continue
        match = _LABEL_PARAGRAPH_RE.match(part)
        if match:
            out.append(f"<p><b>{esc(match.group(1))}:</b> {esc(match.group(2))}</p>")
        else:
            out.append(f"<p>{esc(part)}</p>")
    return "".join(out)


def pair_badge(story_id, pair):
    """How the story's entry in the requirements document relates to this detailed story."""
    if story_id in pair["detailed_missing"]:
        return '<span class="badge s-missing">No detailed story</span>'
    if story_id in pair["detailed_extra"]:
        return '<span class="badge s-stale">Not in the requirements document</span>'
    if story_id in pair["lean_stale"] or story_id in pair["lean_edited"] or story_id in pair["detailed_untracked"]:
        return '<span class="badge s-stale">Requirements document out of sync</span>'
    return '<span class="badge s-sync">Requirements document in sync</span>'


def story_text(story):
    parts = [story["story_id"], story["summary"], story["description"]]
    for key in common.DETAILED_LIST_KEYS:
        parts += story[key]
    return " ".join(parts).lower()


def render_story(story, pair):
    """A detailed story: its fields, functional and non-functional, in the same order as stories/detailed_stories.md (an empty optional field is left out there and here)."""
    sections = [f'<h4>Description</h4>{paragraphs(story["description"])}']
    for key, label, kind, _ in common.DETAILED_FIELDS:
        if kind == "text":
            continue
        items = story[key]
        if not items:
            continue
        css = ' class="nfr"' if key == "non_functional_requirements" else ""
        tag = "ol" if kind == "numbered" else "ul"
        body = f"<{tag}>" + "".join(f"<li>{esc(item)}</li>" for item in items) + f"</{tag}>"
        sections.append(f"<div{css}><h4>{esc(label)}</h4>{body}</div>")
    return (
        f'<article class="story" id="{esc(story["story_id"])}" data-search="{esc(story_text(story))}">'
        f'<h3><span class="sid">{esc(story["story_id"])}</span> <span class="ssum">{esc(story["summary"])}</span> {pair_badge(story["story_id"], pair)}</h3>'
        f'{"".join(sections)}</article>'
    )


def render_missing_story(story_id, summary, pair):
    """A story that has no detailed story. The shortened requirements-document text is deliberately not substituted."""
    search = f"{story_id} {summary}".lower()
    return (
        f'<article class="story" id="{esc(story_id)}" data-search="{esc(search)}">'
        f'<h3><span class="sid">{esc(story_id)}</span> <span class="ssum">{esc(summary)}</span> {pair_badge(story_id, pair)}</h3>'
        f'<p class="warn">{esc(story_id)} has no detailed story in {esc(common.DETAILED_RELATIVE)}, so its full description and criteria cannot be shown. '
        'Run /sdlc-pipeline:ba-generate-stories to create it.</p></article>'
    )


def story_links(story_ids, doc_ids):
    if not story_ids:
        return '<span class="muted">None recorded</span>'
    parts = []
    for story_id in story_ids:
        if story_id in doc_ids:
            parts.append(f'<a href="#{esc(story_id)}">{esc(story_id)}</a>')
        else:
            parts.append(f'<span class="warn" title="Not in the document">{esc(story_id)}</span>')
    return ", ".join(parts)


def render_gap(gap, stories_by_gap, doc_ids, show_decisions):
    status = gap["status"]
    reqs = "".join(
        f'<li><span class="rid">{esc(ref["requirement_id"])}</span><span>{esc(ref["description"])}</span></li>'
        for ref in gap["affected_requirements"]
    )
    decisions = ""
    if show_decisions:
        decisions = _render_decision_list(gap)
    related = story_links(stories_by_gap.get(gap["gap_id"], []), doc_ids)
    return (
        f'<article class="gap" id="{esc(gap["gap_id"])}" data-status="{esc(status)}">'
        f'<h3><span class="sid">{esc(gap["gap_id"])}</span> '
        f'<span class="badge p-{esc(gap["priority"].lower())}">{esc(gap["priority"])}</span> '
        f'<span class="badge s-{esc(status)}">{esc(STATUS_LABEL[status])}</span></h3>'
        f'<p class="def">{esc(gap["gap_definition"])}</p>'
        f'<h4>Affected requirements</h4><ul class="reqs">{reqs}</ul>'
        f'{decisions}'
        f'<p class="muted">Stories built from these requirements: {related}</p></article>'
    )


def _render_decision_list(gap, heading="Recorded decisions"):
    decisions = gap["decisions_recorded"]
    if not decisions:
        return ""
    resolved = gap["status"] == "resolved"
    last = len(decisions) - 1
    items = []
    for index, decision in enumerate(decisions):
        if index == last and resolved:
            tag = '<span class="tag current">Current decision</span>'
        elif index == last:
            tag = '<span class="tag">Latest recorded decision (gap not resolved)</span>'
        else:
            tag = '<span class="tag">Earlier decision</span>'
        items.append(f'<li>{tag}<p class="dec">{esc(decision["decision"])}</p><time>Recorded {esc(decision["recorded_at"])}</time></li>')
    return f'<h4>{esc(heading)}</h4><ul class="decisions">{"".join(reversed(items))}</ul>'


def render_resolved_gap(gap, stories_by_gap, doc_ids):
    latest = gap["decisions_recorded"][-1]["recorded_at"] if gap["decisions_recorded"] else NOT_RECORDED
    card = render_gap(gap, stories_by_gap, doc_ids, show_decisions=True)
    return card.replace("</h3>", f'</h3><p class="muted">Resolved: <time>{esc(latest)}</time></p>', 1)


def gap_section(section_id, title, note, gaps, gap_ctx, renderer):
    if gap_ctx["status"] != "OK":
        body = f'<p class="unavailable">{esc(unavailable_text(gap_ctx))}</p>'
        count = ""
    else:
        body = "".join(renderer(gap) for gap in gaps) or f'<p class="muted">No {esc(title.lower())}.</p>'
        count = f' <span class="count">{len(gaps)}</span>'
    return f'<section id="{section_id}"><h2>{esc(title)}{count}</h2><p class="note">{esc(note)}</p>{body}</section>'


def unavailable_text(gap_ctx):
    if gap_ctx["status"] == "MISSING":
        return "Gap data is unavailable: gaps/gaps.json does not exist. No gaps or decisions are shown. Run /sdlc-pipeline:ba-analyse-gaps to create the register."
    if gap_ctx["status"] == "INVALID":
        return "Gap data is unavailable: gaps/gaps.json is invalid (" + "; ".join(gap_ctx["errors"][:2]) + "). No gaps or decisions are shown."
    return "Gap data is unavailable."


def ledger_label(gap, ledger):
    version = common.decision_version(gap)
    entry = ledger.get(gap["gap_id"])
    if version is None:
        return "No decision recorded"
    if entry and entry.get("recorded_at") == version["recorded_at"] and entry.get("decision_sha256") == version["decision_sha256"]:
        return "Incorporated in stories" if entry.get("outcome") == "incorporated" else "Reviewed: no story change required"
    return "Pending: not yet reflected in the stories (run /sdlc-pipeline:ba-enrich-stories)"


def render_decisions_section(model, stories_by_gap, doc_ids):
    gap_ctx = model["gaps"]
    if gap_ctx["status"] != "OK":
        return f'<section id="decisions"><h2>Business Decisions</h2><p class="unavailable">{esc(unavailable_text(gap_ctx))}</p></section>'
    ledger = model["state"].get("decision_ledger", {})
    rows = []
    for gap in sorted(gap_ctx["register"], key=lambda g: (PRIORITY_RANK[g["priority"]], int(g["gap_id"].split("-")[1]))):
        if not gap["decisions_recorded"]:
            continue
        reqs = ", ".join(ref["requirement_id"] for ref in gap["affected_requirements"])
        rows.append(
            f'<article class="gap"><h3><span class="sid">{esc(gap["gap_id"])}</span> '
            f'<span class="badge s-{esc(gap["status"])}">{esc(STATUS_LABEL[gap["status"]])}</span></h3>'
            f'<p class="def">{esc(gap["gap_definition"])}</p>'
            f'<p class="muted">Affected requirements: {esc(reqs)} &middot; Story status: {esc(ledger_label(gap, ledger))}</p>'
            f'{_render_decision_list(gap, "Decision history")}'
            f'<p class="muted">Stories built from these requirements: {story_links(stories_by_gap.get(gap["gap_id"], []), doc_ids)}</p></article>'
        )
    body = "".join(rows) or '<p class="muted">No business decisions have been recorded yet.</p>'
    return (
        f'<section id="decisions"><h2>Business Decisions <span class="count">{len(rows)}</span></h2>'
        '<p class="note">Decisions recorded by the user through /sdlc-pipeline:ba-triage-gaps. The latest entry of a resolved gap is its current decision; earlier entries are kept as history.</p>'
        f"{body}</section>"
    )


def render_traceability(model, doc_ids):
    state = model["state"]
    requirements = model["requirements"] or {}
    gap_ctx = model["gaps"]
    statuses = {g["gap_id"]: g["status"] for g in gap_ctx["register"] or []} if gap_ctx["status"] == "OK" else {}
    summaries = {s["story_id"]: s["summary"] for s in model["doc"].stories}
    summaries.update({story_id: story["summary"] for story_id, story in model["detailed"].stories.items()})
    by_req = {}
    discrepancies = []
    state_ids = set()
    story_rows = []
    for entry in state["stories"]:
        state_ids.add(entry["story_id"])
        for req_id in entry.get("source_requirement_ids", []):
            by_req.setdefault(req_id, []).append(entry["story_id"])
        reqs = ", ".join(entry.get("source_requirement_ids", [])) or "None recorded"
        gaps = ", ".join(
            f"{gap_id} ({STATUS_LABEL.get(statuses.get(gap_id), 'status unavailable')})" for gap_id in entry.get("related_gap_ids", [])
        ) or "None"
        applied = ", ".join(entry.get("applied_decisions", [])) or "None"
        story_rows.append(
            f"<tr><td>{story_links([entry['story_id']], doc_ids)}</td><td>{esc(summaries.get(entry['story_id'], NOT_RECORDED))}</td>"
            f"<td>{esc(reqs)}</td><td>{esc(gaps)}</td><td>{esc(applied)}</td></tr>"
        )
    for story_id in sorted(doc_ids - state_ids):
        discrepancies.append(f"{story_id} is in the document but has no recorded mapping.")
    for story_id in sorted(state_ids - doc_ids):
        discrepancies.append(f"{story_id} has a recorded mapping but is not in the document.")
    rows = []
    for req_id in sorted(requirements, key=common.requirement_number):
        title = requirements[req_id]["title"]
        rows.append(f"<tr><td>{esc(req_id)}</td><td>{esc(title)}</td><td>{story_links(by_req.get(req_id, []), doc_ids)}</td></tr>")
    for req_id in sorted(set(by_req) - set(requirements)):
        rows.append(f'<tr><td>{esc(req_id)}</td><td class="warn">No longer in the atomic requirements</td><td>{story_links(by_req[req_id], doc_ids)}</td></tr>')
    not_covered = state.get("not_covered_requirements", [])
    extra = ""
    if not_covered:
        items = "".join(f"<li>{esc(item['requirement_id'])}: {esc(item['reason'])}</li>" for item in not_covered)
        extra = f"<h4>Requirements reported as not suitable for a story</h4><ul>{items}</ul>"
    problems = ""
    if discrepancies:
        problems = '<div class="banner warn-box"><b>Traceability discrepancies</b><ul>' + "".join(f"<li>{esc(d)}</li>" for d in discrepancies) + "</ul></div>"
    return (
        '<section id="traceability"><h2>Traceability</h2>'
        '<p class="note">Requirement-to-story and gap-to-story mappings from the internal story state. They are shown here only; they are not part of the stories.</p>'
        f'{problems}<h4>Stories</h4><div class="tablewrap"><table><thead><tr><th scope="col">Story</th><th scope="col">Summary</th>'
        '<th scope="col">Requirements</th><th scope="col">Gaps</th><th scope="col">Decisions applied</th></tr></thead>'
        f'<tbody>{"".join(story_rows)}</tbody></table></div>'
        f'<h4>Requirements</h4><div class="tablewrap"><table><thead><tr><th scope="col">Requirement</th><th scope="col">Title</th><th scope="col">Stories</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>{extra}</section>'
    )


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1d2430;--muted:#566174;--line:#d6dbe3;--accent:#2b5fd9;--warn:#9a4b00;
--critical:#b3261e;--high:#b4530a;--medium:#7a6000;--low:#26694a;--open:#2b5fd9;--resolved:#26694a;--skipped:#6b5b95;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
a{color:var(--accent)}a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.skip{position:absolute;left:-999px}.skip:focus{left:8px;top:8px;background:var(--card);padding:6px 10px;z-index:9}
header,main,footer{max-width:1040px;margin:0 auto;padding:0 20px}
header{padding-top:26px}h1{margin:0;font-size:26px}
.stamp{color:var(--muted);font-size:13px;margin:4px 0 0}
nav ul{list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;margin:14px 0;padding:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:14px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.stat b{display:block;font-size:26px;line-height:1.1}.stat span{color:var(--muted);font-size:13px}
dl.facts{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:10px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
dl.facts dt{color:var(--muted)}dl.facts dd{margin:0;overflow-wrap:anywhere}
section{margin:30px 0}h2{font-size:20px;margin:0 0 4px}
.count{font-size:13px;font-weight:600;background:var(--line);border-radius:10px;padding:1px 9px;vertical-align:middle}
.note,.muted{color:var(--muted);font-size:13px}.note{margin:0 0 10px}
.story,.gap{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
.gap{border-left:4px solid var(--line)}
.story h3,.gap h3{margin:0 0 6px;font-size:16px}.sid{font-family:Consolas,monospace;font-weight:700}
h4{margin:12px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.nfr{border-left:3px solid var(--accent);padding-left:10px;margin-top:6px}
.story p,.gap p{margin:4px 0}.story ol,.story ul{margin:4px 0 4px 22px;padding:0}.story li{margin:4px 0}
.badge{font-size:12px;font-weight:600;padding:1px 9px;border-radius:10px;color:#fff;white-space:nowrap}
.p-critical{background:var(--critical)}.p-high{background:var(--high)}.p-medium{background:var(--medium)}.p-low{background:var(--low)}
.s-open{background:var(--open)}.s-resolved{background:var(--resolved)}.s-skipped{background:var(--skipped)}
.s-sync{background:var(--resolved)}.s-stale{background:var(--high)}.s-missing{background:var(--critical)}
.reqs,.decisions{list-style:none;margin:0;padding:0}
.reqs li{display:grid;grid-template-columns:84px 1fr;gap:10px;padding:3px 0;border-bottom:1px dashed var(--line)}
.rid{font-family:Consolas,monospace;font-weight:600}
.decisions li{border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin:6px 0}
.dec{white-space:pre-wrap}.tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.tag.current{color:var(--resolved)}time{color:var(--muted);font-size:12px}
.unavailable,.banner{background:var(--card);border:1px dashed var(--line);border-radius:8px;padding:12px 14px}
.warn,.warn-box{color:var(--warn)}.warn-box{border:1px solid var(--warn)}
.tablewrap{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--card)}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
input[type=search]{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--ink);width:100%;max-width:420px}
footer{margin:30px auto;color:var(--muted);font-size:12px}
@media(max-width:640px){dl.facts{grid-template-columns:1fr}.reqs li{grid-template-columns:1fr}}
@media print{input,nav{display:none}}
"""

JS = """
(function(){
  var q=document.getElementById('story-search');if(!q)return;
  var items=[].slice.call(document.querySelectorAll('.story')),shown=document.getElementById('story-shown');
  function apply(){var t=q.value.trim().toLowerCase(),n=0;
    items.forEach(function(s){var ok=!t||s.getAttribute('data-search').indexOf(t)!==-1;s.hidden=!ok;if(ok)n++;});
    shown.textContent=t?('Showing '+n+' of '+items.length+' stories'):'';}
  q.addEventListener('input',apply);
})();
"""


def render_html(model):
    doc = model["doc"]
    state = model["state"]
    gap_ctx = model["gaps"]
    pair = model["pair"]
    detailed = model["detailed"].stories
    lean_by_id = {s["story_id"]: s for s in doc.stories}
    doc_ids = set(lean_by_id) | set(detailed)
    stories = sorted(doc_ids, key=lambda story_id: common.story_number(story_id) if common.STORY_ID_RE.match(story_id) else 10**9)
    stories_by_gap = {}
    for entry in state["stories"]:
        for gap_id in entry.get("related_gap_ids", []):
            stories_by_gap.setdefault(gap_id, []).append(entry["story_id"])

    register = gap_ctx["register"] or []
    by_status = {s: sorted([g for g in register if g["status"] == s], key=lambda g: (PRIORITY_RANK[g["priority"]], int(g["gap_id"].split("-")[1]))) for s in STATUS_LABEL}
    covered = {r for e in state["stories"] for r in e.get("source_requirement_ids", [])}

    if gap_ctx["status"] == "OK":
        gap_cards = "".join(
            f'<div class="stat"><b>{len(by_status[s])}</b><span>{STATUS_LABEL[s]} gaps</span></div>' for s in ("open", "resolved", "skipped")
        ) + f'<div class="stat"><b>{len(register)}</b><span>Total gaps</span></div>'
        gap_fact = f"{len(by_status['open'])} open, {len(by_status['skipped'])} skipped, {len(by_status['resolved'])} resolved"
    else:
        gap_cards = f'<div class="stat"><b>n/a</b><span>Gap data unavailable ({esc(gap_ctx["status"].lower())})</span></div>'
        gap_fact = "Unavailable (" + gap_ctx["status"].lower() + ")"

    if model["validation_errors"]:
        validation = f"Failed ({len(model['validation_errors'])} issue(s))"
    else:
        validation = "Passed"
    issue_list = ""
    if model["validation_errors"]:
        issue_list = '<div class="banner warn-box"><b>Validation issues</b><ul>' + "".join(f"<li>{esc(m)}</li>" for m in model["validation_errors"][:25]) + "</ul></div>"
    note_list = ""
    if model["notes"]:
        note_list = '<div class="banner warn-box"><b>Attention</b><ul>' + "".join(f"<li>{esc(n)}</li>" for n in model["notes"]) + "</ul></div>"
    sync_status = "Out of sync" if model["out_of_sync"] else "In sync"
    total_reqs = len(model["requirements"]) if model["requirements"] else None
    coverage = f"{len(covered)} of {total_reqs}" if total_reqs is not None else str(len(covered))

    stories_html = "".join(
        render_story(detailed[story_id], pair) if story_id in detailed else render_missing_story(story_id, lean_by_id[story_id]["summary"], pair)
        for story_id in stories
    ) or '<p class="muted">There are no stories yet.</p>'
    differing = model["differing"]
    if differing:
        lean_sync = f"Document and detailed stories differ ({len(differing)} stor{'y' if len(differing) == 1 else 'ies'})"
    else:
        lean_sync = "Document and detailed stories match"
    generated = esc(model["generated_at"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Phase 3 Report: Development Stories</title>
<style>{CSS}</style>
</head>
<body data-generated="{generated}">
<a class="skip" href="#overview">Skip to the report</a>
<header>
<h1>Phase 3 Report</h1>
<p class="stamp">Generated <time>{generated}</time> &middot; read-only view of the detailed stories (stories/detailed_stories.md), gaps/gaps.json and recorded decisions</p>
<nav aria-label="Report sections"><ul>
<li><a href="#overview">Overview</a></li><li><a href="#stories">Development Stories</a></li><li><a href="#gaps-open">Open Gaps</a></li>
<li><a href="#gaps-resolved">Resolved Gaps</a></li><li><a href="#gaps-skipped">Skipped Gaps</a></li><li><a href="#decisions">Business Decisions</a></li><li><a href="#traceability">Traceability</a></li>
</ul></nav>
</header>
<main>
<section id="overview"><h2>Project overview</h2>
<div class="cards"><div class="stat"><b>{len(stories)}</b><span>Development stories</span></div>{gap_cards}</div>
<dl class="facts">
<dt>Report generated</dt><dd>{generated}</dd>
<dt>Target document</dt><dd>{esc(model['target'])}</dd>
<dt>Detailed stories</dt><dd>{len(detailed)} ({esc(common.DETAILED_RELATIVE)})</dd>
<dt>Requirements document</dt><dd>{len(lean_by_id)} ultra-lean stories</dd>
<dt>Gaps</dt><dd>{esc(gap_fact)}</dd>
<dt>Requirements covered</dt><dd>{esc(coverage)}</dd>
<dt>Story validation</dt><dd>{esc(validation)}</dd>
<dt>Synchronisation</dt><dd>{esc(sync_status)} &middot; {esc(lean_sync)}</dd>
<dt>Last synchronised</dt><dd>{esc(state.get('last_successful_sync') or NOT_RECORDED)}</dd>
</dl>{note_list}{issue_list}</section>
<section id="stories"><h2>Development Stories <span class="count">{len(stories)}</span></h2>
<p class="note">Detailed functional and non-functional stories, read from {esc(common.DETAILED_RELATIVE)}. The requirements document {esc(model['target'])} holds only the ultra-lean version of each story. Edit stories in their files, not here.</p>
<p><input id="story-search" type="search" placeholder="Search stories" aria-label="Search stories"> <span id="story-shown" class="muted" aria-live="polite"></span></p>
{stories_html}</section>
{gap_section('gaps-open', 'Open Gaps', 'Awaiting a decision. Stories were written from the requirements as they stand; no answer was assumed.', by_status['open'], gap_ctx, lambda g: render_gap(g, stories_by_gap, doc_ids, show_decisions=True))}
{gap_section('gaps-resolved', 'Resolved Gaps', 'A decision was recorded and confirmed by the user.', by_status['resolved'], gap_ctx, lambda g: render_resolved_gap(g, stories_by_gap, doc_ids))}
{gap_section('gaps-skipped', 'Skipped Gaps', 'Deferred during triage. Still unresolved: a skipped gap is never treated as a decision.', by_status['skipped'], gap_ctx, lambda g: render_gap(g, stories_by_gap, doc_ids, show_decisions=True))}
{render_decisions_section(model, stories_by_gap, doc_ids)}
{render_traceability(model, doc_ids)}
</main>
<footer>Generated report. The authoritative data is the detailed stories in stories/detailed_stories.md and gaps/gaps.json; edits made here are not saved.</footer>
<script>{JS}</script>
</body>
</html>
"""


# ------------------------------------------------------------------------------ write


def generate(paths):
    """Build, write and verify the report. Returns (exit_code, message)."""
    if isinstance(paths, str):
        paths = common.Paths(paths)
    try:
        model = build_model(paths)
    except ReportError as exc:
        return 1, f"FAILED: {exc} The previous report, if any, was left unchanged."
    except (common.IOFailure, common.Refused) as exc:
        return 2, f"FAILED: {exc} The previous report, if any, was left unchanged."
    page = render_html(model)
    try:
        common.atomic_write_bytes(paths.report, page.encode("utf-8"), prefix=".phase3-report-")
        written = common.read_bytes(paths.report).decode("utf-8")
    except (OSError, common.IOFailure) as exc:
        return 2, (f"FAILED: cannot write report/phase3-report.html: {exc}. The stories and state are unchanged and the previous "
                   "report is stale; run generate-phase3-report.py (or /sdlc-pipeline:ba-generate-report) to regenerate it.")
    missing = [marker for marker in REQUIRED_MARKERS if marker not in written]
    if missing or f'data-generated="{esc(model["generated_at"])}"' not in written:
        return 2, "FAILED: the written report did not pass read-back verification (missing sections or timestamp); regenerate it."
    count = len(set(model["detailed"].stories) | {s["story_id"] for s in model["doc"].stories})
    return 0, f"PASSED: wrote report/phase3-report.html ({count} stor{'y' if count == 1 else 'ies'} from stories/detailed_stories.md, generated {model['generated_at']})."


def main():
    parser = argparse.ArgumentParser(description="Generate the Phase 3 HTML report.")
    parser.add_argument("--project-root", default=os.getcwd())
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    code, message = generate(common.Paths(args.project_root))
    print(message, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
