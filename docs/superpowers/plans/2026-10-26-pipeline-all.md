# `/pipeline-all` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a requirements-first, feature-only orchestrator `/sdlc-pipeline:pipeline-all`, with two placeholder agents (`requirements-writer`, `qa-placeholder`) and a requirements template, without changing the existing pipelines.

**Architecture:** `commands/pipeline-all.md` is a copy of `commands/pipeline.md`. The copy has the bug and nano tracks removed and three new stages (Stage 0 bug guard, Stage R requirements, Stage Q QA slot) inserted before the testing-preference questions. Both new agents are placeholders that return `status: PLACEHOLDER`. The orchestrator handles that status by continuing, so the command works end to end today, and only the agent bodies change when the real instructions arrive.

**Tech Stack:** Claude Code plugin (Markdown commands and agents with YAML frontmatter, JSON manifests). Verification uses `grep`, `awk`, `git diff`, `python -c` (JSON parse) and `claude plugin validate .`.

**Spec:** `docs/superpowers/specs/2026-10-26-pipeline-all-design.md`

## Global Constraints

- Do NOT modify `commands/pipeline.md`, `commands/pipeline-parallel.md`, any existing file in `agents/`, `hooks/*` or `scripts/*`.
- New agent names, exactly: `requirements-writer`, `qa-placeholder`.
- New paths, exactly: `commands/pipeline-all.md`, `agents/requirements-writer.md`, `agents/qa-placeholder.md`, `templates/requirements-template.md`.
- Requirements output path used by the pipeline: `docs/features/<slug>.requirements.md`. Contract path: `docs/features/<slug>.requirements.contract.md`.
- Plugin-root reference inside commands: `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` (works in Claude Code and Cursor).
- Version: `3.1.0` → `3.2.0` in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json`.
- The repo's context-budget hook blocks a full `Read` of any file over 250 lines / 20,000 bytes (including through `cat`). `commands/pipeline-all.md` is about 500 lines, so read it in chunks with `offset`/`limit` (≤200 lines each) before editing.
- Work on branch `feature/pipeline-all`. Never commit to `master`. Do not push.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Action | Responsibility |
|---|---|---|
| `templates/requirements-template.md` | Create | The 23-section requirements template the requirements agent fills |
| `agents/requirements-writer.md` | Create | Placeholder agent for Stage R plus its full I/O contract |
| `agents/qa-placeholder.md` | Create | Placeholder agent for Stage Q plus its I/O contract |
| `commands/pipeline-all.md` | Create | The new orchestrator (copy of `pipeline.md`, trimmed and extended) |
| `README.md` | Modify | Counts, usage example, workflow diagram |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json` | Modify | Version bump |

---

### Task 1: Requirements template

**Files:**
- Create: `templates/requirements-template.md`

**Interfaces:**
- Consumes: nothing.
- Produces: `templates/requirements-template.md`. Stage R passes it to `requirements-writer` as `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/templates/requirements-template.md`. The section numbers §10, §11, §18, §19, §21 and §22 are referenced by the agent contract in Task 2.

- [ ] **Step 1: Create the branch**

The spec and this plan are uncommitted files on `master`. They move to the new branch with
the checkout and are committed there first.

