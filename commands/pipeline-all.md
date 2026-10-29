---
description: Requirements-first feature pipeline. Requirements doc (client approves) → BA requirements analysis → testing prefs → Plan → reviews → CLIENT APPROVES PLAN → Execute (TDD if requested) → Unit test → QA → Code+Security review → Docs → Acceptance gate → Ship PR. Features only — bugs use /pipeline.
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
echo "HOME=$HOME"
B=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
[ -n "$B" ] || { git show-ref --verify -q refs/heads/main 2>/dev/null && B=main || B=master; }
echo "BASE_BRANCH=$B"
```

Record the printed `PLUGIN_ROOT` and `HOME` values as `<PLUGIN_ROOT>` and `<HOME>`, and
`BASE_BRANCH` in the ledger as `<base branch>`; Stage R and Stage 3 use them.

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

1. **Slug and path.** Stale contracts are removed in the same Bash call as each check below
   (Stage 0.8 re-creates them; an old contract would make the context-budget hook redirect
   agents away from the new requirements).
   - **The request is a path to an existing `*.requirements.md`** (for example the next part
     of a split feature): do not dispatch the writer. `<dir>` is the folder containing the
     file; `<stem>` is its file name without `.md`. Set `<slug>` =
     `<feature folder name>-<part file stem without .requirements>`, so the plans dir and
     branch are unique per part (`docs/features/emv-email/02-campaigns.requirements.md` →
     `emv-email-02-campaigns`). A single file directly under `docs/features/`
     (`docs/features/<name>.requirements.md`) is not a part: `<slug>` = `<name>`. One Bash call:
     `ls <path> 2>/dev/null; ls <dir>/[0-9][0-9]-*.requirements.md 2>/dev/null; grep -c '^| Status | Approved |' <path>; rm -f <dir>/<stem>.contract.md`
     — for a part file, add to the same call (`$B` is the base branch the Stage -1 preflight
     recorded; fetch first so a part merged on the remote is seen as merged):
     `B=<base branch>; git fetch -q origin "$B" 2>/dev/null; R=origin/$B; git rev-parse -q --verify "$R" >/dev/null || R=$B; git branch --list 'feature/<feature folder>-[0-9][0-9]-*' --no-merged "$R"`,
     and, in the same call, for each branch it lists:
     `git ls-remote --exit-code --heads origin <branch> >/dev/null 2>&1 || echo "GONE <branch>"`.
     A `GONE` branch no longer exists on the remote: treat it as merged (deleted after merge).
     If `ls <path>` prints nothing, tell the client the file was not found and stop.
     Record `<path>`. `REMAINING_PARTS` and `part K of P` apply only to part files
     (`NN-*.requirements.md` in a feature folder); a top-level
     `docs/features/<name>.requirements.md` gets no part fields. For a part, record
     `REMAINING_PARTS` = the listed parts with a higher NN than this part, and the ledger
     entry as `part K of P` (K = this part's place among the listed parts, P = how many are
     listed). If a branch for a lower-NN part is listed, ask with `AskUserQuestion`:
     **Continue anyway** | **Stop** — "Part NN's branch does not appear merged into
     <base branch> (squash-merged branches show this too); this part may use what it ships."
     (A listed branch that is `GONE` raises no warning.)
     **Stop** ends the run with: "Once part NN is merged and deployed, run
     /sdlc-pipeline:pipeline-all <this path>." When the `grep -c` prints `1`, the file was
     approved earlier: record `REQUIREMENTS: <path> (approved earlier[, part K of P])`, tell the
     client "Part already approved — to change it, edit the file or choose Regenerate.", and skip the step-4
     question. Otherwise go to the step-4 question showing only the path — you do not read
     the file; the summary, counts and Open Questions are not available.
   - **Otherwise** derive `<slug>` from the request (kebab-case, at most 5 words). The
     single-file path is `docs/features/<slug>.requirements.md`; the split folder is
     `docs/features/<slug>/`. One Bash call:
     `ls -d docs/features/<slug>.requirements.md docs/features/<slug>/*.requirements.md 2>/dev/null; rm -f docs/features/<slug>.requirements.contract.md docs/features/<slug>/*.contract.md`.
     If anything exists, ask once: **Use the existing file** (for a split folder, ask which
     part; you do not read the file) — then, for the single file or the chosen part,
     continue exactly as the part-path bullet above with that path as the request: it sets
     `<slug>`, `REMAINING_PARTS` and `part K of P`, and runs the approved-earlier skip and
     the earlier-part check; the summary, counts and Open Questions are not available |
     **Regenerate** — deletes the old requirements and its BA analysis (in one Bash call,
     delete the listed files and the matching Stage Q artifact root —
     `rm -rf docs/features/ba/<slug>/` for the single file, `rm -rf docs/features/<slug>/ba/`
     for a split folder — then dispatch the writer).
2. **Dispatch `requirements-writer`** with:
   - `mode: draft`, `question_round: 0`
   - `request`: the client request, verbatim
   - `input_files`: paths of any files the client referenced, or `none`
   - `template`: `<PLUGIN_ROOT>/templates/requirements-template.md`, using the value Stage -1
     printed. If it printed `unset`, find the template with one Glob for
     `**/templates/requirements-template.md` with its path set to `<HOME>/.claude/plugins`
     (absolute — Glob does not expand `~`); if none, pass
     `template: unavailable (home: <HOME>)`, note it in the ledger, and continue — never HALT
     here.
   - `output`: the single-file path
   - `output_dir`: the split folder
   - `repo_root`

   Increment `requirements_dispatches` on every `requirements-writer` dispatch.
3. **`NEEDS_CONTEXT`** → relay its numbered questions to the client in ONE batched message,
   then re-dispatch in the same mode the agent was dispatched in, with `answers` and
   `question_round` + 1. `answers` are cumulative — every answer given so far in Stage R,
   across rounds — and are passed in both modes. A `NEEDS_CONTEXT` from a `revision` dispatch
   is answered with a `revision` re-dispatch carrying the same `feedback` plus `answers`
   (revision mode must never regenerate the file). At `question_round: 2` the agent must
   write (draft) or apply (revision) without further questions, recording anything still
   unknown as Open Questions and Assumptions.

   **`SPLIT_PROPOSAL`** → the agent judged the feature too big for one run and wrote nothing
   yet. In ONE turn show its `parts` and `order` lines, then ask with
   `AskUserQuestion`: **Approve split** | **Keep as one file** | **Change the split**.
   - **Approve split** → re-dispatch in `draft` mode with `approved_split` = the parts list
     verbatim, `question_round: 2`, plus the same `request`, `input_files`, `template`,
     `output`, `output_dir`, `repo_root` and the cumulative `answers`.
   - **Keep as one file** → re-dispatch the same way with `approved_split: one-file`.
   - **Change the split** → re-dispatch the same way (no `approved_split`) with
     `previous_proposal` = the agent's last `parts` and `order` lines, verbatim, and
     `split_feedback` = the client's words, cumulative across rounds. Count these in
     `split_rounds`; after 2, offer only **Approve split** | **Keep as one file**.

   For **Change the split** and **Request changes** (step 4), take the client's words from
   the free-text answer of the same `AskUserQuestion`, or from one plain follow-up message
   if they gave none.
4. **`DONE` → client confirmation.** In ONE turn show each returned path with its counts
   (BR / VAL / AC / Open Q), the agent's summary and its list of questions still Open. Then
   ask ONE `AskUserQuestion` covering all files: **Approve requirements** | **Request changes**.
   - **Approve requirements** → mark every file approved in one Bash call, without reading
     them: `sed -i 's/^| Status | Draft |/| Status | Approved |/' <path> [<path> …]`.
   - **Request changes** → take the client's feedback verbatim and re-dispatch in
     `revision` mode with `feedback`, `files` (every requirements path in play),
     `question_round: 0`, the cumulative `answers`, plus the same
     `request`, `input_files`, `template`, `output`, `output_dir` and `repo_root` (`output` and
     `output_dir` are `n/a` when the run started from an existing file or part path —
     revision only edits `files`). Return to this step.
   - Count each revision in `requirements_revisions`. **At 4, stop** and say:

     > We've revised the requirements 4 times. Options: (a) approve as-is and keep the
     > remaining points as Open Questions, (b) keep revising, (c) restart from a tightened
     > brief.
5. **`PLACEHOLDER`** → say `Requirements agent not yet implemented — continuing with the raw
   request.` on the same turn as Stage Q, record `REQUIREMENTS: none`, and go
   to Stage Q. No gate. **`BLOCKED`** → the same, but say
   `Requirements agent blocked: <reason> — continuing with the raw request.`
   - **Exception:** if the client chose **Use the existing file**, or the run started from a
     part path, and a later `revision` dispatch returns `PLACEHOLDER` or `BLOCKED`, keep the
     file: record `REQUIREMENTS: <path> (existing, unrevised)`, tell the client in one line
     that their changes could not be applied (for `BLOCKED`, give its `<reason>`; for
     `PLACEHOLDER`, say the requirements agent is not implemented yet), and continue to
     Stage Q.
6. Ledger: `REQUIREMENTS: <path> (approved, revisions: R)`,
   `REQUIREMENTS: <path> (approved earlier[, part K of P])`, `REQUIREMENTS: <path> (existing, unrevised)` or
   `REQUIREMENTS: none`. After a split,
   `<path>` is part 1, `<slug>` becomes part 1's part slug for the rest of the run (plans
   dir, branch), and the entry reads `(approved, part 1 of P, revisions: R)`; also
   record `REMAINING_PARTS: <part 2…P paths>`.
   **One part per run** — the rest of this run builds part 1 only.

You do not read the requirements file. Everything you show the client comes from the agent's
return, and the client opens the file themselves. Never start Stage Q without an approval,
`(existing, unrevised)` or `REQUIREMENTS: none` in the ledger.

## Stage Q — BA requirements analysis

`<artifact root>` = `<directory of the REQUIREMENTS file>/ba/<its stem without .requirements>/`
(e.g. `docs/features/emv/ba/02-campaigns/`).

`<absolute artifact root>` = `<repo root>/<artifact root>`; the skill and the state check
below always get the absolute form.

- `REQUIREMENTS: none` → say `No requirements file — skipping BA analysis.`, record
  `ba: skipped`, continue to Stage 0.5.
- **Already complete?** If `<PLUGIN_ROOT>` (recorded at Stage -1) is not `unset`, run one Bash
  call: `python <PLUGIN_ROOT>/scripts/pipeline-state.py inspect --project-root <absolute artifact root>`.
  If its JSON has `state_status` `COMPLETED` and `artifacts_still_valid` true → say
  `BA analysis already complete — skipping.`, record `ba: <artifact root> (completed)`, run
  the `.gitignore` call from the `COMPLETED` bullet below, and continue to Stage 0.5 without
  its question. Any other result, a failed call, or `unset` → invoke the skill.
- Invoke the skill `sdlc-pipeline:ba-run` with arguments
  `--requirements <REQUIREMENTS path> --artifact-root <absolute artifact root>`. It runs
  atomic requirements, gap analysis, gap triage with the client (one gap at a time; every
  Critical and High gap must be resolved) and development stories appended to the
  requirements file, then returns a last line `BA_STATUS: …`.
- `BA_STATUS: PAUSED` → record `ba: <artifact root> (paused)` and end the run with: "Your
  answers are saved. Run `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` to continue — the
  BA analysis resumes where it stopped."
- `BA_STATUS: BLOCKED`, or no `BA_STATUS` line → record `ba: <artifact root> (blocked)` and
  end the run with: "The BA analysis stopped (reason above). Run
  `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` to continue from where it stopped."
- Stage R and Stage Q stops end with their own line only — never the next-part line.
- `BA_STATUS: COMPLETED` → record `ba: <artifact root> (completed)`, then keep machine-specific
  files out of git with one Bash call:
  `[ -f <artifact root>/.gitignore ] || printf '.ba-requirements/\nstories/backups/\nacceptance/verdicts.json\n' > <artifact root>/.gitignore`.
  If `ba-run` reported that the BA analysis was already complete (a resumed run), do not
  ask — continue to Stage 0.5. Otherwise ask with `AskUserQuestion`: **Stop and resume in a
  fresh session (Recommended — lower cost)** | **Continue now**. The BA instructions stay in
  this session's context for every later turn. **Stop** ends the run with: "Run
  `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` in a new session — requirements and BA
  analysis are kept and skipped."

### Story export (used by Stage 1 and Stage 5.85)

Run it once Stage Q ends with `ba: <artifact root> (completed)` (a resumed or already-complete
run included). If `<PLUGIN_ROOT>` is `unset`, resolve it first: one Glob for
`**/scripts/acceptance-checklist.py` with its path set to `<HOME>/.claude/plugins` (absolute),
and take the plugin root above `scripts/`. None found → record `acceptance: blocked (plugin
root not found)` and end the run now, before Stage 0.5: "Plugin root not found, so the
acceptance check cannot run — no build started. Re-run from the installed plugin."
`<absolute REQUIREMENTS path>` =
`<repo root>/<REQUIREMENTS path>` (unchanged when already absolute). One Bash call writes the
stories as JSON; the command's stdout (the whole draft) goes to a file that is shown only on
failure:
`mkdir -p <absolute artifact root>/.ba-requirements && { python <PLUGIN_ROOT>/scripts/sync-development-stories.py export --project-root <absolute artifact root> --target <absolute REQUIREMENTS path> --draft-out <absolute artifact root>/.ba-requirements/stories-export.json > <absolute artifact root>/.ba-requirements/export-output.json || { cat <absolute artifact root>/.ba-requirements/export-output.json; exit 1; }; }`.
Record `STORIES: <absolute artifact root>/.ba-requirements/stories-export.json`; otherwise
record `STORIES: none`. A non-zero exit → show the output and end the run with the caller's
line:
- Stage Q: "The BA analysis stopped (reason above). Run
  `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` to continue from where it stopped."
- Stage 1: "Story export failed (reason above) — fix the stories
  (/sdlc-pipeline:ba-sync-stories) and re-run `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>`."
- Stage 5.85: "Story export failed — branch kept, no PR; fix the stories
  (/sdlc-pipeline:ba-sync-stories) and re-run."

Agents read the stories from this JSON only, never from `detailed_stories.md`.

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

`<source>` is the requirements file recorded in the ledger (`docs/features/<slug>.requirements.md`,
or the current part's file after a split) when the ledger says `REQUIREMENTS: <path> (approved…)`
or `(existing, unrevised)` — treat both the same. If the ledger says
`REQUIREMENTS: none`, `<source>` is any spec the client referenced instead; if there is none,
record `CONTRACT: none` in the ledger and skip to Stage 1. `<contract dir>` is the directory of
`<source>` for a requirements file, otherwise `docs/features`.

The ledger value `CONTRACT: distilled | copied | none` records which case applies.

1. One Bash call measures the source and, when it is small, copies it to the contract path.
   Estimate tokens as `chars / 3` (12,000 chars ≈ 4,000 tokens):

   ```bash
   wc -c -l <source>
   if [ "$(wc -c < <source>)" -lt 12000 ]; then
     mkdir -p <contract dir> && cp <source> <contract dir>/<source stem>.contract.md && echo "CONTRACT: copied"
   fi
   ```

2. Under 4,000 tokens → that call made the copy. Record `CONTRACT: copied`; `<contract>` =
   `<contract dir>/<source stem>.contract.md`. Skip to Stage 1. Wherever a stage passes the
   contract path, pass the copy, not `<source>`: reviewers may read only slices and
   `*.contract.md` files.
3. Otherwise dispatch **one** `distiller` with `<source>` and the output path
   `<contract>` = `<contract dir>/<source stem>.contract.md`, and record `CONTRACT: distilled`.
   For a single requirements file that is `docs/features/<slug>.requirements.contract.md`; for
   a part it sits beside the part. The name must be `<source stem>.contract.md` (copied or
   distilled), because the context-budget hook links an original to its contract by filename
   stem. When `<source>` is
   a requirements file, add this to the dispatch:

   > Requirements mode. In addition to the standard sections, keep, one line each and with no
   > row cap: every `BR-xxx` (id · rule · priority), every `VAL-xxx` (id · field · rule), every
   > `AC-xxx` (id · one-line Then · Covers), the In Scope and Out of Scope bullets, every Error
   > Scenario and Edge Case, and the Non-functional rows. Put them under `## Scope`,
   > `## Business rules`, `## Validation rules`, `## Acceptance criteria`,
   > `## Error & edge scenarios`, `## Non-functional`. For a requirements source these
   > sections override the "What stays out" list.
   > Also keep every development story from the `# Development Stories` section, one line
   > each: `US-xxx` · summary · the story's one acceptance statement, under
   > `## Development stories`. (The detailed criteria are in the stories export, not the
   > requirements file.)

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

