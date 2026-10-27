# `/pipeline-all` — Requirements-first feature pipeline — Design

- **Date:** 2026-10-26
- **Status:** Draft — awaiting review
- **Target version:** sdlc-pipeline 3.2.0
- **Author:** Muhassin (with Claude)

## 1. Goal

Add a new orchestrator command, `/sdlc-pipeline:pipeline-all`, that starts a feature from a
raw idea (text or a file) and turns it into a proper, user-approved requirements document
**before** the existing plan → build → test → review → ship flow runs.

Two new agents are introduced, both as **placeholders** in this release:

1. `requirements-writer` — produces `docs/features/<slug>.requirements.md` from a template,
   asks the user only for major gaps, then asks for confirmation (approve / request changes).
2. `qa-placeholder` — a reserved slot for the QA team's agent, run right after requirements
   are approved. It may ask the user for input. Its real behaviour will be added later.

The full agent instructions are out of scope here: the user will supply them. This release
delivers the orchestration, the agent contracts, the placeholders and the template.

## 2. Decisions taken during brainstorming

| # | Decision |
|---|---|
| D1 | New command `commands/pipeline-all.md`. `pipeline.md` and `pipeline-parallel.md` are **not** changed. |
| D2 | `pipeline-all.md` is a copy of the **sequential** `pipeline.md`, trimmed and extended (Approach A). Not a wrapper that calls `/pipeline` (Approach B rejected: needs `pipeline.md` changes, runs preflight twice, keeps two ~25 KB orchestrator scripts in context). |
| D3 | Order: Preflight → Requirements → QA slot → the rest of the feature track. |
| D4 | Feature-only. Bug and nano tiers are removed; bugs keep using `/sdlc-pipeline:pipeline`. |
| D5 | Requirements: the agent asks only **major** questions; otherwise it writes the file and asks for confirmation. The user approves or requests changes, repeating until approved. |
| D6 | The QA slot is the QA team's agent; it may ask the user for input when needed. |
| D7 | Stage 0.5 (TDD / unit-test round) questions stay where they are, **after** requirements approval. |
| D8 | Template at `templates/requirements-template.md` (plugin). Output at `docs/features/<slug>.requirements.md` (target repo). Agent names `requirements-writer` and `qa-placeholder`. |
| D9 | The template allows technical detail **only** inside clearly marked optional `### Technical notes` subsections. |
| D10 | No `commands/agent-*.md` wrappers for the new agents (consistent with `distiller` and `implementer`, which have none). |

## 3. Stage flow

```
/sdlc-pipeline:pipeline-all <idea text and/or file path(s)>

Stage -1   Preflight                       unchanged from pipeline.md
Stage R    Requirements                    requirements-writer  ⇄ user (questions, then approve / request changes)
Stage Q    QA slot                         qa-placeholder       ⇄ user (input when needed)
Stage 0.5  TDD + unit-test questions       TYPE fixed to feature — bug/feature question removed
Stage 0.8  Requirements → contract         source = approved requirements file; distil if large, else copy (§6)
Stage 1    Plan                            unchanged (feature track)
Stage 2    Plan review gauntlet            unchanged
Stage 2.5  Client plan approval            unchanged
Stage 2.7  ADR                             unchanged
Stage 3    Execute                         unchanged
Stage 3.9 … Stage 6                        unchanged (unit test, QA scenario, code+security review, perf, docs, ship)
```

**Removed from the copy:** Stage 0 (classify / nano fast-path), Stage 1-B (investigate, bug
track), the bug/feature question in Stage 0.5, and every bug-track or nano branch elsewhere in
the script (e.g. "bug track skips the gauntlet", mini-plan references in Stage 2.5/4.5).

**Bug guard (replaces Stage 0):** if the request clearly describes something broken, the
orchestrator asks once: *"This looks like a bug. `/pipeline-all` is for features — use
`/sdlc-pipeline:pipeline` instead, or continue as a feature?"* It is asked once, after
preflight and before Stage R, with one `AskUserQuestion`. If the user stops, the run ends; if
the user continues, the run proceeds as a feature. Requests that are not clearly bugs get no
question.

## 4. Stage R — Requirements

### 4.1 Orchestrator steps