```bash
git checkout -b feature/pipeline-all
git add docs/superpowers/specs/2026-10-26-pipeline-all-design.md docs/superpowers/plans/2026-10-26-pipeline-all.md
git commit -m "docs: add /pipeline-all design spec and implementation plan

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `Switched to a new branch 'feature/pipeline-all'`, then a commit touching 2 files.

- [ ] **Step 2: Run the template checks and confirm they fail**

```bash
test -f templates/requirements-template.md && echo EXISTS || echo MISSING
```

Expected: `MISSING`

- [ ] **Step 3: Write the template**

Create `templates/requirements-template.md` with exactly this content:

~~~markdown
# <Feature name> — Business Requirements

<!--
sdlc-pipeline requirements template v1.
- Fill every section marked _Required_. An _Optional_ section may be deleted, or kept with
  "Not applicable."
- IDs (BR-, VAL-, AC-, Q-) start at 001 and are never reused.
- Technical detail (table names, endpoints, regexes, services) is allowed ONLY under a
  "### Technical notes" heading, and only in sections 10, 11, 18 and 21. Everything else
  stays business-level.
- Delete these HTML comments when filling in the template.
-->

| Field | Value |
|---|---|
| Version | 0.1 |
| Date | YYYY-MM-DD |
| Status | Draft |
| Source | <client request and/or input file paths> |

## 1. Purpose
_Required_

<!-- 2–4 sentences: what this feature is and the business problem it solves. -->

## 2. Business Objective
_Required_

- **Primary objective:** <!-- the single most important outcome -->
- **Expected business outcome:**
- **Success measure:** <!-- measurable: a number, a percentage or a time -->
- **Target users:**
- **Business owner:**

## 3. Background
_Optional_

<!-- How things work today and why the change is needed now. -->

## 4. Scope
_Required_

### In Scope

- <!-- one bullet per capability; each is covered by at least one AC in §19 -->

### Out of Scope

- <!-- at least one entry: something a reader might expect that this feature will not do -->

## 5. Users and Roles
_Required_

| Role | Description | Main Actions |
|---|---|---|
| | | |

## 6. Business Process
_Optional_

### Current Process

1.

### Proposed Process

1.

## 7. User Journeys
_Required_

<!-- One journey per main path. Copy the block for each journey. -->

### Journey 1 — <name>

**Actor:**
**Trigger:**
**Preconditions:**
**Flow:**
1.

**Expected Result:**

## 8. Business Rules
_Required_

| Rule ID | Rule Description | Priority | Notes |
|---|---|---|---|
| BR-001 | | Must Have / Should Have / Could Have / Won't Have | |

## 9. Validation Rules
_Optional — Required when the feature takes user input_

| Validation ID | Field / Condition | Validation | Expected Error Message |
|---|---|---|---|
| VAL-001 | | | |

## 10. Data Requirements
_Optional_

| Data Item | Required | Source | Validation | Notes |
|---|---:|---|---|---|
| | | | | |

### Technical notes
_Optional_

<!-- Storage, schemas, field names. -->

## 11. Statuses and State Changes
_Optional_

| Entity | Current Status | Action | New Status | Conditions |
|---|---|---|---|---|
| | | | | |

### Technical notes
_Optional_

## 12. Notifications and Messages
_Optional_

| Trigger | Recipient | Channel | Message / Template |
|---|---|---|---|
| | | | |

## 13. Error Scenarios
_Required_

| Scenario | Expected Behaviour | User Message |
|---|---|---|
| | | |

## 14. Positive Scenarios
_Optional_

| Scenario | Expected Result |
|---|---|
| | |

## 15. Edge Cases
_Required_

-

## 16. Reporting and Audit Requirements
_Optional_

- **Events to audit:**
- **Reports required:**

## 17. Non-functional Requirements
_Required_

<!-- "None beyond platform defaults" is a valid entry for any row. -->

| Area | Requirement |
|---|---|
| Performance | |
| Availability | |
| Scalability | |
| Accessibility | |
| Browser / device support | |

## 18. Security and Compliance Requirements
_Required — never omit_

<!-- Access control, data protection, secrets, audit, regulatory. If nothing changes, write
"No new security surface" and say why. -->

-

### Technical notes
_Optional_

## 19. Business Acceptance Criteria
_Required_

<!-- Every In-Scope item and every Must Have BR is covered by at least one AC. -->

### AC-001 — <name>

**Covers:** BR-001

**Given**

**When**

**Then**

## 20. Assumptions
_Required_

<!-- May be "None". -->

-

## 21. Dependencies
_Optional_

-

### Technical notes
_Optional_

## 22. Open Questions
_Required_

<!-- The table may be empty. A question that changes scope must be Resolved before approval. -->

| Question ID | Question | Owner | Status | Decision |
|---|---|---|---|---|
| Q-001 | | | Open / Resolved | |

## 23. Business Definition of Done
_Required_

The requirements are ready for planning when:

- [ ] Every Required section is filled (or explicitly "None").
- [ ] Every In-Scope item is covered by at least one AC.
- [ ] Every Must Have BR is referenced by at least one AC.
- [ ] Security (§18) is filled.
- [ ] No Open Question that changes scope remains Open.
~~~

- [ ] **Step 4: Run the template checks and confirm they pass**

```bash
grep -c '^## [0-9]\+\. ' templates/requirements-template.md
awk '/^## [0-9]+\. /{h=$0; getline; if ($0 !~ /^_(Required|Optional)/) {print "MISSING MARKER: " h; bad=1}} END{exit bad}' templates/requirements-template.md && echo MARKERS_OK
grep -ciE 'emv|zerobounce|zoho|supabase|campaign' templates/requirements-template.md
```

Expected, in order: `23`, `MARKERS_OK`, `0`

- [ ] **Step 5: Commit**

```bash
git add templates/requirements-template.md
git commit -m "feat: add requirements template for /pipeline-all

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Placeholder agents

**Files:**
- Create: `agents/requirements-writer.md`
- Create: `agents/qa-placeholder.md`