- Dispatch the planner in **Approved-requirements mode**: the client already approved the
  requirements, so it skips gstack /office-hours and superpowers:brainstorming.
- When `CONTRACT: distilled`, also pass `<source>`, the approved requirements file,
  labelled explicitly as the original the planner may read. When
  `CONTRACT: copied`, the contract already holds the same text — pass it alone. State that
  the approved requirements are the source of truth. The planner gets no raw client files.
- Add to the dispatch: "Keep the overview's `FR-NN` traceability rows, but each FR row cites
  the `BR-xxx` / `AC-xxx` IDs it covers and the `US-xxx` stories it implements, every Must
  Have `BR-xxx` appears in at least one FR row, and every `US-xxx` story appears in at least
  one FR row."
- When the ledger says `STORIES: <path>`, first run the story export again (fresh — see
  "Story export" in Stage Q), then pass its path to the planner as "the development stories
  (JSON, read it)" and add to the dispatch: "Each task file's `## Acceptance criteria` lists
  the detailed criteria the task implements as `US-003.2 — <criterion text>` (story ID, then
  the criterion's number in that story's `detailed.acceptance_criteria` list). Every detailed
  criterion of every story appears in at least one task."

Otherwise (`REQUIREMENTS: none`) the planner works through
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
The contract cap applies only to a standard distilled contract. A copied contract and a
requirements-mode contract are exempt — never cut the client-approved text or the
requirements-mode rows.

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
requirements Open Questions still Open (from Stage R's return; write "not available
(existing file)" only for an existing file or part path, "n/a" when the ledger says
`REQUIREMENTS: none`, and "none reported" when the agent returned an empty list), and an
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

