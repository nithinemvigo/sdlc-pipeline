#!/usr/bin/env python3
"""
PreToolUse hook - context budget guard for the sdlc-pipeline.

Purpose
-------
Agent instructions are advisory; a hook is not. Across three measured runs, every
rule below was first written as a prompt instruction and violated anyway.

  0. Don't Read files already in the system prompt (CLAUDE.md, MEMORY.md).
  1. No unbounded full-file Read of a large file. Grep to locate, then Read with
     offset/limit.
  2. No reading an original spec once a distilled `*.contract.md` exists beside it.
  3. No shelling out to measure a markdown file (wc/stat/du/Measure-Object).
  4. An agent may not Read a `*.contract.md` it wrote itself.
  5. No Read of a path this agent already read in this session.
  9. No shell dump (`cat`, `grep -n ""`, `sed -n '1,$p'`) of a file rules 1-2 would deny.
 10. No second full-test-suite run inside one dispatch (targeted runs always allowed).
 11. No loop wrapped around a test command to check for flakiness.

Measured justification: 83 full reads of two documents produced ~9.3M tokens of
re-transmission - 29% of a 32.3M-token, $20.87 session. A single planner spent
~3.3M tokens on 16 `wc -c` calls verifying its own output. In the v2 run the
distiller re-read its own contract 3x and a reviewer re-read its slice twice.

Behaviour
---------
Blocks the call and returns a specific instruction to the model, so it retries the
cheap way rather than giving up. Never blocks small files. Never blocks Grep/Glob.

Install
-------
Copy to `hooks/guard_context_budget.py`, make executable, and register in
`.claude/settings.json` (see hooks/settings.snippet.json).

Tuning
------
MAX_LINES_FULL_READ  - full reads above this many lines are blocked
MAX_BYTES_FULL_READ  - or above this many bytes
ALWAYS_ALLOW         - filename patterns exempt from the line/byte check
CONTRACT_SUFFIX      - the distilled-file suffix that shadows an original
"""

import json
import os
import re
import sys
from fnmatch import fnmatch

MAX_LINES_FULL_READ = 250
MAX_BYTES_FULL_READ = 20_000  # ~6.5k tokens at 3 chars/token

# Files that are ALREADY in every agent's system prompt. Reading them as a file
# pays for the same content twice. Measured: 8 agents did this with CLAUDE.md,
# ~36,000 tokens of pure duplication before re-transmission.
ALREADY_IN_SYSTEM_PROMPT = ["CLAUDE.md", "CLAUDE.local.md", "MEMORY.md"]

# Small, universally needed files - never blocked.
ALWAYS_ALLOW = [
    "*.contract.md",
    "*-slice.md",
    "task-*.md",
    "00-overview.md",
    "package.json",
    "*.json",
    "*.yml",
    "*.yaml",
    "*.snippet.json",
]

# Agents permitted to read a large original document end-to-end.
DISTILLER_AGENTS = {"distiller", "planner"}

CONTRACT_SUFFIX = ".contract.md"


def agent_of(payload) -> str:
    """Normalise the calling agent's role name.

    Confirmed by probe against Claude Code 2.1.217: the field is `agent_type`, and it is
    absent entirely for main-agent calls. `subagent_type`/`agentType` are kept only as
    harmless fallbacks in case the name changes.

    Values seen: "general-purpose" (built-in). Custom plugin agents are expected as
    "sdlc-pipeline:eng-reviewer", but the exact form is unconfirmed - so ROLE_READ_ALLOWLIST
    is matched by substring rather than equality, which tolerates "eng-reviewer",
    "sdlc-pipeline:eng-reviewer" and "sdlc-pipeline_eng-reviewer" alike.
    """
    return str(
        payload.get("agent_type")
        or payload.get("subagent_type")
        or payload.get("agentType")
        or ""
    )


def role_rules(agent_raw: str):
    """Return (role_name, allowlist) for the first role whose name appears in agent_raw."""
    a = agent_raw.replace("_", "-").lower()
    for role, patterns in ROLE_READ_ALLOWLIST.items():
        if role in a:
            return role, patterns
    return None, None


def is_role(agent_raw: str, role: str) -> bool:
    return role in agent_raw.replace("_", "-").lower()


