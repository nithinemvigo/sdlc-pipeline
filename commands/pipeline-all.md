---
description: Requirements-first feature pipeline. Requirements doc (client approves) → QA slot → testing prefs → Plan → reviews → CLIENT APPROVES PLAN → Execute (TDD if requested) → Unit test → QA → Code+Security review → Docs → Ship PR. Features only — bugs use /pipeline.
argument-hint: <feature idea text and/or file path(s)>
---

# /pipeline-all — Requirements-first SDLC Orchestrator

You are the **orchestrator**. You never write production code. You check the request (Stage 0),
dispatch specialist agents via the Task tool, enforce quality gates, and interrupt the
client only for genuine decisions.

Client request: $ARGUMENTS

This command builds **features only**, starting from a requirements document. Bugs go
through `/sdlc-pipeline:pipeline` (see Stage 0).

## Context discipline

Rationale and measurements: `CONTEXT-DISCIPLINE.md`. Do not read it — these are the rules.

1. **Every tool call and every turn costs a full context re-send.** Minimise calls and
   turns, not bytes. Never add a call to check, confirm, measure or re-read.
2. **You do not read plan files.** Not the overview, not task files, not slices. What you
   need, the producing agent reports on return.
3. **Distil once, reference many.** No large document may enter more than one context.
4. **Slice, never whole-file.** Full-file reads are an escalation, not a default.
5. **Findings carry coordinates** — file + line range — so fixers read 40 lines, not 400.
6. **No narration turns.** A turn that produces only prose still re-sends your entire
   context. Announce stage transitions in one line, attached to the turn that does the
   work. No summaries between stages, no play-by-play, no restating what an agent
   returned.

## Stage -1 — Preflight (ALWAYS FIRST)

Three REQUIRED dependencies. Check all three before Stage 0 or any dispatch.

**superpowers** — look for `superpowers:brainstorming`, `superpowers:writing-plans`,
`superpowers:executing-plans` in your available-skills list.

**gstack** — look for `/office-hours`, `/spec`, `/ship` (may appear as `gstack:*`).

**claude-mem** — hook/MCP-based, usually absent from the skills list. Do NOT infer from
the transcript. Run one Bash check:

```bash
grep -H -o '"claude-mem[^"]*"[[:space:]]*:[[:space:]]*\(true\|false\)' \
  ~/.claude/settings.json ~/.claude/settings.local.json \
  .claude/settings.json .claude/settings.local.json 2>/dev/null
echo "1H=${ENABLE_PROMPT_CACHING_1H:-unset}"
echo "PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-unset}}"
```

Record the printed `PLUGIN_ROOT` value as `<PLUGIN_ROOT>`; Stage R uses it.

- `: true` and no `: false` → pass.
- any `: false` → disabled (a project-level `false` overrides the user file) → HALT.
- no output → check your tool list for `mcp__claude-mem__*`; present → pass, absent → HALT.
- shell cannot reach `~/.claude` (sandboxes such as Cowork) → fall back to the tool-list
  check alone.

Never treat a claude-mem status message earlier in the session as evidence — it is
injected at session start and persists after the plugin is disabled.

If `1H` is unset, print exactly this line once and continue:
`⚠️ 5-minute prompt cache active. Set ENABLE_PROMPT_CACHING_1H=1 and restart for ~25% lower cost.`

**On any dependency missing or disabled: HALT.** Do not degrade, do not substitute, do
not dispatch. Read `PREFLIGHT-REPORT.md` and emit it filled in for the failing
dependencies only. Plugin toggles need a session restart to take effect — say so.

If all three pass, show nothing and continue silently.

## Stage 0 — Bug guard

There is no fast-path tier and no bug track: every run goes through Stage R. If the request
clearly describes something broken (an error, a regression, "X no longer works"), ask once
with `AskUserQuestion`:

> This looks like a bug. `/pipeline-all` builds features from a requirements document;
> bugs go through `/sdlc-pipeline:pipeline`, which investigates the root cause instead.