1. Run `git fetch -q origin <base branch>` and create `feature/<slug>` from `origin/<base branch>`
   (from the local `<base branch>` when there is no remote), so a later part includes earlier
   parts already merged. Verify a
   clean test baseline first. On every `/pipeline-all` run with a requirements file
   (written, approved, or approved earlier), commit them as the branch's first commit: `git add` the current requirements
   file, for a part its sibling `<dir>/[0-9][0-9]-*.requirements.md` files, and the Stage Q
   `<artifact root>` when it exists, with its `.gitignore` but without its checkpoint and
   story backups (the checkpoint stores absolute local paths and the backups duplicate the
   requirements file):
   `if [ -d <artifact root> ]; then git add <artifact root> ':!<artifact root>/.ba-requirements' ':!<artifact root>/stories/backups' ':!<artifact root>/acceptance'; fi`.
   Commit only if something is staged
   (`git diff --cached --quiet || git commit -m "docs: requirements for <slug>"`).
   After a split this includes all parts, so later parts reach the base branch with this PR.
2. Record the base commit (HEAD after the requirements commit).
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

Dispatch `perf-tester` (gstack /benchmark) to compare the base branch vs branch on the touched
paths. Regressions → fresh `implementer`. Skip entirely otherwise.

## Stage 5.8 — Documentation