def audit(payload, decision: str, rule: str, path: str) -> None:
    """Append one line per decision so 'the hook did nothing' is never ambiguous again.

    Set GUARD_AUDIT=0 to disable.
    """
    if os.environ.get("GUARD_AUDIT") == "0":
        return
    try:
        line = json.dumps(
            {
                "at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
                "decision": decision,
                "rule": rule,
                "agent": agent_of(payload) or "main",
                "tool": payload.get("tool_name"),
                "target": os.path.basename(path) if path else None,
            }
        )
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-audit.log"),
            "a",
            encoding="utf-8",
        ) as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def deny(reason: str) -> None:
    """Block the tool call and hand the model a corrective instruction."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    # Also emit on stderr so older CLI versions that read exit code 2 behave the same.
    print(reason, file=sys.stderr)
    sys.exit(2)


def allow() -> None:
    sys.exit(0)


def ok(payload, rule: str, path: str = "") -> None:
    """Audit an allow decision, then permit the call.

    Allows are logged too, so an empty guard-audit.log unambiguously means "the hook
    never ran" rather than "the hook ran and found nothing". Four runs were lost to
    that ambiguity.
    """
    audit(payload, "allow", rule, path)
    sys.exit(0)


def basename_matches(path: str, patterns) -> bool:
    base = os.path.basename(path)
    return any(fnmatch(base, p) for p in patterns)


def file_stats(path: str):
    """Return (n_lines, n_bytes) or (None, None) if unreadable."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            lines = sum(1 for _ in fh)
        return lines, size
    except OSError:
        return None, None


# Where a distilled contract may live, relative to the repo. Checked in addition to
# "beside the original", so a spec at the project root and a contract in docs/features/
# still pair up. Without this, an unconventional layout silently disables Rule 2.
CONTRACT_DIRS = ("", "docs/features", "docs", "features")


# Rule 2 applies to prose specification documents only. A distilled contract can only
# ever shadow another *document* - never source code, and never a derived plan artifact.
#
# v6.2: in a real run this rule denied an implementer `product_list_page.dart` and a
# unit-tester `product_list_page_test.dart`, telling both to "read the contract instead"
# for the source file they were being asked to modify. Cause: the fuzzy stem match below
# normalises punctuation away, so `product_list_page.dart` -> `productlistpagedart`,
# which *contains* the contract stem `productlistpage`. Every source file named after the
# feature was therefore unreadable. The agents worked around it with `cat -n`, so the rule
# cost turns and blocked nothing. Both gates below close that.
SPEC_DOC_EXTS = (".md", ".markdown")

# Derived plan artifacts. These are outputs of the pipeline, not the original spec, so a
# contract never shadows them. Checked before Rule 2 - ALWAYS_ALLOW is checked far later
# (Rule 1) and so did not protect them.
DERIVED_ARTIFACTS = ["*.contract.md", "*-slice.md", "*-slice-delta.md", "task-*.md", "00-overview.md"]


def contract_beside(path: str):
    """If `path` is an original spec DOCUMENT that has been distilled, return the contract.

    Matching is by filename stem, and tolerates the distiller shortening the name
    (`01_authentication_product_setup_registration.md` ->
     `auth-product-setup-registration.contract.md`) by also accepting any contract in
    CONTRACT_DIRS whose stem is a substring of the original's, or vice versa.

    Returns None for anything that is not a markdown document, and for derived plan
    artifacts - see SPEC_DOC_EXTS / DERIVED_ARTIFACTS above for why.
    """
    if path.endswith(CONTRACT_SUFFIX):
        return None
    if not os.path.basename(path).lower().endswith(SPEC_DOC_EXTS):
        return None  # source code, tests, config: never shadowed by a contract
    if basename_matches(path, DERIVED_ARTIFACTS):
        return None  # pipeline output, not the original spec
    stem = re.sub(r"\.(md|markdown)$", "", os.path.basename(path), flags=re.IGNORECASE)
    if not stem:
        return None

    # 1. exact stem, beside the original and in the usual doc folders
    directory = os.path.dirname(path)
    for d in (directory,) + CONTRACT_DIRS:
        cand = os.path.join(d, stem + CONTRACT_SUFFIX) if d else stem + CONTRACT_SUFFIX
        if os.path.exists(cand):
            return cand

    # 2. a renamed contract in a known folder whose stem overlaps this one
    norm = re.sub(r"[^a-z0-9]+", "", stem.lower())
    for d in (directory,) + CONTRACT_DIRS:
        if d and not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d or ".")
        except OSError:
            continue
        for e in entries:
            if not e.endswith(CONTRACT_SUFFIX):
                continue
            other = re.sub(r"[^a-z0-9]+", "", e[: -len(CONTRACT_SUFFIX)].lower())
            if len(other) >= 12 and (other in norm or norm in other):
                return os.path.join(d, e) if d else e
    return None