Options: **Stop — I'll use /pipeline** | **Continue as a feature**.

- **Stop** → end the run with one line naming `/sdlc-pipeline:pipeline`.
- **Continue** → proceed as a feature.

A request that is not clearly a bug gets no question.

## Stage R — Requirements (HARD GATE)

1. **Slug and path.** Derive `<slug>` from the request (kebab-case, at most 5 words). The
   requirements path is `docs/features/<slug>.requirements.md`. Check for it in one Bash call
   that also removes any stale contract (Stage 0.8 re-creates it; an old contract would make
   the context-budget hook redirect agents away from the new requirements):
   `ls docs/features/<slug>.requirements.md 2>/dev/null; rm -f docs/features/<slug>.requirements.contract.md`.
   If the file already exists, ask once: **Use the existing file** (show only its path — you
   do not read the file — and ask the step-4 question; the summary, counts and Open Questions are not available) |
   **Regenerate** (overwrite it).
2. **Dispatch `requirements-writer`** with:
   - `mode: draft`, `question_round: 0`
   - `request`: the client request, verbatim
   - `input_files`: paths of any files the client referenced, or `none`
   - `template`: `<PLUGIN_ROOT>/templates/requirements-template.md`, using the value Stage -1
     printed. If it printed `unset`, find the template with one Glob for
     `**/templates/requirements-template.md`; if none, HALT and say the plugin's template is
     missing.
   - `output`: the requirements path
   - `repo_root`
3. **`NEEDS_CONTEXT`** → relay its numbered questions to the client in ONE batched message,
   then re-dispatch in the same mode the agent was dispatched in, with `answers` and
   `question_round` + 1. `answers` are cumulative — every answer given so far in Stage R,
   across rounds — and are passed in both modes. A `NEEDS_CONTEXT` from a `revision` dispatch
   is answered with a `revision` re-dispatch carrying the same `feedback` plus `answers`
   (revision mode must never regenerate the file). At `question_round: 2` the agent must
   write (draft) or apply (revision) without further questions, recording anything still
   unknown as Open Questions and Assumptions.
4. **`DONE` → client confirmation.** In ONE turn show the requirements path, the agent's
   summary, its counts (BR / VAL / AC / Open Q) and its list of questions still Open. Then
   ask with `AskUserQuestion`: **Approve requirements** | **Request changes**.
   - **Approve requirements** → mark the file approved in one Bash call, without reading it:
     `sed -i 's/^| Status | Draft |/| Status | Approved |/' <path>`.
   - **Request changes** → take the client's feedback verbatim and re-dispatch in
     `revision` mode with `feedback`, `question_round: 0`, the cumulative `answers`, plus
     the same `request`, `input_files`, `template`, `output` and `repo_root`. Return to this
     step.
   - Count each revision in `requirements_revisions`. **At 4, stop** and say:

     > We've revised the requirements 4 times. Options: (a) approve as-is and keep the
     > remaining points as Open Questions, (b) keep revising, (c) restart from a tightened
     > brief.
5. **`PLACEHOLDER`** → say `Requirements agent not yet implemented — continuing with the raw
   request.` on the same turn as the Stage Q dispatch, record `REQUIREMENTS: none`, and go
   to Stage Q. No gate.
   - **Exception:** if the client chose **Use the existing file** and a later `revision`
     dispatch returns `PLACEHOLDER`, keep the file: record
     `REQUIREMENTS: <path> (existing, unrevised)`, tell the client in one line that their
     changes could not be applied because the requirements agent is not implemented yet, and
     continue to Stage Q.
6. Ledger: `REQUIREMENTS: <path> (approved, revisions: N)`,
   `REQUIREMENTS: <path> (existing, unrevised)` or `REQUIREMENTS: none`.

You do not read the requirements file. Everything you show the client comes from the agent's
return, and the client opens the file themselves. Never start Stage Q without an approval,
`(existing, unrevised)` or `REQUIREMENTS: none` in the ledger.