Dispatch `doc-writer` (gstack /document-release) with branch name, the diff file path, and
`00-overview.md`. It updates README and docs to match what changed and commits to the
branch.

## Stage 5.85 — Acceptance gate

Every acceptance criterion must be proven met, or accepted by the client as a follow-up,
before Stage 6. "End the run" below means: branch kept, no PR; if `REMAINING_PARTS` is not
empty, end with the "Finish this part first …" line from the Hard rules.

`<PLUGIN_ROOT>` is still `unset` (backstop — Stage Q resolves it when BA ran) → record
`acceptance: blocked (plugin root not found)` and end the run with: "Plugin root not found, so the acceptance check cannot run — branch kept, no PR.
Re-run from the installed plugin."

`<acceptance dir>` = `<absolute artifact root>/acceptance` when the ledger says
`ba: … (completed)`; otherwise (no BA folder) `<repo root>/docs/plans/<slug>/acceptance`. It
holds `checklist.json`, `verdicts.json`, `acceptance-report.md` and `acceptance-report.json`.

1. **Checklist.**
   - `ba: … (completed)` → run the story export again (fresh — see "Story export" in Stage Q),
     then one Bash call:
     `python <PLUGIN_ROOT>/scripts/acceptance-checklist.py build --export <absolute artifact root>/.ba-requirements/stories-export.json --requirements <absolute REQUIREMENTS path> --out <acceptance dir>/checklist.json`.
   - `ba: skipped` (this includes `REQUIREMENTS: none`) → one Bash call:
     `python <PLUGIN_ROOT>/scripts/acceptance-checklist.py build --tasks <repo root>/docs/plans/<slug> --out <acceptance dir>/checklist.json`.
   - Exit 2 with `No acceptance criteria found` → say `No acceptance criteria — skipping the
     acceptance gate.`, record `acceptance: skipped (no criteria)`, continue to Stage 5.9. Any
     other non-zero exit → show the output and end the run.