**Interfaces:**
- Consumes: the template path from Task 1.
- Produces: two dispatchable agents whose return contract Task 3's orchestrator relies on.
  - `requirements-writer` returns `status: DONE | NEEDS_CONTEXT | PLACEHOLDER`. With `DONE` it also returns `path`, `counts`, `summary` and `open_questions`; with `NEEDS_CONTEXT` it returns `questions`; it always returns `turns`.
  - `qa-placeholder` returns `status: DONE | NEEDS_INPUT | PLACEHOLDER`. With `DONE` it also returns `outputs` and `summary`; with `NEEDS_INPUT` it returns `questions`; it always returns `turns`.

- [ ] **Step 1: Confirm the agents do not exist yet**

```bash
ls agents/requirements-writer.md agents/qa-placeholder.md 2>&1 | grep -c "No such file"
```

Expected: `2`

- [ ] **Step 2: Write `agents/requirements-writer.md`**

~~~markdown
---
name: requirements-writer
description: Turns a feature idea (text and/or files) into a requirements document that follows the plugin's requirements template. Asks the client only for major gaps; otherwise writes the file for confirmation. Invoked by /pipeline-all at Stage R, never directly by the client.
tools: Read, Grep, Glob, Write, Edit
model: sonnet
---

> **PLACEHOLDER — instructions to be added.**
> Until this notice is removed: do not read or write any file, and ignore everything below
> the line. Return exactly:
>
> ```
> status: PLACEHOLDER
> turns: 1
> ```

---

The sections below are the contract that the real instructions must keep. `/pipeline-all`
Stage R depends on them.

## Inputs

| Field | Meaning |
|---|---|
| `mode` | `draft` or `revision` |
| `request` | the client's request, verbatim |
| `input_files` | paths of any files the client referenced, or `none` |
| `template` | path to `templates/requirements-template.md` in the plugin |
| `output` | `docs/features/<slug>.requirements.md` |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_CONTEXT` questions (draft mode, optional) |
| `feedback` | the client's change requests, verbatim (revision mode only) |
| `question_round` | 0, 1 or 2. At 2 you must not return `NEEDS_CONTEXT` |

## Major questions only

Return `NEEDS_CONTEXT` only when the answer would change what the feature *is*: its purpose,
who uses it, what is in or out of scope, or a core user journey. Do this only when the answer
is not in the input or the codebase. Record everything else in §22 Open Questions (status
`Open`) or §20 Assumptions, and draft anyway. Ask at most 7 questions per round, in plain
language a non-technical client can answer.

## Output rules

- Follow the template's section numbering and ID schemes (BR-, VAL-, AC-, Q-).
- Fill every `_Required_` section. §18 Security is never omitted.
- Technical detail goes only under `### Technical notes` in §10, §11, §18 and §21.
- Revision mode: `Edit` only the sections the feedback touches; never regenerate the file.

## Constraints

- Read large inputs in chunks with `offset`/`limit`. The context-budget hook blocks full
  reads over 250 lines / 20,000 bytes.
- Write forward. Never re-read or measure your own output.
- Read code only with targeted `Grep`, then `Read` around the hit, and only to ground scope
  and existing behaviour.
- Never write production code, plans or tests.

## Return

```
status: DONE | NEEDS_CONTEXT | PLACEHOLDER
path: <output path>                     (DONE only)
counts: BR n · VAL n · AC n · Open Q n  (DONE only)
summary: ≤5 lines                       (DONE only)
open_questions: numbered, one line each (DONE only; items still Open)
questions: numbered list                (NEEDS_CONTEXT only)
turns: <n>
```
~~~

- [ ] **Step 3: Write `agents/qa-placeholder.md`**

~~~markdown
---
name: qa-placeholder
description: Reserved slot for the QA team's requirements-stage agent. Runs right after requirements are approved and may ask the client for input. Invoked by /pipeline-all at Stage Q, never directly by the client.
tools: Read, Grep, Glob, Write, Edit
model: sonnet
---

> **PLACEHOLDER — instructions to be added.**
> Until this notice is removed: do not read or write any file, and ignore everything below
> the line. Return exactly:
>
> ```
> status: PLACEHOLDER
> turns: 1
> ```

---

The sections below are the contract that the real instructions must keep. `/pipeline-all`
Stage Q depends on them. When this agent is renamed, also update its `name:` field and the
Stage Q dispatch line in `commands/pipeline-all.md`.

## Inputs

| Field | Meaning |
|---|---|
| `requirements` | path to the approved `docs/features/<slug>.requirements.md`, or `none` |
| `request` | the client's request, verbatim |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_INPUT` questions (optional) |

## Constraints

- Read large inputs in chunks with `offset`/`limit`. The context-budget hook blocks full
  reads over 250 lines / 20,000 bytes.