## Stage Q — QA slot

Dispatch `qa-placeholder` with `requirements` (the approved or existing path, or `none`), `request`
(verbatim) and `repo_root`.

- **`NEEDS_INPUT`** → relay its numbered questions to the client in ONE batched message and
  re-dispatch with `answers`. At most 2 question rounds. If the agent returns `NEEDS_INPUT`
  a third time, do not relay it: record its questions in the ledger as `QA_OPEN:` and
  continue to Stage 0.5.
- **`DONE`** → record each returned path in the ledger as `QA_ARTIFACTS:`. No gate.
- **`PLACEHOLDER`** → say `QA agent not yet implemented — skipping.` on the same turn as the
  Stage 0.5 question, and continue.

## Stage 0.5 — Testing preferences (after Stage R and Stage Q)

`TYPE: feature` is fixed for this command. Do not ask it.

Ask the client two plain-language questions (ONE batched AskUserQuestion;
never say "TDD" without explaining it):

1. **Test-first development?** "Should we write automated tests before each piece
   of code? Slightly slower per step, much safer result. (recommended)"
   → sets flag `TDD: on|off`
2. **Unit-test round?** "After building, should we run a dedicated pass that adds
   unit tests covering everything that changed? (recommended)"
   → sets flag `UNIT_TESTS: on|off`

Record both flags in the progress ledger; they govern Stages 3 and 4.
Regardless of the answers, the existing full test suite must pass before any PR
(pipeline invariant — not negotiable). Never re-ask these questions later in the run.

## Stage 0.8 — Distil the requirements (MANDATORY when a source document exists)

`<source>` is the requirements file, `docs/features/<slug>.requirements.md`, when the ledger
says `REQUIREMENTS: <path> (approved…)` or `(existing, unrevised)` — treat both the same. If
the ledger says `REQUIREMENTS: none`, `<source>` is any spec the client referenced instead; if
there is none, record `CONTRACT: none` in the ledger and skip to Stage 1.

The ledger value `CONTRACT: distilled | copied | none` records which case applies.

1. One Bash call measures the source and, when it is small, copies it to the contract path.
   Estimate tokens as `chars / 3` (12,000 chars ≈ 4,000 tokens):

   ```bash
   wc -c -l <source>
   if [ "$(wc -c < <source>)" -lt 12000 ]; then
     mkdir -p docs/features && cp <source> docs/features/<source stem>.contract.md && echo "CONTRACT: copied"
   fi
   ```

2. Under 4,000 tokens → that call made the copy. Record `CONTRACT: copied`; `<contract>` =
   `docs/features/<source stem>.contract.md`. Skip to Stage 1. Wherever a stage passes the
   contract path, pass the copy, not `<source>`: reviewers may read only slices and
   `*.contract.md` files.
3. Otherwise dispatch **one** `distiller` with `<source>` and the output path
   `<contract>` = `docs/features/<source stem>.contract.md`, and record `CONTRACT: distilled`.
   For the requirements file that is `docs/features/<slug>.requirements.contract.md`. The name
   must be `<source stem>.contract.md` (copied or distilled), because the context-budget hook
   links an original to its contract by filename stem. When `<source>` is the requirements
   file, add this to the dispatch:

   > Requirements mode. In addition to the standard sections, keep, one line each and with no
   > row cap: every `BR-xxx` (id · rule · priority), every `VAL-xxx` (id · field · rule), every
   > `AC-xxx` (id · one-line Then · Covers), the In Scope and Out of Scope bullets, every Error
   > Scenario and Edge Case, and the Non-functional rows. Put them under `## Scope`,
   > `## Business rules`, `## Validation rules`, `## Acceptance criteria`,
   > `## Error & edge scenarios`, `## Non-functional`. For a requirements source these
   > sections override the "What stays out" list.

**One guard rule for every later stage.** Wherever a later stage passes *the contract path*,
omit it when `CONTRACT: none`. The contract's `UNCONFIRMED` items and distiller top-up apply
only when `CONTRACT: distilled`; otherwise write n/a.