# Agents that authored the contract and must not read it back (Rule 4).
CONTRACT_AUTHORS = {"distiller"}

# Rule 7 - agents that must never read a derived slice. Slices are generated from the
# planner's own task files by the orchestrator, so for the planner they contain nothing new:
# in the v4 run it read `eng-slice.md` three times. Reviewers read slices; nobody else does.
SLICE_FORBIDDEN = {"planner", "distiller", "implementer"}
SLICE_PATTERNS = ["*-slice.md", "*-slice-delta.md"]

# Rule 6 - per-role read allowlist. Prompt instructions told the reviewers to read
# their slice and the contract only. In the v2 run they complied; in the v3 run, with
# byte-identical instructions, both eng-reviewers read the slice AND all nine task
# files AND CLAUDE.md - 235% more tokens. Compliance is not reproducible; this is.
#
# An empty list means "no restriction". Patterns are fnmatch on the basename.
ROLE_READ_ALLOWLIST = {
    "ceo-reviewer": ["ceo-slice*.md", "*.contract.md"],
    "eng-reviewer": ["eng-slice*.md", "*.contract.md"],
    "design-reviewer": ["design-slice*.md", "*.contract.md", "DESIGN_SYSTEM.md"],
}

# Where Rule 5 keeps its per-session record of what each agent has already read.
STATE_DIR = os.path.join(
    os.environ.get("TMPDIR") or os.environ.get("TEMP") or "/tmp", "sdlc_ctx_guard"
)