- Ask the client only what you cannot find in the requirements file or the codebase. Ask at
  most 7 questions per round, at most 2 rounds.

## Return

```
status: DONE | NEEDS_INPUT | PLACEHOLDER
outputs: <path list>        (DONE only)
summary: ≤5 lines           (DONE only)
questions: numbered list    (NEEDS_INPUT only)
turns: <n>
```
~~~

- [ ] **Step 4: Validate the plugin**

```bash
claude plugin validate . 2>&1 | grep -c "Found"
claude plugin validate . 2>&1 | grep -E "requirements-writer|qa-placeholder"
claude plugin validate . 2>&1 | tail -1
```

Expected, in order:
- `13`, the baseline count: the 13 existing `commands/agent-*.md` pointer files each give a "No frontmatter block found" warning.
- No output.
- `✔ Validation passed with warnings`

- [ ] **Step 5: Commit**

```bash
git add agents/requirements-writer.md agents/qa-placeholder.md
git commit -m "feat: add requirements-writer and qa-placeholder placeholder agents

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `/pipeline-all` orchestrator

**Files:**
- Create: `commands/pipeline-all.md` (copied from `commands/pipeline.md`, then edited)

**Interfaces:**
- Consumes: the agent names and return contracts from Task 2 and the template path from Task 1.
- Produces: the command `/sdlc-pipeline:pipeline-all`.

All edits below are exact-string replacements on `commands/pipeline-all.md`. Line numbers refer to the unedited copy (they match `commands/pipeline.md` at commit `ce7cc2d`). Read the file in chunks first (see Global Constraints).

- [ ] **Step 1: Write the structural check and confirm it fails**

```bash
test -f commands/pipeline-all.md && grep -n '^## ' commands/pipeline-all.md || echo MISSING
```

Expected: `MISSING`

- [ ] **Step 2: Copy the sequential pipeline**

```bash
cp commands/pipeline.md commands/pipeline-all.md
```

- [ ] **Step 3: Replace the frontmatter and title (lines 1–12)**

old:
```
description: End-to-end feature/bug pipeline. Ask type + testing prefs → Plan (features) or Investigate (bugs) → reviews → CLIENT APPROVES PLAN → Execute (TDD if requested) → Unit test → QA → Code+Security review → Docs → Ship PR.
argument-hint: <feature or bug description>
---

# /pipeline — Autonomous SDLC Orchestrator
```

new:
```
description: Requirements-first feature pipeline. Requirements doc (client approves) → QA slot → testing prefs → Plan → reviews → CLIENT APPROVES PLAN → Execute (TDD if requested) → Unit test → QA → Code+Security review → Docs → Ship PR. Features only — bugs use /pipeline.
argument-hint: <feature idea text and/or file path(s)>
---

# /pipeline-all — Requirements-first SDLC Orchestrator
```

Then, old:
```
Client request: $ARGUMENTS
```

new:
```
Client request: $ARGUMENTS

This command builds **features only**, starting from a requirements document. Bugs go
through `/sdlc-pipeline:pipeline` (see Stage 0).
```

- [ ] **Step 4: Replace Stage 0 and the top of Stage 0.5 (lines 67–89) with Stage 0, Stage R, Stage Q and the new Stage 0.5 questions**

old:
```
## Stage 0 — Classify

Read the request and pick a tier:
- **nano** — typo, copy change, config tweak, one-liner. Skip Stages 1–2:
  `implementer` → `code-reviewer` only → `ship-pr`.
- Everything else → the client confirms bug vs feature in Stage 0.5.
Announce the tier in one line, on the same turn as the Stage 0.5 question.

## Stage 0.5 — Type + testing preferences (EVERY non-nano run)

Ask the client three plain-language questions (ONE batched AskUserQuestion;
never say "TDD" without explaining it):

1. **Bug or feature?** "Is something broken that we're fixing, or is this new
   functionality / a change?" → sets `TYPE: bug|feature`
   (If the request makes it obvious, pre-select the recommended answer but
   still confirm — the client owns this call.)
2. **Test-first development?** "Should we write automated tests before each piece
   of code? Slightly slower per step, much safer result. (recommended)"
   → sets flag `TDD: on|off`
3. **Unit-test round?** "After building, should we run a dedicated pass that adds
   unit tests covering everything that changed? (recommended)"
   → sets flag `UNIT_TESTS: on|off`