1. **Slug and output path.** Derive `<slug>` (kebab-case, ≤5 words) from the request. Output
   path `docs/features/<slug>.requirements.md`. The existence check is one Bash call that also
   runs `rm -f docs/features/<slug>.requirements.contract.md` (see §8).
   - If that file already exists, ask once: **Use existing file as-is** (show only its path,
     since the orchestrator does not read the file, and ask the step-4 question; the summary,
     counts and Open Questions are not available) | **Regenerate** (overwrite).
2. **Dispatch `requirements-writer`** in `draft` mode (inputs in 4.2).
3. **`NEEDS_CONTEXT`** → relay the numbered questions to the user in ONE batched message,
   then re-dispatch in the same mode the agent was dispatched in, with the answers and
   `question_round` + 1. Answers are cumulative across rounds and are passed in both modes. A
   `NEEDS_CONTEXT` from a `revision` dispatch is answered with a `revision` re-dispatch
   carrying the same `feedback` plus the answers (revision mode never regenerates the file).
   At most **2** question rounds; at `question_round: 2` the agent must write (draft) or
   apply (revision) without further questions, recording anything still unknown as Open
   Questions and Assumptions.
4. **`DONE` → confirmation gate (HARD GATE).** In one turn, show: the file path, the agent's
   summary (≤5 lines), the counts (BR / AC / open questions), and the list of questions still
   **Open**. Ask with `AskUserQuestion`: **Approve requirements** | **Request changes**.
   - **Approve requirements** → one Bash call, no read, sets the file's header row to
     `| Status | Approved |` (`sed -i` on `| Status | Draft |`).
   - **Request changes** → collect the user's feedback verbatim and re-dispatch in
     `revision` mode with `question_round: 0`, the cumulative answers and `input_files`.
     Loop back to this gate.
   - Count revisions. **At 4**, stop and offer: (a) approve as-is and treat the rest as Open
     Questions, (b) keep revising, (c) restart from a tightened brief — mirroring the
     Stage 2.5 planner cap.
5. **`PLACEHOLDER`** → print one line (`Requirements agent not yet implemented — continuing
   with the raw request.`), record `REQUIREMENTS: none`, and continue to Stage Q. No gate.
   Exception: if the user chose **Use existing file** and a later `revision` dispatch returns
   `PLACEHOLDER`, keep the file, record `REQUIREMENTS: <path> (existing, unrevised)`, tell the
   user in one line that the changes could not be applied because the agent is not
   implemented yet, and continue. Stage 0.8 treats `(existing, unrevised)` like approved.
6. Record in the ledger: `REQUIREMENTS: <path> (approved, revisions: N)`,
   `REQUIREMENTS: <path> (existing, unrevised)` or `REQUIREMENTS: none`.

The orchestrator **never reads the requirements file** (context discipline rule 2). Everything
it shows at the gate comes from the agent's return. The user opens the file themselves.

Never start Stage Q without either an approval or `REQUIREMENTS: none` recorded.

### 4.2 Agent contract — `requirements-writer`

**Frontmatter**

```yaml
name: requirements-writer
description: Turns a feature idea (text and/or files) into a requirements document that follows the plugin's requirements template. Asks the client only for major gaps; otherwise writes the file for confirmation. Invoked by /pipeline-all at Stage R, never directly by the client.
tools: Read, Grep, Glob, Write, Edit
model: sonnet
```

**Inputs (dispatch prompt)**