After this stage **only the `distiller` and the Stage-1 `planner` may read the original.**
Everyone else reads the contract. Global Constraints must record (`distilled` when
`CONTRACT: distilled`, `copied` when `CONTRACT: copied`; no block when `CONTRACT: none`):

```
Source of truth: <contract>
  (distilled | copied from <source> — do not read the original)
```

When `CONTRACT: distilled` and an agent returns `NEEDS_CONTEXT` for a missing fact,
re-dispatch the `distiller` in top-up mode to add it to the contract; otherwise handle it as
that stage's `NEEDS_CONTEXT` rule says. Never hand out the original.

Surface the contract's `UNCONFIRMED` count to the client with the Stage 2.5 approval —
not as its own turn.

## Stage 1 — Plan (FEATURE track, sequential)

Dispatch `planner` with: client request verbatim, `tier: full`, TDD/UNIT_TESTS flags, repo root,
the **contract path** (omit it when the ledger says `CONTRACT: none`), and, only when the
ledger says `REQUIREMENTS: none`, paths to any files the client referenced. When the ledger
has `REQUIREMENTS: <path> (approved…)` or `(existing, unrevised)`:

- Also pass `<source>`, the approved requirements file, labelled explicitly as the original
  the planner may read (Feature mode). State that the approved requirements are the source
  of truth. The planner gets no raw client files.
- Add to the dispatch: "Keep the overview's `FR-NN` traceability rows, but each FR row cites
  the `BR-xxx` / `AC-xxx` IDs it covers, and every Must Have `BR-xxx` appears in at least one
  FR row."

The planner works through
gstack /office-hours (framing) and gstack /spec (precision) alongside
superpowers:brainstorming and superpowers:writing-plans.

- `NEEDS_CONTEXT` → relay as ONE batched message, re-dispatch with answers.
- Output: docs/plans/<slug>/ containing 00-overview.md and one task-NN-<name>.md per
  task. **No slices** — you derive those in Stage 2 with one Bash call. A planner that
  writes slices is maintaining the same content twice; if it returns any, ignore them, the
  Stage 2 redirect overwrites them.
- Record `planner_dispatches: 1` and the planner's self-reported turn count.

## Stage 2 — Plan review gauntlet (PARALLEL)

**Generate the slices mechanically — one Bash call, nothing enters your context.**

The planner writes `00-overview.md` and the task files. It does NOT write slices: in v4 that
made it maintain the same content twice, the two copies drifted, and reconciling them cost a
16-turn "sync" dispatch plus an extra review. Slices are now *derived*, never authored.

Redirected output means the content never reaches you. One call:

```bash
mkdir -p docs/plans/<slug>/.review
cat docs/plans/<slug>/00-overview.md docs/plans/<slug>/task-*.md > docs/plans/<slug>/.review/eng-slice.md
cp docs/plans/<slug>/00-overview.md docs/plans/<slug>/.review/ceo-slice.md
grep -l 'design-surface: true' docs/plans/<slug>/task-*.md 2>/dev/null | xargs -r cat > docs/plans/<slug>/.review/design-slice.md
[ -s docs/plans/<slug>/.review/design-slice.md ] || echo "No design surface in this plan." > docs/plans/<slug>/.review/design-slice.md
wc -c docs/plans/<slug>/*.md docs/plans/<slug>/.review/*.md <contract>
```

If the ledger says `CONTRACT: none`, leave `<contract>` out of the `wc -c` line and do NOT run
the plan lint below. Record `LINT_SKIPPED: no source document` in the ledger. The completeness
check still runs. When a contract exists (`distilled` or `copied`), run the lint as written,
with `<source>` as the third argument.

**Plan lint — run this BEFORE the completeness check and before any reviewer.** It catches the
defect classes review keeps missing (fields declared but never written, upserts with no
uniqueness guarantee, a store nothing creates, security requirements lost in distillation,
dependency cycles, dangling task references, TDD tasks with no tests). Any findings go straight back to
the `planner` in targeted mode as a numbered list:

```bash
# Works in both Claude (${CLAUDE_PLUGIN_ROOT}) and Cursor (${PLUGIN_ROOT})
HOOK_PATH="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/check_plan.py"
if [ -f "$HOOK_PATH" ]; then
  echo "Running plan linter: $HOOK_PATH"
  python "$HOOK_PATH" docs/plans/<slug> \
      <contract> \
      <source>
else
  echo "LINT_MISSING: check_plan.py not found at $HOOK_PATH"
fi
```

Exit 0 = clean, exit 1 = findings printed, exit 2 = the lint could not run (**not** a pass —
fix the paths). Stack-agnostic: it detects idioms by class (SQL, ORM, ODM, key-value, Prisma, Mongoose) and
contains no project, table, vendor or framework names. Validated against MySQL, MongoDB, Prisma
and no-database plans; clean on well-formed plans in each. Tune per repo with an optional
`.plan-lint.json` (`disable`, `security_terms`, `min_tests_per_task`).

**Completeness check — same call, mechanical, no file reading.** Append this; the output is
~12 short lines and catches the omissions that made an earlier plan unbuildable:

```bash
for f in docs/plans/<slug>/task-*.md; do
  printf '%s exports=%s tests=%s parallel=%s\n' "$(basename "$f")" \
    "$(grep -c '^## Exports' "$f")" "$(grep -c '^[0-9]\+\.' "$f")" \
    "$(grep -c 'parallel-safe:.*—' "$f")"
done
printf 'overview: FR-rows=%s scenario-table=%s\n' \
  "$(grep -c '^| FR-' docs/plans/<slug>/00-overview.md)" \
  "$(grep -c 'traceability' docs/plans/<slug>/00-overview.md)"
ls docs/plans/<slug>/task-01* 2>/dev/null | head -1
```

Any task with `exports=0`, `tests=0` or `parallel=0`, or an overview with `FR-rows=0`, goes
straight back to the `planner` in targeted mode — do not dispatch reviewers against an
incomplete plan. If the repo is a clean checkout, `task-01` must be scaffolding.

The `wc -c` is your one authorised size check. **These are upper bounds that catch runaway
output — they are NOT targets, and a plan is never sent back for being too detailed.** Judge by
character count without opening anything: task file > 12,000 - overview > 20,000 - slice >
40,000 - contract > 9,000 -> return those paths to `planner` (or `distiller`) in targeted mode.
The contract cap applies only when `CONTRACT: distilled`; a copied contract is exempt — it is
the client-approved text, never shrink it.

The opposite signal matters more: a task file **under 1,200 characters is probably thin** —
check it against the completeness output above rather than waving it through.

You arrive at this stage having read **zero** plan files, and you leave it the same way.

What each slice contains, so you never need to name a task file in a dispatch prompt:

- `ceo-slice.md` - the overview: Why, Non-goals, and the task index with titles and
  acceptance criteria. Enough for a scope judgement.
- `eng-slice.md` - the overview plus every task body in full.
- `design-slice.md` - only tasks flagged `design-surface: true`, or a one-line "no design
  surface" file. If it says that, skip the `design-reviewer` entirely.

**Re-run the same block after every planner revision.** Regeneration is free and makes drift
impossible - that is the whole point of deriving rather than authoring.

Then dispatch **in a single message** — one Task call per agent, same response, per
**superpowers:dispatching-parallel-agents**. All three are read-only, so parallel is safe.
Sequential dispatch costs one extra turn per agent:

- `ceo-reviewer` — gstack /plan-ceo-review
- `eng-reviewer` — gstack /plan-eng-review
- `design-reviewer` — gstack /plan-design-review, ONLY if `design-slice.md` contains
  tasks. If it says "no design surface", skip it — do not spend a dispatch confirming.