def _state_path(context_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", context_id)[:120] or "unknown"
    return os.path.join(STATE_DIR, safe + ".json")


def already_read(context_id: str, path: str, tool_input: dict) -> bool:
    """Rule 5 - has THIS context already read this exact window?

    Keyed on `agent_id`, which is unique per subagent dispatch. Keying on the role name
    was a bug: `eng-reviewer` is dispatched twice per run (review, then delta re-review),
    and the second dispatch is a brand-new empty context that legitimately needs the
    contract the first one read. Role-keying blocked it.

    The key also includes the offset/limit window, so a distiller walking a long document
    in 400-line chunks is not blocked - only a genuine repeat of the same window is.

    Best-effort: any filesystem problem returns False so the hook fails open.
    """
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        p = _state_path(context_id)
        seen = []
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                seen = json.load(fh)
        key = "|".join(
            (
                os.path.normcase(os.path.abspath(path)),
                str(tool_input.get("offset", "")),
                str(tool_input.get("limit", "")),
            )
        )
        if key in seen:
            return True
        seen.append(key)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(seen[-400:], fh)
    except Exception:
        return False
    return False


MEASURE_CMD = re.compile(
    r"\b(wc|stat|du|Get-Item|Measure-Object|Get-Content)\b", re.IGNORECASE
)

# Rule 9 (v6.2) - a shell command that dumps a whole file is a `Read` with the guard
# switched off. Measured: 21 such calls in one run (14 by unit-tester, 7 by implementer),
# every one of them immediately after a Read of the same path was denied. The content
# reached the context anyway; the only thing the denial bought was the wasted turn.
#
# This does NOT ban `cat`. It blocks an *unbounded* dump of a file that the read rules
# would have refused. Anything piped into head/tail/grep/wc is bounded and passes.
FULL_DUMP_RE = re.compile(
    r"""(?:^|[;&|]\s*)\s*
        (?:cat|bat|type|Get-Content|gc)\b(?:\s+-[A-Za-z-]+)*\s+   # cat / cat -n / type
      | \bgrep\s+(?:-[A-Za-z]+\s+)*(?:-n\s+)?(?:""|'')\s+       # grep -n "" <file>
      | \bsed\s+-n\s+['"]1,\$?p?['"]\s+                          # sed -n '1,$p'
    """,
    re.IGNORECASE | re.VERBOSE,
)
BOUNDED_PIPE_RE = re.compile(r"\|\s*(head|tail|grep|wc|sed|awk|sort|uniq|jq)\b", re.IGNORECASE)
PATH_TOKEN_RE = re.compile(r"(?:^|\s)((?:[./~]|[A-Za-z]:)[^\s;&|<>'\"]+|[\w./-]+\.[A-Za-z]{1,8})")


def _dump_targets(cmd: str):
    """Candidate file paths a full-dump command is about to print."""
    out = []
    for m in PATH_TOKEN_RE.finditer(cmd):
        tok = m.group(1).strip()
        if tok.startswith("-") or tok.endswith(("/", "*")):
            continue
        if os.path.isfile(tok):
            out.append(tok)
    return out


# Rule 10 (v6.2) - the full test suite, once per dispatch.
# Measured: 17 full-suite runs across one build phase (Task 8 ran it 3x, Task 9 3x) while
# the standing instruction was "targeted tests during implementation, full suite once at
# the end". Each run is a turn, and each turn re-sends the whole accumulated context.
# Targeted runs (a path argument) are always allowed - they are the wanted behaviour.
FULL_SUITE_RE = re.compile(
    r"\b("
    r"flutter\s+test|dart\s+test|npm\s+(?:run\s+)?test|yarn\s+test|pnpm\s+test|"
    r"pytest|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test|jest|vitest|rspec"
    r")\b",
    re.IGNORECASE,
)
# A path-ish argument means the run is scoped, not the whole suite.
TARGETED_RE = re.compile(r"(?:^|\s)(?:[\w./-]*(?:test|spec)[\w./-]*/|[\w./-]+\.(?:dart|py|js|ts|tsx|go|rs|rb|java))\b")
SUITE_EXEMPT = {"qa-tester", "unit-tester"}  # gate roles: verifying the suite IS their job


def check_full_suite(payload) -> None:
    """Rule 10 - block a repeat full-suite run inside one dispatch."""
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not cmd or not FULL_SUITE_RE.search(cmd) or TARGETED_RE.search(cmd):
        return
    agent_raw = agent_of(payload)
    if not agent_raw or any(is_role(agent_raw, r) for r in SUITE_EXEMPT):
        return
    context_id = payload.get("agent_id") or payload.get("agentId")
    if not context_id:
        return
    if already_read(str(context_id), "::full-test-suite::", {}):
        audit(payload, "deny", "10-repeat-full-suite", cmd[:60])
        deny(
            "BLOCKED by context budget guard: you have already run the full test suite "
            "once in this dispatch. Run only the tests for the files you just changed "
            "(pass their paths), and leave the whole-suite run to the test gate that runs "
            "after you return. A full suite re-run costs a turn, and every turn re-sends "
            "your entire accumulated context."
        )


# Rule 11 (v6.3) - do not loop a test to prove it is not flaky.
# Measured: the heaviest implementer dispatch of one run (75 records) ended with
#   for i in 1 2 3; do flutter test <one test file> --plain-name ...; done
# Three executions of a test that had already passed, to check stability. The instinct is
# reasonable and the cost is not: each iteration is a turn, and a turn re-sends the whole
# accumulated context. Flakiness is a real problem, but it belongs to the test gate, which
# runs in a short-lived context, not to an implementer 70 turns deep.
#
# Deliberately narrow: this matches a *loop or repetition construct wrapped around* a test
# command. A plain re-run after an edit is the RED-GREEN cycle and is always allowed - the
# hook cannot tell "re-run after fixing" from "re-run to check flakiness", so it does not try.
LOOP_WRAPPER_RE = re.compile(
    r"""(?:
          \bfor\b[^;]{0,80}\bin\b[^;]{0,80};\s*do\b     # for i in 1 2 3; do
        | \bwhile\b[^;]{0,60};\s*do\b                    # while ...; do
        | \brepeat\s+\d+                                 # zsh: repeat 3
        | \bseq\s+\d+\s*\|\s*xargs                       # seq 3 | xargs
        | \bxargs\s+-[A-Za-z]*n?\d*\s*.*\btest\b         # xargs ... test
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def check_test_loop(payload) -> None:
    """Rule 11 - block a loop/repeat construct wrapped around a test command."""
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not cmd or not FULL_SUITE_RE.search(cmd) or not LOOP_WRAPPER_RE.search(cmd):
        return
    agent_raw = agent_of(payload)
    if not agent_raw or any(is_role(agent_raw, r) for r in SUITE_EXEMPT):
        return  # the gate roles may legitimately hunt flakiness
    audit(payload, "deny", "11-test-loop", cmd[:60])
    deny(
        "BLOCKED by context budget guard: you are about to run the same test repeatedly to "
        "check it is stable. Every iteration is a turn, and every turn re-sends your entire "
        "accumulated context - by this point in a dispatch that is the most expensive thing "
        "you can do for the least new information. A test that passed once is green for your "
        "purposes. If you genuinely suspect flakiness, say so in your DONE report naming the "
        "test, and the test gate will investigate it in a fresh, cheap context."
    )


def check_dump_bypass(payload) -> None:
    """Rule 9 - apply the Read rules to shell commands that dump a whole file."""
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not cmd or not FULL_DUMP_RE.search(cmd) or BOUNDED_PIPE_RE.search(cmd):
        return
    agent_raw = agent_of(payload)
    for target in _dump_targets(cmd):
        contract = contract_beside(target)
        if contract and not any(is_role(agent_raw, r) for r in DISTILLER_AGENTS):
            audit(payload, "deny", "9-dump-bypass-contract", target)
            deny(
                f"BLOCKED by context budget guard: dumping `{os.path.basename(target)}` "
                f"through the shell puts the whole file in your context exactly as a full "
                f"`Read` would - it is the same cost with the guard switched off. That "
                f"document has been distilled; read `{contract}` instead."
            )
        lines, nbytes = file_stats(target)
        if lines is None:
            continue
        if lines > MAX_LINES_FULL_READ or nbytes > MAX_BYTES_FULL_READ:
            audit(payload, "deny", "9-dump-bypass-size", target)
            deny(
                f"BLOCKED by context budget guard: `{os.path.basename(target)}` is "
                f"{lines} lines / {nbytes:,} bytes, and dumping it through the shell costs "
                f"exactly what a full `Read` costs - the guard is not bypassed by changing "
                f"tool. Use `Grep` to find the part you need, then `Read` with `offset` and "
                f"`limit` around the match. If you truly need all of it, say so in "
                f"NEEDS_CONTEXT."
            )
DOC_TARGET = re.compile(r"\.(md|markdown)\b", re.IGNORECASE)
MEASURE_EXEMPT = {"distiller", "orchestrator", ""}


def check_bash(payload) -> None:
    """Rule 3 - measuring a markdown file you just wrote costs a whole turn.

    Observed: one planner made 16 `wc -c` calls verifying its own task files against a
    token cap, at ~110,000 tokens of re-sent context per call - ~3.3M tokens spent
    measuring. Prompt instructions did not prevent it; this does.
    """
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not cmd or not MEASURE_CMD.search(cmd) or not DOC_TARGET.search(cmd):
        return
    agent_raw = agent_of(payload)
    if not agent_raw or any(is_role(agent_raw, r) for r in ("distiller", "orchestrator")):
        return  # main agent does the one authorised size check; distiller sizes its source
    audit(payload, "deny", "3-measure", cmd[:60])
    deny(
        f"BLOCKED by context budget guard: measuring a markdown file costs a full "
        f"context re-send, and you are about to do it mid-task. You can see what you "
        f"just wrote - judge its length by eye against the line guidance in your "
        f"instructions. The orchestrator runs one size check across the whole plan "
        f"directory after you return, in a context that is about to end. Continue "
        f"without measuring."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        allow()  # never break the session on a malformed payload

    tool = payload.get("tool_name")
    if tool in ("Bash", "PowerShell"):
        check_bash(payload)
        check_test_loop(payload)
        check_full_suite(payload)
        check_dump_bypass(payload)
        ok(payload, "shell-ok", str((payload.get("tool_input") or {}).get("command", ""))[:60])

    if tool != "Read":
        allow()

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    if not path:
        allow()

    agent_raw = agent_of(payload)
    agent = agent_raw.split(":")[-1]

    # --- Rule 0: don't re-read what's already in the system prompt ------------
    if basename_matches(path, ALREADY_IN_SYSTEM_PROMPT):
        audit(payload, "deny", "0-in-system-prompt", path)
        deny(
            f"BLOCKED by context budget guard: `{os.path.basename(path)}` is already "
            f"loaded into your system prompt - every subagent inherits it at startup. "
            f"Reading it as a file pays for the same content a second time, and then "
            f"re-sends the duplicate on every subsequent turn. Scroll up: the project "
            f"instructions are already in your context. If you need a specific rule "
            f"you cannot find there, quote what you're looking for in a NEEDS_CONTEXT "
            f"return instead of reading the file."
        )

    # --- Rule 2: a contract file shadows its original -------------------------
    contract = contract_beside(path)
    if contract and not any(is_role(agent_raw, r) for r in DISTILLER_AGENTS):
        audit(payload, "deny", "2-contract-shadows", path)
        deny(
            f"BLOCKED by context budget guard: `{os.path.basename(path)}` has been "
            f"distilled. Read `{contract}` instead - it holds every endpoint, field "
            f"mapping, schema and constraint you need, at about 1/8 the token cost. "
            f"If a fact is genuinely missing from the contract, return NEEDS_CONTEXT "
            f"naming that fact so the orchestrator can have the distiller add it. "
            f"Do not read the original."
        )

    # --- Rule 7: only reviewers read derived slices ---------------------------
    if basename_matches(path, SLICE_PATTERNS) and any(
        is_role(agent_raw, r) for r in SLICE_FORBIDDEN
    ):
        audit(payload, "deny", "7-derived-slice", path)
        deny(
            f"BLOCKED by context budget guard: `{os.path.basename(path)}` is generated "
            f"from your own task files - it contains nothing you did not write. Read the "
            f"specific task file a finding cites, or scroll up to what you already have. "
            f"Slices exist for reviewers only."
        )

    # --- Rule 6: reviewers read their own slice and nothing else --------------
    role, allow_list = role_rules(agent_raw)
    if allow_list and not basename_matches(path, allow_list):
        audit(payload, "deny", "6-role-allowlist", path)
        deny(
            f"BLOCKED by context budget guard: as `{role}` you may read only "
            f"{' or '.join(allow_list)}. `{os.path.basename(path)}` is outside your "
            f"lens - the orchestrator already sliced the plan so you would not have to "
            f"load it. Reading task files individually defeats the slice and costs "
            f"roughly 3x your budget. If your slice is genuinely missing something you "
            f"need, return NEEDS_CONTEXT naming the section."
        )

    # --- Rule 4: you may not read a contract you wrote yourself ---------------
    if any(is_role(agent_raw, r) for r in CONTRACT_AUTHORS) and path.endswith(CONTRACT_SUFFIX):
        audit(payload, "deny", "4-own-output", path)
        deny(
            f"BLOCKED by context budget guard: you wrote `{os.path.basename(path)}` - "
            f"it is already in your context. Reading it back costs a full context "
            f"re-send to learn nothing new. Scroll up to see what you have written so "
            f"far. Append the next section with `Edit` and do not verify."
        )

    # --- Rule 5: no second read of the same path in this context --------------
    # agent_id identifies one subagent dispatch; for main-agent calls fall back to the
    # session. If neither is present we cannot tell contexts apart - skip the rule.
    context_id = payload.get("agent_id") or payload.get("agentId")
    if not context_id:
        sid = payload.get("session_id") or payload.get("sessionId")
        context_id = f"main-{sid}" if sid else None
    if context_id and already_read(str(context_id), path, tool_input):
        audit(payload, "deny", "5-repeat-read", path)
        deny(
            f"BLOCKED by context budget guard: you have already read "
            f"`{os.path.basename(path)}` in this session, so its contents are already "
            f"in your context. Scroll up rather than reading it again - a repeat read "
            f"costs a full context re-send and adds a duplicate copy that is then "
            f"re-sent on every remaining turn."
        )

    # --- Rule 1: no unbounded full read of a large file ----------------------
    has_window = "offset" in tool_input or "limit" in tool_input
    if has_window:
        ok(payload, "windowed-read", path)

    if basename_matches(path, ALWAYS_ALLOW):
        ok(payload, "allowlisted-file", path)

    lines, nbytes = file_stats(path)
    if lines is None:
        ok(payload, "no-such-file", path)  # let the tool report it

    if lines > MAX_LINES_FULL_READ or nbytes > MAX_BYTES_FULL_READ:
        audit(payload, "deny", "1-unbounded-read", path)
        est_tokens = nbytes // 3
        if agent in DISTILLER_AGENTS:
            deny(
                f"BLOCKED by context budget guard: `{os.path.basename(path)}` is "
                f"{lines} lines (~{est_tokens:,} tokens) - too large for one call even "
                f"for you. Read it in sequential chunks: `Read` with "
                f"`offset=1, limit=400`, then `offset=401, limit=400`, and so on, "
                f"distilling as you go. This keeps each turn short enough that the "
                f"prompt cache does not expire between calls."
            )
        deny(
            f"BLOCKED by context budget guard: `{os.path.basename(path)}` is "
            f"{lines} lines / {nbytes:,} bytes (~{est_tokens:,} tokens). A full read "
            f"puts all of it in your context, where it is re-sent on every "
            f"subsequent turn. Instead: (1) `Grep` for the specific symbol, path or "
            f"heading you need, then (2) `Read` this file with `offset` and `limit` "
            f"around the match (~40-80 lines). If you truly need the whole file, "
            f"return NEEDS_CONTEXT and say why."
        )

    ok(payload, "under-limits", path)


if __name__ == "__main__":
    main()