2. **Verify.** Dispatch `acceptance-verifier` with: checklist path
   `<acceptance dir>/checklist.json`, verdicts output path `<acceptance dir>/verdicts.json`,
   repo root, branch, base branch, plan directory `<repo root>/docs/plans/<slug>`, the Stage 4 suite
   summary line, and the Stage 4.5 QA findings (or "not run"). `BLOCKED` → show its reason and
   end the run; never guess verdicts. `DONE` → one Bash call:
   `python <PLUGIN_ROOT>/scripts/acceptance-checklist.py render --checklist <acceptance dir>/checklist.json --verdicts <acceptance dir>/verdicts.json --out-dir <acceptance dir>`.
   It prints `total`, counts per status, `open`, `report_md` and `report_json`. Exit 0 →
   step 5. Exit 1 → step 3 when any item is `not_met`, else step 4. Exit 2 → show the output
   and end the run.
3. **Fix loop.** Fix IDs = the `not_met` IDs (from step 2), or the IDs the client chose
   **Fix more** for (from step 4, `not_met` or `cannot_verify`). Each round, one Bash call
   prints each fix item (ID, criterion text, `fix_hint` or `note`) from `report_json` and the
   task file that covers it: `T<NN>.<n>` → `docs/plans/<slug>/task-<NN>-*.md`; any other ID →
   `grep -HowF -e <ID> … docs/plans/<slug>/task-*.md`. On entering step 3, that call also
   prints `git rev-parse HEAD`; record it as `<pre-fix sha>`. Then dispatch a fresh
   `implementer` per affected task — **sequential**, one at a time (they share the working
   tree) — with the task file path and its fix IDs, criterion text and fix hints, plus: "Stage