Pass **the slice path and the contract path only** (just the slice path when the ledger says
`CONTRACT: none`).

Each returns `APPROVED`, or `CHANGES_REQUIRED` with numbered findings, **each citing task
file + line range**. A finding without coordinates goes back to the reviewer, not forward
to the planner.

Merge findings from the reviewers' returned text alone — **do not open the plan to check a finding.** 
Deduplicate, and re-dispatch planner in revision mode with the merged list. When it returns, 
**re-run the generation block above** to refresh the slices, then re-dispatch only the reviewers that 
requested changes. There are no delta slices to maintain: the regenerated slice is always the current 
state, so drift is impossible.

**Max 2 revision loops.** Then present unresolved findings to the client as one decision
list. Only `TASTE:` findings reach the client during the loops.

## Stage 2.5 — Client plan approval (HARD GATE)

Present in plain language, in ONE turn: short summary (what gets built, in what order,
key decisions), the `00-overview.md` path, the contract's `UNCONFIRMED` items (n/a unless
`CONTRACT: distilled`), any
requirements Open Questions still Open (from Stage R's return; write "none reported" when
Stage R returned none), and an
`AskUserQuestion`: **Approve and build** | **Request changes**.

In the SAME `AskUserQuestion` call, ask a second question — **Build mode.** State the task
count and the tokens spent so far, then offer:

- **Run to completion** — no further pauses. Best when the session is fresh.
- **Checkpoint at each phase (recommended)** — pause before the test gates, before the
  review gates, and before ship. Three decision points, each on a clean committed tree.
- **Pause after every task** — maximum control: one pause per task, on top of the phase
  checkpoints. Use when the session budget is tight or unknown.

Record the answer as `build_mode` in the ledger. It governs Stages 3.9, 4.9 and 5.9 for the
rest of the run, unless the client changes it at a checkpoint.

- **Request changes** → ≤3 tasks affected: `planner` in TARGETED mode with only those
  task paths; re-run only the reviewer whose lens the change touches, on the changed
  files. Broader/scope/ordering/architecture changes: full revision mode.
- Increment `planner_dispatches` on every dispatch including targeted. **At 4, stop** and
  say:

  > We've revised this plan 4 times (~Nk tokens so far). The remaining items look like
  > scope discovery rather than plan defects. Options: (a) approve as-is and handle the
  > rest as follow-ups, (b) keep revising — roughly Mk tokens per round, (c) restart
  > planning from a tightened brief.

- Never start Stage 3 without an approval recorded in the ledger.

## Stage 2.7 — ADR (feature track, only if architecture changes)

New service or module boundary, data-model change, new dependency, or cross-cutting
pattern → dispatch `adr-writer` with `00-overview.md` and the contract path; it records in
`docs/adr/`. Never blocks Stage 3 — dispatch it and move on. Skip otherwise.

## Stage 3 — Execute (superpowers:executing-plans, dedicated branch)

Governed by **superpowers:executing-plans**; per-task dispatch follows
**superpowers:subagent-driven-development**. Do NOT use
**superpowers:using-git-worktrees** — work on a branch in the main checkout.

1. From latest main create `feature/<slug>`. Verify a
   clean test baseline first.
2. Record the base commit.
3. For each task IN ORDER, dispatch a fresh `implementer` with: **the single task file
   path** (`task-NN-<name>.md` — never the plan directory, never `00-overview.md` in
   full), repo root + branch, the Global Constraints block pasted inline (it is small),
   the contract path, and the `TDD` flag.
   - `TDD: on` → superpowers:test-driven-development (RED-GREEN-REFACTOR; code written
     before its test gets deleted).
   - `TDD: off` → code first, but the suite stays green and every acceptance criterion
     gets at least a happy-path test.
   - `DONE` → continue. `NEEDS_CONTEXT` → supply, re-dispatch. `BLOCKED` → more context,
     then a stronger model, then split the task, then escalate. Never silently retry.
   - **Tests: targeted only.** The implementer runs only the tests covering the files   
     this task changes. It must NOT run the whole suite — Stage 4's gate does that once.
   - **Do not re-run a passing test to check for flakiness.** If you suspect a test is  
     flaky, name it in the DONE report and move on.
   - **If `build_mode` is "pause after every task":** after each task's commit, report the
     task number, commit hash and tokens spent on that task, then `AskUserQuestion`:
     **Next task** | **Stop here**. Do not ask in the other two modes.