```

new:
~~~
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
   requirements path is `docs/features/<slug>.requirements.md`. If it already exists, ask
   once: **Use the existing file** (show its path and go straight to the step-4 question) |
   **Regenerate** (overwrite it).
2. **Dispatch `requirements-writer`** with:
   - `mode: draft`, `question_round: 0`
   - `request`: the client request, verbatim
   - `input_files`: paths of any files the client referenced, or `none`
   - `template`: `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/templates/requirements-template.md`
   - `output`: the requirements path
   - `repo_root`
3. **`NEEDS_CONTEXT`** → relay its numbered questions to the client in ONE batched message,
   then re-dispatch in `draft` mode with `answers` and `question_round` + 1. At
   `question_round: 2` the agent must draft, recording anything still unknown as Open
   Questions and Assumptions.
4. **`DONE` → client confirmation.** In ONE turn show the requirements path, the agent's
   summary, its counts (BR / VAL / AC / Open Q) and its list of questions still Open. Then
   ask with `AskUserQuestion`: **Approve requirements** | **Request changes**.
   - **Request changes** → take the client's feedback verbatim and re-dispatch in
     `revision` mode with `feedback`, plus the same `request`, `template`, `output` and
     `repo_root`. Return to this step.
   - Count each revision in `requirements_revisions`. **At 4, stop** and say:

     > We've revised the requirements 4 times. Options: (a) approve as-is and keep the
     > remaining points as Open Questions, (b) keep revising, (c) restart from a tightened
     > brief.
5. **`PLACEHOLDER`** → say `Requirements agent not yet implemented — continuing with the raw
   request.` on the same turn as the Stage Q dispatch, record `REQUIREMENTS: none`, and go
   to Stage Q. No gate.
6. Ledger: `REQUIREMENTS: <path> (approved, rounds: N)` or `REQUIREMENTS: none`.

You do not read the requirements file. Everything you show the client comes from the agent's
return, and the client opens the file themselves. Never start Stage Q without an approval or
`REQUIREMENTS: none` in the ledger.

## Stage Q — QA slot

Dispatch `qa-placeholder` with `requirements` (the approved path, or `none`), `request`
(verbatim) and `repo_root`.

- **`NEEDS_INPUT`** → relay its numbered questions to the client in ONE batched message and
  re-dispatch with `answers`. At most 2 question rounds.
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
~~~

- [ ] **Step 5: Replace the top of Stage 0.8 (lines 95–108)**

old:
~~~
## Stage 0.8 — Distil the source documents (MANDATORY when a spec is referenced)

1. `wc -c -l <spec>`. Estimate tokens as `chars / 3`.
2. Under 4,000 tokens → pass the path directly, note it in the ledger, skip to Stage 1.
3. Otherwise dispatch **one** `distiller` with the spec path and output path
   `docs/features/<slug>.contract.md`.

After this stage **only the `distiller` and the Stage-1 `planner` may read the original.**
Everyone else reads the contract. Global Constraints must record:

```
Source of truth: docs/features/<slug>.contract.md
  (distilled from docs/features/<original>.md — do not read the original)
```
~~~

new:
~~~
## Stage 0.8 — Distil the requirements (MANDATORY when a source document exists)

`<source>` is the approved requirements file, `docs/features/<slug>.requirements.md`. If the
ledger says `REQUIREMENTS: none`, `<source>` is any spec the client referenced instead; if
there is none, skip to Stage 1.

1. `wc -c -l <source>`. Estimate tokens as `chars / 3`.
2. Under 4,000 tokens → pass the path directly, note it in the ledger, skip to Stage 1.
3. Otherwise dispatch **one** `distiller` with `<source>` and the output path
   `<contract>` = `docs/features/<source stem>.contract.md`. For the requirements file that
   is `docs/features/<slug>.requirements.contract.md`. The name must be
   `<source stem>.contract.md`, because the context-budget hook links an original to its
   contract by filename stem.

After this stage **only the `distiller` and the Stage-1 `planner` may read the original.**
Everyone else reads the contract. Global Constraints must record:

```
Source of truth: <contract>
  (distilled from <source> — do not read the original)
```
~~~

- [ ] **Step 6: Delete Stage 1-B (lines 116–130)**

old:
```
## Stage 1-B — Investigate (BUG track — no planner)

Dispatch the `investigator` agent (gstack /investigate +
superpowers:systematic-debugging) with the bug report verbatim and repo root.

- If it returns NEEDS_CONTEXT (reproduction steps, expected vs actual behavior,
  environment), relay to the client as ONE batched message, re-dispatch with answers.
- Output: a **mini-plan** at `docs/bugs/<slug>.md` — root cause with evidence,
  Task 1: failing test that reproduces the bug, Task 2: minimal fix, exact file list.
- **Escalation rule:** fix touches ≤3 files → proceed. More files, or the
  investigation reveals a design problem → return ESCALATE; hand the findings
  to `planner` and switch to the feature track (Stages 1–2).