| Field | Meaning |
|---|---|
| `mode` | `draft` or `revision` |
| `request` | the client's request, verbatim |
| `input_files` | paths of any files the client referenced (may be empty); passed in revision mode too |
| `template` | `<PLUGIN_ROOT>/templates/requirements-template.md`, resolved at Stage -1 (see §6) |
| `output` | `docs/features/<slug>.requirements.md` |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_CONTEXT` questions, cumulative (both modes) |
| `feedback` | the client's change requests, verbatim (revision mode only) |
| `question_round` | 0, 1 or 2 — starts at 0 for each draft and for each revision round; at 2 the agent must not return `NEEDS_CONTEXT` |

**What counts as a major question** (return `NEEDS_CONTEXT`): the answer would change what the
feature *is* — its purpose, who uses it, what is in or out of scope, or a core user journey —
and cannot be found in the input or the codebase. Everything else is drafted and recorded as an
Open Question (status `Open`) or an Assumption. At most 7 questions per round, plain language,
answerable by a non-technical client.

**Return format**

```
status: DONE | NEEDS_CONTEXT | PLACEHOLDER
path: <output path>                     (DONE only)
counts: BR n · VAL n · AC n · Open Q n  (DONE only)
summary: ≤5 lines                       (DONE only)
open_questions: numbered, one line each (DONE only; status Open items)
questions: numbered list                (NEEDS_CONTEXT only)
turns: <n>
```

**Constraints to put in the agent file** (so the real implementation inherits them):

- Read large inputs in chunks with `offset`/`limit` — the context-budget hook blocks full
  reads over 250 lines / 20,000 bytes.
- Write forward; never re-read or measure the output file (same discipline as `distiller`).
- Revision mode: `Edit` only the sections the feedback touches; do not regenerate the file.
- Read the codebase only with targeted `Grep` → `Read` around the hit, and only to ground
  scope and existing behaviour.
- Never write production code, plans or tests.

### 4.3 Placeholder body (this release)

The agent file contains the frontmatter, the full contract above, and this body:

> **PLACEHOLDER — instructions to be added.** Do not read any file. Return exactly:
> `status: PLACEHOLDER` and `turns: 1`.

When the real instructions are added, only the body changes; the orchestrator needs no edit.

## 5. Stage Q — QA slot

### 5.1 Orchestrator steps

1. Dispatch `qa-placeholder` with: `requirements` (the approved path, or `none`), `request`
   verbatim, `repo_root`, and `answers` (on re-dispatch).
2. **`NEEDS_INPUT`** → relay the numbered questions to the user in ONE batched message,
   re-dispatch with the answers. Same 2-round limit as Stage R. If the agent returns
   `NEEDS_INPUT` a third time, do not relay it: record its questions in the ledger as
   `QA_OPEN:` and continue to Stage 0.5.
3. **`DONE`** → record each returned output path in the ledger under `QA_ARTIFACTS:`. No gate
   in this release; a gate can be added when the real agent defines what it produces.
4. **`PLACEHOLDER`** → print one line (`QA agent not yet implemented — skipping.`), continue.

### 5.2 Agent contract — `qa-placeholder`

```yaml
name: qa-placeholder
description: Reserved slot for the QA team's requirements-stage agent. Runs right after requirements are approved and may ask the client for input. Invoked by /pipeline-all at Stage Q, never directly by the client.
tools: Read, Grep, Glob, Write, Edit
model: sonnet
```

Return format:

```
status: DONE | NEEDS_INPUT | PLACEHOLDER
outputs: <path list>        (DONE only)
summary: ≤5 lines           (DONE only)
questions: numbered list    (NEEDS_INPUT only)
turns: <n>
```

Placeholder body: same as 4.3. The name `qa-placeholder` is temporary; renaming it later means
updating the agent file name, its `name:` field, and the Stage Q dispatch line in
`pipeline-all.md`.

## 6. Changes to the stages copied from `pipeline.md`

| Stage | Change in `pipeline-all.md` |
|---|---|
| Header / description | New description: requirements-first feature pipeline. `argument-hint: <feature idea text and/or file path(s)>`. |
| Stage -1 | The preflight Bash block also prints `PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-unset}}`; the value is recorded and Stage R passes `<PLUGIN_ROOT>/templates/requirements-template.md`. If it printed `unset`, one Glob for `**/templates/requirements-template.md` under `~/.claude/plugins`; if none, pass `template: unavailable`, note it in the ledger and continue (never HALT — the placeholder path must keep working). |
| Stage 0.5 | Only two questions (TDD, unit-test round), one batched `AskUserQuestion`. `TYPE: feature` is set without asking. |
| Stage 0.8 | Source = the approved (or `existing, unrevised`) requirements file. If `REQUIREMENTS: none`, behave exactly as `pipeline.md` (use any spec the client referenced). One ledger value, `CONTRACT: distilled \| copied \| none`: over the 4,000-token threshold the distiller writes the contract (`distilled`); under it, the same Bash call as the `wc` copies the source to `docs/features/<source stem>.contract.md` (`copied`), so reviewers can read it; no source → `none`, skip to Stage 1. Contract output path for the requirements file: **`docs/features/<slug>.requirements.contract.md`** (see §8). Global Constraints say "distilled from" or "copied from" the source; none when `CONTRACT: none`. One guard rule: a later stage omits the contract path when `CONTRACT: none`; `UNCONFIRMED` items and distiller top-up apply only when `distilled`. **Requirements mode:** when the requirements file is distilled, the dispatch tells the distiller to keep every `BR-`, `VAL-` and `AC-` item, scope bullets, error/edge scenarios and non-functional rows, overriding its "What stays out" list. |
| Stage 1 | The planner receives the contract path only when one exists, i.e. not `CONTRACT: none`. When requirements exist and `CONTRACT: distilled`, it also receives the approved requirements file, labelled as the original it may read (Feature mode), as the source of truth (with `CONTRACT: copied` the contract is the same text, so it is passed alone); its overview's `FR-NN` rows each cite the `BR-xxx` / `AC-xxx` IDs they cover, and every Must Have `BR-xxx` appears in at least one FR row. Paths to files the client referenced are passed only when the ledger says `REQUIREMENTS: none`; once requirements are approved the planner does not get the raw client files. |
| Stage 2 | When the ledger says `CONTRACT: none`: leave `<contract>` out of the `wc -c` line, do not run the plan lint, record `LINT_SKIPPED: no source document`, and pass reviewers only the slice path. The completeness check still runs. The contract > 9,000 size cap applies only to a standard distilled contract; a copied contract (the client-approved text) and a requirements-mode contract (its rows are never cut) are exempt. |
| Stage 2.5 | Also surface any requirements Open Questions still `Open` alongside the contract's `UNCONFIRMED` items; write "none reported" when Stage R returned none. |
| Token ledger | Add rows for `requirements-writer` and `qa-placeholder` dispatches and the requirements revision count (`requirements: <path> (approved, revisions: N)`), plus `contract: distilled \| copied \| none`. |
| Hard rules | Add: never skip the Stage R gate when the agent returned `DONE`; never start Stage 0.5 before Stage R and Stage Q have completed; bug requests are redirected per §3. |
| Everything else | Byte-for-byte the same as `pipeline.md`, minus bug/nano branches. |

## 7. Requirements template

File: `templates/requirements-template.md`. Built from the supplied EMV sample, with all
sample content replaced by one-line guidance comments (`<!-- … -->`) so the agent never copies
project-specific text. Every section carries a `Required` or `Optional` marker. Sections are
never deleted or renumbered: an Optional section that does not apply keeps its heading and
says "Not applicable." (other agents cite sections by number).

| § | Section | Req/Opt | Notes |
|---|---|---|---|
| 1 | Purpose | Required | |
| 2 | Business Objective | Required | Primary objective, outcome, success measure, target users, business owner |
| 3 | Background | Optional | |
| 4 | Scope (In / Out) | Required | Out of Scope must have at least one entry |
| 5 | Users and Roles | Required | Table: Role / Description / Main Actions |
| 6 | Business Process (Current / Proposed) | Optional | |
| 7 | User Journeys | Required | Actor / Trigger / Preconditions / Flow / Expected Result |
| 8 | Business Rules | Required | `BR-xxx`, Priority (MoSCoW) |
| 9 | Validation Rules | Optional | `VAL-xxx`; required when the feature has user input |
| 10 | Data Requirements | Optional | `### Technical notes` allowed |
| 11 | Statuses and State Changes | Optional | `### Technical notes` allowed |
| 12 | Notifications and Messages | Optional | |
| 13 | Error Scenarios | Required | |
| 14 | Positive Scenarios | Optional | |
| 15 | Edge Cases | Required | |
| 16 | Reporting and Audit Requirements | Optional | |
| 17 | **Non-functional Requirements** (new) | Required | Performance, availability, scalability, accessibility, browser/device support — "None beyond platform defaults" is a valid entry |
| 18 | Security and Compliance Requirements | **Required (mandatory)** | Never omitted; "No new security surface" must be stated explicitly if true. `### Technical notes` allowed |
| 19 | Business Acceptance Criteria | Required | `AC-xxx`, Given / When / Then, plus a `Covers: BR-xxx` line |
| 20 | Assumptions | Required | May be "None" |
| 21 | Dependencies | Optional | `### Technical notes` allowed |
| 22 | Open Questions | Required | `Q-xxx`, Owner, Status `Open`/`Resolved`, Decision. May be empty table |
| 23 | Business Definition of Done | Required | Generic checklist (below) |