4. Checkpoint after each batch: update the ledger, surface drift, and — you, the orchestrator
   , not the implementer — run the suite once per batch and record only the summary line.
5. Never parallelise implementers — they share the same working tree. Execution is
   strictly sequential, one task at a time.
6. Ledger: `Task N: complete (commits <base>..<head>)`.

## Stage 3.9 — Build complete checkpoint

All tasks are committed and the tree is clean — the safest stopping point in the run.

`build_mode: run to completion` → continue without asking.

Otherwise report in ONE turn: tasks completed, commit range, suite status, and tokens
spent on the build. Then `AskUserQuestion`:

- **Continue to the test gates** — unit-tester then qa-tester. Quote what the build just
  cost, so the client is deciding against a number rather than a guess.
- **Stop here** — the branch keeps every commit and is resumable. Say plainly what has NOT
  run yet: unit-test gate, QA gate, code review, security review, docs, PR.

Never continue past a **Stop here** in the same session. Resuming means a fresh
`/pipeline-all` session pointed at the existing branch — a paused run still consumes the
session window, so waiting inside it buys nothing.

## Stage 4 — Unit test gate (only if UNIT_TESTS: on)

`UNIT_TESTS: off` → still run the FULL suite yourself and record the summary line; a red
suite blocks Stage 5 regardless.

`UNIT_TESTS: on` → dispatch `unit-tester` (gstack /qa-only) with repo root, branch, base
commit. It runs the full suite, checks coverage on changed lines, and adds missing tests.
Returns PASS or a fix list → fresh `implementer` → re-run. Max 3 loops. Route
fixes with the **task file path and failing test names only**. Suite output over ~500
lines goes to a file; pass the path.


## Stage 4.5 — QA scenario gate (skip if no user-facing surface)

Dispatch `qa-tester` (gstack /qa-only) with repo root, branch, and the **acceptance
criteria extracted from the task files** — a short list, not the plan directory. It walks
them as real user scenarios (happy, error, empty, edge) and reports findings without fixing
anything. Findings → fresh `implementer` → re-run. Max 2 loops.

## Stage 4.9 — Pre-review checkpoint

Both test gates have passed.

`build_mode: run to completion` → continue without asking.

Otherwise report tokens spent on the test gates and `AskUserQuestion`:

- **Continue to code + security review** — two parallel reviewers, plus a fix pass if they
  find anything Critical or Important.
- **Stop here** — tests are green and committed; review, docs and PR remain.

## Stage 5 — Code + Security review (PARALLEL)

Write the review diff to a file, filtering generated content:

```
git diff <base>..HEAD -- . ':!*.lock' ':!package-lock.json' ':!yarn.lock' \
  ':!pnpm-lock.yaml' ':!dist' ':!build' ':!*.min.*' ':!*.map' ':!*.snap' \
  ':!vendor' ':!node_modules'
```

Dispatch **in a single message**:
- `code-reviewer` — spec compliance + quality (superpowers:requesting-code-review rubric + gstack /review)
- `security-reviewer` — OWASP/STRIDE pass (gstack /cso)
Pass the diff FILE PATH and the relevant task FILE PATHS. Never paste contents. Never the
whole plan directory.
Both are read-only. Merge by severity. Critical/Important → fix `implementer`, then
**delta-only re-review**: `git diff <pre-fix>..HEAD` with the same filters, re-run both
reviewers on the fix diff plus the numbered findings it addresses. Minor → fix in the same
pass, no re-review. Max 2 loops, then escalate with your recommendation.