- The bug track skips the Stage 2 gauntlet: the mini-plan goes straight to
  Stage 2.5 client approval. Code + security review still gate the diff at Stage 5.

## Stage 1 — Plan (FEATURE track, sequential)
```

new:
```
## Stage 1 — Plan (FEATURE track, sequential)
```

- [ ] **Step 7: Make the single-line edits in Stages 1–6**

Apply each replacement (each old string occurs exactly once):

| # | Line | old | new |
|---|---|---|---|
| a | 133 | ``Dispatch `planner` with: client request verbatim, tier, TDD/UNIT_TESTS flags, repo root,`` | ``Dispatch `planner` with: client request verbatim, `tier: full`, TDD/UNIT_TESTS flags, repo root,`` |
| b | 161 | `wc -c docs/plans/<slug>/*.md docs/plans/<slug>/.review/*.md docs/features/<slug>.contract.md` | `wc -c docs/plans/<slug>/*.md docs/plans/<slug>/.review/*.md <contract>` |
| c | 176 | `      docs/features/<slug>.contract.md \` | `      <contract> \` |
| d | 177 | `      docs/features/<original-spec>.md` | `      <source>` |
| e | 233 | ``- `ceo-reviewer` — gstack /plan-ceo-review; skip for bug tier`` | ``- `ceo-reviewer` — gstack /plan-ceo-review`` |
| f | 296 | ``1. From latest main create `feature/<slug>` · `fix/<slug>` · `hotfix/<slug>`. Verify a`` | ``1. From latest main create `feature/<slug>`. Verify a`` |
| g | 337 | see the code block below this table | see the code block below this table |
| h | 400 | `branch. Skip for nano tier.` | `branch.` |
| i | 417 | ``Dispatch `ship-pr` with repo root + branch, plan/bug file path, review verdicts, test`` | ``Dispatch `ship-pr` with repo root + branch, plan file path, review verdicts, test`` |

Row g (line 337) — the line starts with a backtick, so here it is as a code block.

old:
```
`/pipeline` session pointed at the existing branch — a paused run still consumes the
```

new:
```
`/pipeline-all` session pointed at the existing branch — a paused run still consumes the
```

- [ ] **Step 8: Surface the requirements' Open Questions at plan approval (Stage 2.5, lines 255–257)**

old:
```
key decisions), the `00-overview.md` path, the contract's `UNCONFIRMED` items, and an
`AskUserQuestion`: **Approve and build** | **Request changes**.
```

new:
```
key decisions), the `00-overview.md` path, the contract's `UNCONFIRMED` items, any
requirements Open Questions still Open (from Stage R's return), and an
`AskUserQuestion`: **Approve and build** | **Request changes**.
```

- [ ] **Step 9: Extend the token ledger (lines 430–433)**

old:
```
TOKEN LEDGER
  build_mode: <run to completion | checkpoint | per-task>
```

new:
```
TOKEN LEDGER
  requirements: <path> (approved, rounds: N) | none
  requirements_dispatches: N   requirements_revisions: N / 4
  qa_slot: DONE (<outputs>) | PLACEHOLDER   qa_input_rounds: N / 2
  build_mode: <run to completion | checkpoint | per-task>
```

- [ ] **Step 10: Add the hard rules (after line 450)**

old:
```
- Never start implementation before explicit client approval (Stage 2.5).
```

new:
```
- Never start implementation before explicit client approval (Stage 2.5).
- Never skip the Stage R client confirmation when `requirements-writer` returned `DONE`.
- Never start Stage 0.5 before Stage R and Stage Q have finished.
- `/pipeline-all` runs features only. A clear bug request gets the Stage 0 redirect question.
```

- [ ] **Step 11: Run the structural checks and confirm they pass**

```bash
grep -n '^## ' commands/pipeline-all.md
```

Expected, exactly these headings in this order:

```
## Context discipline
## Stage -1 — Preflight (ALWAYS FIRST)
## Stage 0 — Bug guard
## Stage R — Requirements (HARD GATE)
## Stage Q — QA slot
## Stage 0.5 — Testing preferences (after Stage R and Stage Q)
## Stage 0.8 — Distil the requirements (MANDATORY when a source document exists)
## Stage 1 — Plan (FEATURE track, sequential)
## Stage 2 — Plan review gauntlet (PARALLEL)
## Stage 2.5 — Client plan approval (HARD GATE)
## Stage 2.7 — ADR (feature track, only if architecture changes)
## Stage 3 — Execute (superpowers:executing-plans, dedicated branch)
## Stage 3.9 — Build complete checkpoint
## Stage 4 — Unit test gate (only if UNIT_TESTS: on)
## Stage 4.5 — QA scenario gate (skip if no user-facing surface)
## Stage 4.9 — Pre-review checkpoint
## Stage 5 — Code + Security review (PARALLEL)
## Stage 5.5 — Performance gate (only if a task is `perf-sensitive: true`)
## Stage 5.8 — Documentation
## Stage 5.9 — Pre-ship checkpoint
## Stage 6 — Ship
## Token ledger
## Hard rules
```

(The bash snippet comment `# Works in both Claude ...` inside Stage 2 also matches `^#`, but not `^## `.)

Then check that the removed tracks are gone and the new names are wired:

```bash
grep -cE 'Stage 1-B|investigator|nano|TYPE: bug|docs/bugs|hotfix|skip for bug tier|plan/bug|<slug>\.contract\.md|<original-spec>' commands/pipeline-all.md
grep -c 'requirements-writer' commands/pipeline-all.md
grep -c 'qa-placeholder' commands/pipeline-all.md
grep -c 'templates/requirements-template.md' commands/pipeline-all.md
git diff --exit-code commands/pipeline.md commands/pipeline-parallel.md && echo ORIGINALS_UNCHANGED
```

Expected, in order: `0`, `≥2`, `≥1`, `1`, `ORIGINALS_UNCHANGED`

- [ ] **Step 12: Validate the plugin**

```bash
claude plugin validate . 2>&1 | grep -c "Found"
claude plugin validate . 2>&1 | grep "pipeline-all"
claude plugin validate . 2>&1 | tail -1
```

Expected, in order: `13` (the baseline, unchanged), no output, `✔ Validation passed with warnings`.

- [ ] **Step 13: Review the full diff against the original**

```bash
git diff --no-index --stat commands/pipeline.md commands/pipeline-all.md
git diff --no-index commands/pipeline.md commands/pipeline-all.md > "$TEMP/pipeline-all.diff"; echo "diff written"
```

Read `$TEMP/pipeline-all.diff` in chunks. Every hunk must correspond to Steps 3–10. Revert any other change.

- [ ] **Step 14: Commit**

```bash
git add commands/pipeline-all.md
git commit -m "feat: add /pipeline-all requirements-first feature orchestrator

Copy of /pipeline without the bug and nano tracks, with Stage 0 bug guard,
Stage R (requirements-writer, client approval loop) and Stage Q (QA slot)
before the testing-preference questions.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: README and version bump

**Files:**
- Modify: `README.md:11-12`, insert after `README.md:141`, insert after `README.md:169`
- Modify: `.claude-plugin/plugin.json:4`, `.claude-plugin/marketplace.json:12`, `.cursor-plugin/plugin.json:4`

**Interfaces:**
- Consumes: the command and agent names from Tasks 2–3.
- Produces: nothing other tasks use.

- [ ] **Step 1: Confirm the current state**

```bash
grep -c '3.2.0' .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json
grep -c 'pipeline-all' README.md
```

Expected: each file `0`, then `0`.

- [ ] **Step 2: Update the "What's inside" rows (README lines 11–12)**

old:
```
| Commands | 1 | `/pipeline` — the end-to-end orchestrator |
| Agents | 14 | Specialist sub-agents: planner, investigator, implementer, reviewers (code, security, eng, design, CEO, perf), unit-tester, qa-tester, adr-writer, doc-writer, ship-pr |
```

new:
```
| Commands | 3 | `/pipeline` (features and bugs), `/pipeline-parallel` (parallel task waves), `/pipeline-all` (requirements-first, features only) |
| Agents | 17 | Specialist sub-agents: requirements-writer and qa-placeholder (placeholders), distiller, planner, investigator, implementer, reviewers (code, security, eng, design, CEO), perf-tester, unit-tester, qa-tester, adr-writer, doc-writer, ship-pr |
```

- [ ] **Step 3: Add Example 4 (insert after README line 141, before `## Workflow`)**

old:
```
Nano changes skip planning and reviews entirely: `implementer` → `code-reviewer` → `ship-pr`. Fast path, still reviewed.
```

new:
~~~
Nano changes skip planning and reviews entirely: `implementer` → `code-reviewer` → `ship-pr`. Fast path, still reviewed.

### Example 4 — start from an idea (requirements first)

```
/sdlc-pipeline:pipeline-all Let sales managers export filtered contact lists as CSV
```

`/pipeline-all` is for features only. It first turns your idea (text, or a file path such as `docs/ideas/export.md`) into a requirements document based on the plugin's template, and asks you only about major gaps. You approve the document or ask for changes. A QA step runs next, and from the testing questions onward the run is the same as Example 1.

In this release the requirements and QA agents are placeholders: each reports "not yet implemented" and the run continues with your original request.
~~~

- [ ] **Step 4: Add the `/pipeline-all` workflow (insert after README line 169)**

old:
```
`∥` = stages run in parallel. Token usage is tracked per run by the bundled hooks.
```

new:
~~~
`∥` = stages run in parallel. Token usage is tracked per run by the bundled hooks.

`/pipeline-all` runs a requirements-first version of the feature track:

```
idea (text and/or files)
   │
   ▼
Stage -1   Preflight
Stage 0    Bug guard (bugs → /pipeline)
Stage R    Requirements (requirements-writer) ── ★ YOU APPROVE THE REQUIREMENTS ★
Stage Q    QA slot (qa-placeholder), may ask you for input
Stage 0.5  Your preferences: TDD, unit tests
Stage 0.8  Distil requirements → contract
Stage 1 →  Same as the FEATURE track above (plan, reviews, ★ plan approval ★, build, gates, ship)
```
~~~

- [ ] **Step 5: Bump the version in all three manifests**

In each of `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` and `.cursor-plugin/plugin.json`:

old: `"version": "3.1.0",`
new: `"version": "3.2.0",`

- [ ] **Step 6: Verify**

```bash
python -c "import json; [json.load(open(f, encoding='utf-8')) for f in ['.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', '.cursor-plugin/plugin.json']]; print('JSON_OK')"
grep -c '"version": "3.2.0"' .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json
grep -c 'pipeline-all' README.md
claude plugin validate . 2>&1 | grep -c "Found"
claude plugin validate . 2>&1 | tail -1
```

Expected, in order: `JSON_OK`; `1` for each file; `≥4`; `13` (the baseline); `✔ Validation passed with warnings`.

- [ ] **Step 7: Commit**

```bash
git add README.md .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json
git commit -m "docs: document /pipeline-all and bump version to 3.2.0

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: End-to-end dry run (manual)

This needs an interactive Claude Code session with superpowers, gstack and claude-mem installed, so preflight passes. Nothing is committed in this task.

**Files:** none (a scratch git repo outside this one).

- [ ] **Step 1: Prepare a scratch repo**

```bash
mkdir -p "$TEMP/pipeline-all-dryrun" && cd "$TEMP/pipeline-all-dryrun" && git init -q && git commit -q --allow-empty -m init && echo READY
```

Expected: `READY`

- [ ] **Step 2: Start Claude Code with the local plugin**

```bash
claude --plugin-dir "C:/Users/EMVIGO-USER/Muhassin/workspace/sdlc-pipeline"
```

If the marketplace copy of `sdlc-pipeline` is also installed, disable it for this session (`/plugin`) so the local copy is the one that runs.

- [ ] **Step 3: Feature run with placeholders**

In that session run:

```
/sdlc-pipeline:pipeline-all Let users export their saved reports as CSV
```

Expected:
1. Preflight is silent (or prints only the cache warning).
2. No bug question.
3. One line: `Requirements agent not yet implemented — continuing with the raw request.`
4. One line: `QA agent not yet implemented — skipping.`
5. Stage 0.5 asks exactly **two** questions (test-first, unit-test round) and does not ask bug vs feature.
6. The planner is dispatched next. Stop the run here (Esc).

- [ ] **Step 4: Bug guard**

```
/sdlc-pipeline:pipeline-all The login button no longer works after session timeout
```

Expected: the "This looks like a bug" question. Choose **Stop — I'll use /pipeline**, and the run ends with one line naming `/sdlc-pipeline:pipeline`.

- [ ] **Step 5: Record the result**

If both runs match, the branch is ready for review. If not, note the stage and the actual output, and fix it in `commands/pipeline-all.md` with a new commit on `feature/pipeline-all`.

---

## Spec coverage

| Spec section | Task |
|---|---|
| §3 Stage flow, removed tracks, bug guard | Task 3 Steps 4, 6, 7 |
| §4 Stage R orchestrator steps | Task 3 Step 4 |
| §4.2–4.3 `requirements-writer` contract and placeholder | Task 2 Step 2 |
| §5 Stage Q and `qa-placeholder` | Task 3 Step 4, Task 2 Step 3 |
| §6 Changes to copied stages (0.5, 0.8, 1, 2.5, ledger, hard rules) | Task 3 Steps 4, 5, 7, 8, 9, 10 |
| §7 Template | Task 1 |
| §8 Hook fit (chunked reads, contract naming) | Task 2 contracts, Task 3 Step 5, Global Constraints |
| §9 Files (README, versions) | Task 4 |
| §10 Verification | Task 1 Step 4, Task 2 Step 4, Task 3 Steps 11–13, Task 4 Step 6, Task 5 |