only the files you changed — never `git add -A`; leave `<acceptance dir>` untouched." IDs no task
   file cites → one more implementer with those IDs, texts and hints only. Re-check: dispatch
   `acceptance-verifier` with the step 2 inputs plus the re-check IDs (this round's fix IDs)
   → `render`. A re-check `BLOCKED` or `render` exit 2 is handled as in step 2. From step 2:
   max 2 rounds, the second round's fix IDs are the ones still `not_met`, and the loop stops
   early when there are none. From step 4: exactly one round per **Fix more**. If any fix commit was made, write
   `git diff <pre-fix sha>..HEAD` (the Stage 5 filters) to a file and dispatch
   `code-reviewer` on the fix commit range only: that diff file path and the fixed IDs. Its
   findings are handled as in Stage 5, `code-reviewer` only; if they lead to further implementer
commits, re-check the fixed IDs once more (verifier with those IDs → `render`), handled as in
step 2.
4. **Client decision.** Still `not_met` or `cannot_verify` → ask ONE batched question listing
   them (ID · status · criterion · fix hint or reason) — `AskUserQuestion` with one question
   per item when there are at most 4, otherwise one message the client answers per ID. Per
   item: **Fix more** (one more step 3 round for it) | **Accept as follow-up** | **Stop**. Ask
   even when `build_mode: run to completion` — the PR never ships with an open criterion.
   - **Accept as follow-up** → edit that verdict in `<acceptance dir>/verdicts.json`:
     `status` `accepted_followup`, `note` = the client's words. Then re-run `render` (exit 2
     is handled as in step 2).
   - **Fix more** → one step 3 round for those IDs, whatever their status, then back to this
     step for anything still open.
   - **Stop** on any item → step 5 and 6, then end the run.