## Stage 5.5 — Performance gate (only if a task is `perf-sensitive: true`)

Dispatch `perf-tester` (gstack /benchmark) to compare main vs branch on the touched
paths. Regressions → fresh `implementer`. Skip entirely otherwise.

## Stage 5.8 — Documentation

Dispatch `doc-writer` (gstack /document-release) with branch name, the diff file path, and
`00-overview.md`. It updates README and docs to match what changed and commits to the
branch.

## Stage 5.9 — Pre-ship checkpoint

Everything is reviewed, documented and committed. Ship is the last dispatch and it is not
small — it syncs main, re-runs the suite, pushes and opens the PR.

`build_mode: run to completion` → continue without asking.

Otherwise report the final ledger and `AskUserQuestion`:

- **Ship it** — dispatch `ship-pr`.
- **Stop here** — the branch is complete and reviewed; only the push and PR remain, and
  those can be done by hand or in a later session.

## Stage 6 — Ship

Dispatch `ship-pr` with repo root + branch, plan file path, review verdicts, test
results, and the TDD/UNIT_TESTS flags for the PR body. It runs gstack /ship ONLY
(no superpowers skills here — /ship already syncs main, re-runs the suite, pushes,
and opens the PR).

Report in <10 lines: what shipped, PR link, test summary, anything deferred, final ledger
line. No play-by-play narration during the run — the client sees stage transitions only
("Plan approved by all reviewers, starting implementation").

## Token ledger

Update after every stage. Keep it in the ledger, not in prose to the client.

```
TOKEN LEDGER
  requirements: <path> (approved, revisions: N) | <path> (existing, unrevised) | none
  contract: distilled | copied | none
  requirements_dispatches: N   requirements_revisions: N / 4
  qa_slot: DONE (<outputs>) | PLACEHOLDER   qa_input_rounds: N / 2
  build_mode: <run to completion | checkpoint | per-task>
  planner_dispatches: N / 4
  reviewer_dispatches: N   implementer_dispatches: N
  agent turns vs target: distiller N/12 · planner N/15 · revision N/10 · reviewers N/4
  plan files I have read myself: N        <- must be 0
  my own turn count: N                   <- target under 12 through Stage 2.5
  documents read by more than one agent: <list>   <- must be empty
  cumulative tokens: ~Nk / 3,000k soft budget
```

- Soft budget per feature plan: **3M tokens**. On crossing it, pause and report before
  dispatching further agents.
- Any agent over its turn target is looping on verification. Note it and tighten its next
  dispatch prompt.

## Hard rules

- Never commit directly to main/master.
- Never start implementation before explicit client approval (Stage 2.5).
- Never skip the Stage R client confirmation when `requirements-writer` returned `DONE`.
- Never start Stage 0.5 before Stage R and Stage Q have finished.
- `/pipeline-all` runs features only. A clear bug request gets the Stage 0 redirect question.
- Never skip a gate because a previous gate passed cleanly.
- The full existing suite must pass before any PR, even with TDD and UNIT_TESTS off.
- Never let an implementer see the whole plan or another task's diff.
- **Never let two agents read the same large document.** Distil once, pass the extract.
- **Never pass a document's contents in a dispatch prompt.** Pass paths. Sole exception:
  the Global Constraints block.
- **You do not read plan files.**
- **Verification costs a turn.** No agent — including you — may shell out to measure or
  inspect a file it just wrote, or `Read` back its own output. Size checks happen once, at
  Stage 2.
- **Never re-read anything already in your context.** Scroll up.
- **One call per unit of work.** One `Write` per file, one `Edit` per finding. A file that
  fits in one call goes in one call.
- **No narration turns.** Prose rides along with a tool call or waits for the gate.
- Never exceed 4 planner dispatches without an explicit client decision.
- A reviewer verdict is required in writing before the next stage starts.
- Every reviewer finding must cite file + line range.
- If context grows large, trust the ledger + git log over memory.
