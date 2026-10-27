#!/usr/bin/env python3
"""Generate the self-contained HTML gap dashboard (ba-requirements plugin, Phase 2).

The report is a read-only view of gaps/gaps.json. It is validated first (the
same checks as validate-gap-register.py); an invalid register produces no
report. All register text is HTML-escaped. The page needs no server, database
or external resource. Its script only shows and hides cards that are already in
the page; it carries no copy of the data.

Usage:
    generate-gap-report.py [--project-root <dir>] [--gaps <gaps.json>]
                           [--requirements <atomic_requirements.json>]
                           [--output <gap-analysis.html>] [--allow-stale]

Defaults are resolved from the project root (default: the current directory):
gaps/gaps.json -> gaps/gap-analysis.html.

Exit status: 0 = report written, 1 = register invalid (no report written),
2 = an input file could not be read or the report could not be written.
"""

import argparse
import html
import importlib.util
import os
import sys
import tempfile
from datetime import datetime

PRIORITIES = ("Critical", "High", "Medium", "Low")
PRIORITY_RANK = {name: rank for rank, name in enumerate(PRIORITIES)}
STATUS_LABEL = {"open": "Open", "resolved": "Resolved", "skipped": "Skipped"}
COLLAPSE_ABOVE = 10  # cards start collapsed when the register is larger than this