5. **Commit** the report to the branch in one Bash call:
   `git add <acceptance dir>/checklist.json <acceptance dir>/acceptance-report.md <acceptance dir>/acceptance-report.json && (git diff --cached --quiet || git commit -m "docs: acceptance report for <slug>") && rm -f <acceptance dir>/verdicts.json`.
   (`acceptance-report.json` already holds every verdict.) A non-zero exit → show the output
   and end the run.
6. **Ledger:** `acceptance: <met>/<total> met, <n> follow-ups, report <report_md>`.

## Stage 5.9 — Pre-ship checkpoint

Everything is reviewed, documented and committed. Ship is the last dispatch and it is not
small — it syncs the base branch, re-runs the suite, pushes and opens the PR.

`build_mode: run to completion` → continue without asking.

Otherwise report the final ledger, the acceptance summary line from Stage 5.85
(`X/Y met · N follow-ups`, or why it was skipped), and `AskUserQuestion`:

- **Ship it** — dispatch `ship-pr`.
- **Stop here** — the branch is complete and reviewed; only the push and PR remain, and
  those can be done by hand or in a later session.

## Stage 6 — Ship

Dispatch `ship-pr` with repo root + branch, plan file path, review verdicts, test
results, the TDD/UNIT_TESTS flags, and — unless `acceptance: skipped …` — the acceptance
report path (`report_md`) and summary line, for the PR body. It runs gstack /ship ONLY
(no superpowers skills here — /ship already syncs the base branch, re-runs the suite, pushes,
and opens the PR).

Report in <10 lines: what shipped, PR link, test summary, anything deferred, final ledger
line. If `REMAINING_PARTS` is not empty, end with:
`Once this PR is merged and deployed, run /sdlc-pipeline:pipeline-all <next part path>.`
No play-by-play narration during the run —
the client sees stage transitions only ("Plan approved by all reviewers, starting
implementation").

## Token ledger

Update after every stage. Keep it in the ledger, not in prose to the client.

```
TOKEN LEDGER
  requirements: <path> (approved[, part K of P], revisions: R) | <path> (approved earlier[, part K of P]) | <path> (existing, unrevised) | none
  base_branch: <main | master>
  remaining_parts: <paths> | none   split_rounds: N / 2
  contract: distilled | copied | none
  requirements_dispatches: N   requirements_revisions: N / 4
  ba: <artifact root> (completed | paused | blocked | skipped)
  STORIES: <path> | none
  acceptance: <met>/<total> met, <n> follow-ups, report <path> | skipped (no criteria) | blocked (plugin root not found)
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
- One requirements part per run. Whenever a run ends at Stage 6 or any **Stop here** checkpoint — not at a Stage R or Stage Q stop — and
  `REMAINING_PARTS` is not empty, end with the next-part line from Stage 6. At Stages 3.9, 4.9
  and 5.9 (any **Stop here** before Stage 6 opens a PR) the line is instead:
  "Finish this part first (resume this branch), merge and deploy its PR, then run
  /sdlc-pipeline:pipeline-all <next part path>."
- Never start Stage 0.5 before Stage R and Stage Q have finished.
- Never start Stage 0.5 while `ba` is `paused` or `blocked`.
- `/pipeline-all` runs features only. A clear bug request gets the Stage 0 redirect question.
- Never skip a gate because a previous gate passed cleanly.
- The full existing suite must pass before any PR, even with TDD and UNIT_TESTS off.
- Never start Stage 6 while any acceptance criterion is `not_met` or `cannot_verify`.
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