Inserting §17 shifts the sample's §17–§22 down by one; the template's numbering is the
authoritative one.

**Template header block**: title `# <Feature name> — Business Requirements`, then
`Version`, `Date`, `Status: Draft | Approved`, `Source: <request / input files>`.

**§23 default checklist**:
- Every Required section is filled (or explicitly "None").
- Every In-Scope item is covered by at least one `AC-xxx`.
- Every `BR-xxx` marked Must Have is referenced by at least one `AC-xxx`.
- Security (§18) is filled.
- No Open Question that changes scope remains `Open`.

**Technical notes rule**: technical detail (table names, endpoints, regexes, services) may
appear **only** under a `### Technical notes` heading in §10, §11, §18 and §21. Everywhere else
stays business-level.

## 8. Context-budget hook fit

No changes to `hooks/guard_context_budget.py` in this release. Implications the design
accounts for:

- **Full-read limit** (250 lines / 20,000 bytes): both agent contracts require chunked reads.
- **"Only distiller/planner may read the original once a contract exists"**: Stage R and
  Stage Q run *before* Stage 0.8, so they are unaffected — provided no contract from an
  earlier run is left beside the requirements file. Stage R therefore runs
  `rm -f docs/features/<slug>.requirements.contract.md` in its existence-check Bash call; a
  stale contract would make the hook redirect agents away from the new requirements. Stage 0.8
  re-creates it.