def _load_validator():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate-gap-register.py")
    spec = importlib.util.spec_from_file_location("validate_gap_register", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def esc(value):
    return html.escape(str(value), quote=True)


def gap_sort_key(gap):
    return (PRIORITY_RANK[gap["priority"]], int(gap["gap_id"].split("-")[1]))


def render_requirements(gap):
    rows = "".join(
        f'<li><span class="req-id">{esc(ref["requirement_id"])}</span>'
        f'<span class="req-desc">{esc(ref["description"])}</span></li>'
        for ref in gap["affected_requirements"]
    )
    return f'<div class="block"><h4>Affected requirements</h4><ul class="reqs">{rows}</ul></div>'


def render_decisions(gap):
    decisions = gap["decisions_recorded"]
    if not decisions:
        return ""
    resolved = gap["status"] == "resolved"
    items = []
    last = len(decisions) - 1
    for index, decision in enumerate(decisions):
        is_current = index == last
        if is_current and resolved:
            tag = '<span class="tag current">Current decision</span>'
        elif is_current:
            tag = '<span class="tag past">Latest recorded decision</span>'
        else:
            tag = '<span class="tag past">Earlier decision</span>'
        css = "decision current" if (is_current and resolved) else "decision"
        items.append(
            f'<li class="{css}">{tag}<p>{esc(decision["decision"])}</p>'
            f'<time>{esc(decision["recorded_at"])}</time></li>'
        )
    # Newest first so the current decision is the first thing read.
    heading = "Recorded decisions" if resolved else "Decision history (gap was reopened)"
    return f'<div class="block"><h4>{heading}</h4><ul class="decisions">{"".join(reversed(items))}</ul></div>'


def render_gap(gap, expanded):
    search = " ".join(
        [gap["gap_id"], gap["gap_definition"]]
        + [f'{ref["requirement_id"]} {ref["description"]}' for ref in gap["affected_requirements"]]
        + [decision["decision"] for decision in gap["decisions_recorded"]]
    ).lower()
    priority = gap["priority"]
    status = gap["status"]
    req_ids = ", ".join(ref["requirement_id"] for ref in gap["affected_requirements"])
    return (
        f'<article class="gap" id="{esc(gap["gap_id"])}" data-priority="{esc(priority)}" '
        f'data-status="{esc(status)}" data-search="{esc(search)}">'
        f'<details{" open" if expanded else ""}>'
        f'<summary><span class="gap-id">{esc(gap["gap_id"])}</span>'
        f'<span class="badge p-{esc(priority.lower())}">{esc(priority)}</span>'
        f'<span class="badge s-{esc(status)}">{esc(STATUS_LABEL[status])}</span>'
        f'<span class="gap-def">{esc(gap["gap_definition"])}</span>'
        f'<span class="gap-reqs">{esc(req_ids)}</span></summary>'
        f'<div class="body">{render_requirements(gap)}{render_decisions(gap)}</div>'
        f"</details></article>"
    )


def render_section(status, title, note, gaps, expanded):
    cards = "".join(render_gap(gap, expanded) for gap in gaps)
    empty = f'<p class="empty static-empty">No {esc(status)} gaps.</p>' if not gaps else ""
    return (
        f'<section class="status-section" data-section="{status}">'
        f'<h2>{esc(title)} <span class="count" data-count-for="{status}">{len(gaps)}</span></h2>'
        f'<p class="note">{esc(note)}</p>{empty}{cards}'
        f'<p class="empty filter-empty" hidden>No {esc(status)} gaps match the current filters.</p>'
        f"</section>"
    )


def render_distribution(gaps):
    total = len(gaps)
    rows = []
    for priority in PRIORITIES:
        subset = [gap for gap in gaps if gap["priority"] == priority]
        share = (100 * len(subset) / total) if total else 0
        breakdown = ", ".join(
            f"{sum(1 for gap in subset if gap['status'] == status)} {status}" for status in ("open", "skipped", "resolved")
        )
        rows.append(
            f'<div class="dist-row"><span class="dist-label"><span class="badge p-{priority.lower()}">{priority}</span></span>'
            f'<span class="dist-bar"><span class="fill p-{priority.lower()}" style="width:{share:.1f}%"></span></span>'
            f'<span class="dist-n">{len(subset)}</span><span class="dist-detail">{breakdown}</span></div>'
        )
    return "".join(rows)


CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1d2430;--muted:#5d6879;--line:#dde1e8;--accent:#2b5fd9;
--critical:#b3261e;--high:#c25b00;--medium:#8a6d00;--low:#2a6f4d;--open:#2b5fd9;--resolved:#2a6f4d;--skipped:#6b5b95}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
header,main{max-width:1100px;margin:0 auto;padding:0 20px}
header{padding-top:28px}
h1{margin:0;font-size:26px}
.stamp{color:var(--muted);font-size:13px;margin:4px 0 0}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px}
.stat b{display:block;font-size:28px;line-height:1.1}
.stat span{color:var(--muted);font-size:13px}
.stat.open b{color:var(--open)}.stat.resolved b{color:var(--resolved)}.stat.skipped b{color:var(--skipped)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:16px}
.panel h2{margin:0 0 10px;font-size:16px}
.dist-row{display:grid;grid-template-columns:90px 1fr 36px 230px;align-items:center;gap:10px;padding:3px 0}
.dist-bar{background:#eceff3;border-radius:4px;height:10px;overflow:hidden}
.fill{display:block;height:100%}
.dist-n{font-weight:600;text-align:right}.dist-detail{color:var(--muted);font-size:12px}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.controls input,.controls select,.controls button{font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink)}
.controls input{flex:1;min-width:240px}
.controls button{cursor:pointer}.controls button:hover{border-color:var(--accent)}
.shown{color:var(--muted);font-size:13px;margin:8px 0 0}
.status-section h2{font-size:19px;margin:26px 0 2px}
.count{font-size:13px;font-weight:600;background:#e6e9ef;border-radius:10px;padding:1px 9px;vertical-align:middle}
.note{margin:0 0 10px;color:var(--muted);font-size:13px}
.gap{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:8px;margin-bottom:8px}
.gap[data-priority=Critical]{border-left-color:var(--critical)}.gap[data-priority=High]{border-left-color:var(--high)}
.gap[data-priority=Medium]{border-left-color:var(--medium)}.gap[data-priority=Low]{border-left-color:var(--low)}
.gap[hidden]{display:none}
summary{cursor:pointer;padding:10px 14px;display:grid;grid-template-columns:auto auto auto 1fr;gap:4px 10px;align-items:baseline}
summary::-webkit-details-marker{display:none}
.gap-id{font-weight:700;font-family:Consolas,monospace}
.gap-def{grid-column:1/-1;font-size:15px}
.gap-reqs{grid-column:1/-1;font-size:12px;color:var(--muted)}
details[open] .gap-reqs{display:none}
.badge{font-size:12px;font-weight:600;padding:1px 9px;border-radius:10px;color:#fff;white-space:nowrap}
.p-critical{background:var(--critical)}.p-high{background:var(--high)}.p-medium{background:var(--medium)}.p-low{background:var(--low)}
.s-open{background:var(--open)}.s-resolved{background:var(--resolved)}.s-skipped{background:var(--skipped)}
.body{padding:0 14px 12px;border-top:1px solid var(--line)}
.block h4{margin:12px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.reqs,.decisions{list-style:none;margin:0;padding:0}
.reqs li{display:grid;grid-template-columns:90px 1fr;gap:10px;padding:4px 0;border-bottom:1px dashed var(--line)}
.req-id{font-family:Consolas,monospace;font-weight:600}
.decision{border:1px solid var(--line);border-radius:6px;padding:8px 10px;margin-bottom:6px;background:#fafbfc}
.decision.current{border-color:var(--resolved);background:#f1f8f4}
.decision p{margin:4px 0;white-space:pre-wrap}
.decision time{color:var(--muted);font-size:12px}
.tag{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}
.tag.current{color:var(--resolved)}.tag.past{color:var(--muted)}
.empty{color:var(--muted);font-style:italic;margin:6px 2px}
.overall-empty{background:var(--card);border:1px dashed var(--line);border-radius:8px;padding:28px;text-align:center;color:var(--muted)}
footer{max-width:1100px;margin:30px auto;padding:0 20px;color:var(--muted);font-size:12px}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,1fr)}.dist-row{grid-template-columns:80px 1fr 30px}.dist-detail{display:none}}
@media print{.controls,.shown{display:none}.gap details>*{display:block}}
"""

JS = """
(function(){
  var q=document.getElementById('q'),pr=document.getElementById('f-priority'),st=document.getElementById('f-status');
  var gaps=[].slice.call(document.querySelectorAll('.gap'));
  var sections=[].slice.call(document.querySelectorAll('.status-section'));
  var shown=document.getElementById('shown');
  function apply(){
    var term=q.value.trim().toLowerCase(),p=pr.value,s=st.value,visible=0;
    gaps.forEach(function(g){
      var ok=(!term||g.getAttribute('data-search').indexOf(term)!==-1)&&
             (!p||g.getAttribute('data-priority')===p)&&(!s||g.getAttribute('data-status')===s);
      g.hidden=!ok; if(ok)visible++;
    });
    sections.forEach(function(sec){
      var all=sec.querySelectorAll('.gap').length,vis=sec.querySelectorAll('.gap:not([hidden])').length;
      var fe=sec.querySelector('.filter-empty'); if(fe)fe.hidden=!(all>0&&vis===0);
      sec.hidden=(s&&sec.getAttribute('data-section')!==s);
    });
    shown.textContent='Showing '+visible+' of '+gaps.length+' gaps';
  }
  [q,pr,st].forEach(function(el){el.addEventListener('input',apply);el.addEventListener('change',apply);});
  document.getElementById('clear').addEventListener('click',function(){q.value='';pr.value='';st.value='';apply();});
  function toggle(open){gaps.forEach(function(g){g.querySelector('details').open=open;});}
  document.getElementById('expand').addEventListener('click',function(){toggle(true);});
  document.getElementById('collapse').addEventListener('click',function(){toggle(false);});
  apply();
})();
"""


def render_html(gaps, generated_at):
    ordered = sorted(gaps, key=gap_sort_key)
    by_status = {status: [gap for gap in ordered if gap["status"] == status] for status in ("open", "resolved", "skipped")}
    expanded = len(ordered) <= COLLAPSE_ABOVE

    cards = (
        f'<div class="stat"><b>{len(ordered)}</b><span>Total gaps</span></div>'
        f'<div class="stat open"><b>{len(by_status["open"])}</b><span>Open gaps</span></div>'
        f'<div class="stat resolved"><b>{len(by_status["resolved"])}</b><span>Resolved gaps</span></div>'
        f'<div class="stat skipped"><b>{len(by_status["skipped"])}</b><span>Skipped gaps (unresolved)</span></div>'
    )

    if ordered:
        body = (
            render_section("open", "Open Gaps", "Awaiting a decision. Triage them with /sdlc-pipeline:ba-triage-gaps.", by_status["open"], expanded)
            + render_section("resolved", "Resolved Gaps", "A decision was recorded and confirmed.", by_status["resolved"], expanded)
            + render_section("skipped", "Skipped Gaps", "Deferred during triage. These are still unresolved and return in the next triage session.", by_status["skipped"], expanded)
        )
    else:
        body = (
            '<div class="overall-empty"><b>No gaps were identified.</b><br>'
            "The atomic requirements were analysed and no missing or unclear decisions needed clarification.</div>"
        )

    priority_options = "".join(f'<option value="{p}">{p}</option>' for p in PRIORITIES)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gap Analysis Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header>
<h1>Gap Analysis Dashboard</h1>
<p class="stamp">Generated <time>{esc(generated_at)}</time> from gaps/gaps.json &middot; read-only report; triage with /sdlc-pipeline:ba-triage-gaps</p>
<div class="cards">{cards}</div>
<div class="panel"><h2>Priority distribution</h2>{render_distribution(ordered)}</div>
<div class="panel controls" role="search">
<input id="q" type="search" placeholder="Search by gap ID, definition or requirement ID" aria-label="Search gaps">
<select id="f-priority" aria-label="Filter by priority"><option value="">All priorities</option>{priority_options}</select>
<select id="f-status" aria-label="Filter by status"><option value="">All statuses</option><option value="open">Open</option><option value="resolved">Resolved</option><option value="skipped">Skipped</option></select>
<button id="clear" type="button">Clear filters</button>
<button id="expand" type="button">Expand all</button>
<button id="collapse" type="button">Collapse all</button>
</div>
<p class="shown" id="shown"></p>
</header>
<main>
{body}
</main>
<footer>Generated report. The authoritative data is gaps/gaps.json; edits made here are not saved.</footer>
<script>{JS}</script>
</body>
</html>
"""


def atomic_write_text(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=directory, prefix=".gap-report-", suffix=".tmp", delete=False)
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


def generate(gaps_path, output_path, requirements_path=None, allow_stale=False):
    """Validate the register and write the report. Returns (exit_code, message)."""
    try:
        data, duplicate_keys = validator.read_json(gaps_path)
        requirements = None
        note = ""
        req_path = requirements_path or validator.default_requirements_path(gaps_path)
        if os.path.exists(req_path):
            requirements = validator.load_requirements(req_path)
        else:
            note = f" (atomic requirements not found at {req_path}; requirement references were not cross-checked)"
    except validator.InputError as exc:
        return 2, f"FAILED: {exc}"

    errors, _ = validator.validate_register(data, duplicate_keys, requirements, allow_stale)
    if errors:
        lines = [f"FAILED: {gaps_path} is invalid; no report was generated ({len(errors)} error(s))."]
        lines += [f"  - {message}" for message in errors[: validator.MAX_REPORTED]]
        return 1, "\n".join(lines)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        atomic_write_text(output_path, render_html(data, generated_at))
    except OSError as exc:
        return 2, f"FAILED: cannot write {output_path}: {exc}. The JSON register is unchanged; re-run this script to regenerate the report."
    return 0, f"PASSED: wrote {output_path} ({len(data)} gap(s)){note}."


def main():
    parser = argparse.ArgumentParser(description="Generate the HTML gap dashboard from gaps.json.")
    parser.add_argument("--project-root", default=os.getcwd())
    parser.add_argument("--gaps")
    parser.add_argument("--requirements")
    parser.add_argument("--output")
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    root = os.path.abspath(args.project_root)
    gaps_path = args.gaps or os.path.join(root, "gaps", "gaps.json")
    output_path = args.output or os.path.join(os.path.dirname(os.path.abspath(gaps_path)), "gap-analysis.html")
    requirements_path = args.requirements or os.path.join(root, "atomic_requirements", "atomic_requirements.json")

    code, message = generate(gaps_path, output_path, requirements_path, args.allow_stale)
    print(message, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