- **Reviewer allowlist:** `ceo-reviewer`, `eng-reviewer` and `design-reviewer` may read only
  slices and `*.contract.md`. A source under the threshold is therefore copied to
  `docs/features/<source stem>.contract.md` rather than passed directly.
- **Contract naming.** The hook links an original to its contract by exact filename stem
  (`<stem>.contract.md`), with a fallback overlap match that needs ≥12 normalised characters.
  A contract named `<slug>.contract.md` would fail to match `<slug>.requirements.md` for short
  slugs, leaving the original unprotected. Therefore, whether Stage 0.8 distils (file over the
  4,000-token threshold) or copies (under it), `pipeline-all.md` writes
  **`docs/features/<slug>.requirements.contract.md`**.
- **Known limitation:** if a client passes as *input* a `.md` file that already has a contract
  beside it (from an earlier run), the hook will block `requirements-writer` from reading it.
  Fix when it matters: add `requirements-writer` to `DISTILLER_AGENTS` in the hook.

## 9. Files

| File | Action |
|---|---|
| `commands/pipeline-all.md` | **New** — copy of `pipeline.md` with §3 and §6 changes |
| `agents/requirements-writer.md` | **New** — placeholder per §4.2–4.3 |
| `agents/qa-placeholder.md` | **New** — placeholder per §5.2 |
| `templates/requirements-template.md` | **New** — per §7 |
| `README.md` | Update — "What's inside" counts (commands, agents), a `/pipeline-all` usage example, and the workflow diagram for it |
| `.claude-plugin/plugin.json` | Version 3.1.0 → 3.2.0 |
| `.claude-plugin/marketplace.json` | Version 3.1.0 → 3.2.0 |
| `.cursor-plugin/plugin.json` | Version 3.1.0 → 3.2.0 |

**Not changed:** `commands/pipeline.md`, `commands/pipeline-parallel.md`, all existing agents,
`hooks/*`, `scripts/check_plan.py`.

## 10. Verification

1. **Diff check:** `git diff --no-index commands/pipeline.md commands/pipeline-all.md` shows
   only the §3 / §6 changes — no accidental edits to shared stages.
2. **Plugin validation:** `claude plugin validate .` passes (frontmatter of new agents and command).
3. **Dry run, placeholders:** in a scratch repo, run `/sdlc-pipeline:pipeline-all <small idea>`.
   Expect: preflight → one line for each placeholder → Stage 0.5 asks exactly two questions →
   continues as `pipeline.md` would with the raw request. Stop at the Stage 2.5 gate.
4. **Bug guard:** run with an obviously-broken-thing request; expect the redirect question.
5. **Template check:** every section in `requirements-template.md` has a Required/Optional
   marker and no EMV-specific text (`grep -i "emv\|zerobounce\|zoho"` returns nothing).

## 11. Out of scope

- Real instructions for `requirements-writer` and the QA agent (user will supply them).
- A parallel variant (`pipeline-all-parallel`).
- Hook changes (see §8 known limitation).
- Any change to `pipeline.md` or `pipeline-parallel.md`.

## 12. Open items for the user

1. The QA agent's final name and its outputs — needed to decide whether Stage Q gets an
   approval gate and how later stages (e.g. `qa-tester` at Stage 4.5) consume its outputs.
2. The full `requirements-writer` instructions — designed in
   `docs/superpowers/specs/2026-10-27-requirements-writer-design.md`.
