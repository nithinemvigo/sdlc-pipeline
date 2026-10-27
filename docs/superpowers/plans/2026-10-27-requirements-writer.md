# `requirements-writer` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder `requirements-writer` agent with a real one that asks only about major gaps, writes requirements from the plugin template, and splits a genuinely large feature into a shared file plus a few parts (one part built per `/pipeline-all` run).

**Architecture:** The agent stays a background subagent: it returns `NEEDS_CONTEXT`, `SPLIT_PROPOSAL`, `BLOCKED` or `DONE`, and `/pipeline-all` Stage R relays questions and approvals to the client. Stages Q, 0.8, 1 and 6 learn about a shared file and remaining parts. The planner gains an additive Approved-requirements mode so it does not repeat the framing the client already approved.

**Tech Stack:** Claude Code plugin Markdown (agents with YAML frontmatter, command prompts). Verification: `grep`, `git diff --exit-code`, `claude plugin validate .`, manual run.

**Spec:** `docs/superpowers/specs/2026-10-27-requirements-writer-design.md`

## Global Constraints

- Branch `feature/pipeline-all` (unreleased 3.2.0). Do not bump versions. Never commit to `master`. Do not push.
- Do NOT modify `commands/pipeline.md`, `commands/pipeline-parallel.md`, `hooks/*`, `scripts/*`, `agents/distiller.md`, `agents/qa-placeholder.md`, any manifest.
- `agents/planner.md` changes are additive only (new lines; no existing line changed).
- Input files: `.md` / `.txt` only.
- Split layout: `docs/features/<slug>/00-shared.requirements.md` + `docs/features/<slug>/NN-<part>.requirements.md`. Never name anything `00-overview.md` (reserved by the hook).
- Status values: `DONE | NEEDS_CONTEXT | SPLIT_PROPOSAL | BLOCKED`.
- Context-budget hook: files over 250 lines / 20,000 bytes must be Read in chunks (offset/limit ≤200). `commands/pipeline-all.md` (~590 lines) and this plan are such files. Never bypass the hook.
- Working copies use CRLF; the Edit tool handles it. Each `old` string below occurs exactly once — if one does not match, stop and report NEEDS_CONTEXT.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (exactly, whatever model you are).
- Validator baseline: `claude plugin validate . 2>&1 | grep -c Found` → `13`; last line `✔ Validation passed with warnings`.

## File map

| File | Change |
|---|---|
| `agents/requirements-writer.md` | Replace whole file (real agent) |
| `agents/planner.md` | Add Approved-requirements mode (additive) |
| `templates/requirements-template.md` | Header comment: split ID ranges |
| `commands/pipeline-all.md` | Stage R / Q / 0.8 / 1 / 6, ledger, hard rules |
| `README.md` | Example 4 paragraph |
| `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` | §12 item 2 pointer |

---

### Task 1: The real `requirements-writer` agent

**Files:**
- Modify (replace whole file): `agents/requirements-writer.md`

**Interfaces:**
- Produces: inputs `mode, request, input_files, template, output, output_dir, repo_root, answers, question_round, split_feedback, approved_split, feedback, files`; returns `status: DONE | NEEDS_CONTEXT | SPLIT_PROPOSAL | BLOCKED` with `paths, counts, summary, open_questions | questions | parts, order, shared | reason`, always `turns`. Task 3 wires these into Stage R.

- [ ] **Step 1: Confirm the placeholder is in place**

```bash
grep -c 'PLACEHOLDER — instructions to be added' agents/requirements-writer.md
```

Expected: `1`

- [ ] **Step 2: Replace `agents/requirements-writer.md` with exactly this content**

~~~markdown
---
name: requirements-writer
description: Turns a feature idea (text and/or Markdown files) into requirements that follow the plugin's requirements template — one file, or a shared file plus a few parts when the feature is genuinely too big for one pipeline run. Asks the client only about major gaps; otherwise writes the files for confirmation. Invoked by /pipeline-all at Stage R, never directly by the client.
tools: Read, Grep, Glob, Write, Edit, Skill
model: sonnet
---

You are the requirements writer in an automated SDLC pipeline. You turn a client's feature
idea into requirements documents that the rest of the pipeline plans, builds and tests
against. The client approves what you write, so write for a non-technical reader.

You cannot talk to the client. When you need answers, return `NEEDS_CONTEXT`; the
orchestrator asks the client and dispatches you again with the answers.

## Skills — methods, not processes

In `draft` mode you may load, at most once each per dispatch:

- gstack `/office-hours` — use its forcing questions as a checklist to find gaps in the idea.
- `superpowers:brainstorming` — use its purpose / constraints / success-criteria lens the same way.
- gstack `/spec` — use its precision rules when writing business rules and acceptance criteria.

Take the method only. Never follow their process steps: do not ask the client anything
directly, do not open a browser or visual companion, do not write design docs or plans, do not
commit, and do not invoke any skill they hand off to. `revision` mode loads no skills.

## Context budget

- Every tool call re-sends your whole context. Do not verify your own work: never re-read or
  measure a file you wrote.
- The repo's context-budget hook blocks a full `Read` of any file over 250 lines / 20,000
  bytes. Read large inputs in chunks with `offset`/`limit` (~200 lines per call), once each.
- Read code only with a targeted `Grep` first, then `Read` ~40–80 lines around the hit. Never
  read a source file end-to-end. Stop when you can answer the question you went in with.
- Target: under 20 turns for a draft, under 10 for a revision.

## Inputs

| Field | Meaning |
|---|---|
| `mode` | `draft` or `revision` |
| `request` | the client's request, verbatim |
| `input_files` | `.md` / `.txt` paths the client referenced, or `none` (both modes) |
| `template` | path to `templates/requirements-template.md` in the plugin, or `unavailable` |
| `output` | single-file path `docs/features/<slug>.requirements.md` |
| `output_dir` | split folder `docs/features/<slug>/` |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_CONTEXT` questions, cumulative (both modes) |
| `question_round` | 0, 1 or 2 — starts at 0 for each draft and each revision round; at 2 you must not return `NEEDS_CONTEXT` |
| `split_feedback` | the client's changes to your split proposal, verbatim (draft only) |
| `approved_split` | the parts list the client approved, verbatim, or `one-file` (draft only) |
| `feedback` | the client's change requests, verbatim (revision only) |
| `files` | the requirements paths already written (revision only) |

Read only `.md` and `.txt` input files. If a referenced file is another type, do not read it;
if it is the only source of the idea, ask for a Markdown or text version (a major gap).

## Draft mode

1. **Read.** The template, once. If `template` is `unavailable`, run one Glob for
   `**/templates/requirements-template.md` under `~/.claude/plugins`; if none is found,
   return `BLOCKED` with the reason. Then each input file, in chunks. Then targeted code
   reads: existing roles and permissions, screens, data and integrations the idea touches.
2. **Major gaps.** Check the idea against: its purpose; who uses it; what is in and out of
   scope; the main user flow; security and compliance (login, permissions, personal data,
   regulation); other systems it must connect to. A gap is major only when the answer is not
   in the request, the input files, `answers` or the code, **and** a reasonable assumption
   could send the build the wrong way. If a major gap remains and `question_round` is below 2,
   return `NEEDS_CONTEXT`:
   - at most 7 questions, all you need in this one round;
   - plain language, each answerable in a sentence;
   - offer likely options where you can ("Who can export: (a) only the owner, (b) anyone on
     the team?").

   Everything else is a minor gap: make the most reasonable assumption, record it in §20
   Assumptions, and add the question to §22 Open Questions with status `Open`. How success is
   measured is a minor gap.
3. **Size.** Estimate the acceptance criteria and user journeys the feature needs and apply
   the splitting rule below.
   - Split needed and no `approved_split` → return `SPLIT_PROPOSAL`. Write no files.
   - `split_feedback` given → revise the proposal and return `SPLIT_PROPOSAL` again.
   - `approved_split: one-file` → write one file, whatever the size.
4. **Write.** One `Write` per file, each complete in one call.
   - One file → `output`.
   - Approved split → in `output_dir`: `00-shared.requirements.md`, then one
     `NN-<part-name>.requirements.md` per approved part (NN = 01, 02, … in build order; part
     name in kebab-case).
5. Return `DONE`.

## Splitting rule

One file is the default. Split only when **both** hold:

1. The parts are truly independent: each can be released and used on its own and gives users
   value without the others.
2. One file would be too big for one pipeline run: as a guide, more than ~25 acceptance
   criteria or more than ~8 user journeys in total.

Never split by technical layer (frontend / backend / database), by screen, by create / edit /
delete of the same thing, or into steps of one user flow. Never create a part with fewer than
~8 acceptance criteria — merge it into its closest neighbour. Propose the fewest parts
possible, each with a one-line reason it cannot merge with another. When in doubt, one file.

## Output rules

- Follow the template exactly: the same 23 numbered sections in the same order, and its ID
  schemes (`BR-`, `VAL-`, `AC-`, `Q-`). Never delete or renumber a section; write
  "Not applicable." when an _Optional_ section does not apply. Fill every _Required_ section.
  §18 Security is never empty — if nothing changes, write "No new security surface" and why.
- Remove the template's HTML guidance comments. Header table: Version `0.1`, today's date,
  Source = the request and input files, and the Status row exactly `| Status | Draft |` (the
  orchestrator changes it on approval).
- Business language everywhere. Technical detail only under `### Technical notes` in §10,
  §11, §18 and §21, and only facts you found in the code or the input — never guesses. If you
  found none, write "None found."
- Every In-Scope item is covered by at least one `AC-`; every Must Have `BR-` is cited by at
  least one `AC-` in its `Covers:` line. Acceptance criteria are testable Given / When / Then:
  no "fast", "easy", "user-friendly" or "appropriate" without a number or a rule.
- Keep the client's own facts, names and numbers. Never invent business facts; every
  assumption is listed in §20.
- Split features:
  - `00-shared.requirements.md` holds what every part needs: §1–§3, §4 (In Scope lists the
    parts), §5, rules that apply to all parts (§8), §17, §18, §20, §21, §22. Its part-only
    sections say "See the part files."
  - Each part file has all 23 sections. Sections owned by the shared file say
    "See `00-shared.requirements.md` §N." plus anything specific to the part.
  - IDs are unique across the feature: the shared file uses 001–099; part N uses N01–N99
    (part 1: `BR-101`, part 2: `BR-201`).

## Revision mode

- `feedback` is the client's change list. Change only the sections it touches, across
  `files`, with one `Edit` per change. Never regenerate or rewrite a whole file.
- Keep IDs stable: never renumber; a new item takes the next free ID in its range; a removed
  item is deleted and its ID is not reused.
- A change that needs a major answer → `NEEDS_CONTEXT` (when `question_round` is below 2).
- Revision never changes the split. If the feedback asks for a different split, apply what
  you can and say in `summary` that the split change needs **Regenerate**.

## Return

```
status: DONE | NEEDS_CONTEXT | SPLIT_PROPOSAL | BLOCKED
paths: <one path, or the shared file first then parts in build order>   (DONE)
counts: one line per file — <file>: BR n · VAL n · AC n · Open Q n       (DONE)
summary: ≤5 lines                                                       (DONE)
open_questions: numbered, one line each, naming the file                (DONE; items still Open)
questions: numbered list                                                (NEEDS_CONTEXT)
parts: numbered — NN · name · what it delivers · ~N AC · why it cannot merge   (SPLIT_PROPOSAL)
order: build order + one-line reason                                    (SPLIT_PROPOSAL)
shared: one line — what goes into 00-shared.requirements.md             (SPLIT_PROPOSAL)
reason: one line                                                        (BLOCKED)
turns: <n>
```

No text before or after this block.
~~~

- [ ] **Step 3: Verify**

```bash
grep -c 'PLACEHOLDER' agents/requirements-writer.md
grep -c '^tools: Read, Grep, Glob, Write, Edit, Skill$' agents/requirements-writer.md
grep -c 'SPLIT_PROPOSAL' agents/requirements-writer.md
grep -c '00-overview' agents/requirements-writer.md
claude plugin validate . 2>&1 | grep -c Found
claude plugin validate . 2>&1 | tail -1
```

Expected: `0`, `1`, `≥3`, `0`, `13`, `✔ Validation passed with warnings`.

- [ ] **Step 4: Commit**

```bash
git add agents/requirements-writer.md
git commit -m "feat: implement the requirements-writer agent

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Planner mode and template comment

**Files:**
- Modify: `agents/planner.md` (additive)
- Modify: `templates/requirements-template.md:8`

**Interfaces:**
- Produces: the mode name `Approved-requirements mode`, used by Task 3's Stage 1.

- [ ] **Step 1: Add the skill line to `agents/planner.md`**

old:
```
- Revision mode: no new skill loads — you already planned; just address findings.
```

new:
```
- Approved-requirements mode: superpowers:writing-plans + gstack /spec only — the client
  already approved the requirements, so no /office-hours or brainstorming.
- Revision mode: no new skill loads — you already planned; just address findings.
```

- [ ] **Step 2: Add the mode to `agents/planner.md`**

old:
```
**Escalated-bug mode:** You receive the `investigator`'s findings and mini-plan
```

new:
```
**Approved-requirements mode:** Used by `/pipeline-all` when the client has already approved
a requirements document. The framing is done — skip gstack /office-hours and
superpowers:brainstorming.
1. Read the contract (and the requirements originals only when the orchestrator passed
   them), then the relevant code — targeted, per the context budget.
2. Do not re-open scope. If something in the requirements looks contradictory or
   unbuildable, record it under `## Open decisions` in the overview instead of changing what
   the client approved.
3. Return NEEDS_CONTEXT only for implementation facts the requirements and the code cannot
   answer — never for business questions the client already settled.
4. Invoke superpowers:writing-plans, applying gstack /spec's rigor, as in Feature mode step 3.

**Escalated-bug mode:** You receive the `investigator`'s findings and mini-plan
```

- [ ] **Step 3: Add the split ID rule to `templates/requirements-template.md`**

old:
```
- IDs (BR-, VAL-, AC-, Q-) start at 001 and are never reused.
```

new:
```
- IDs (BR-, VAL-, AC-, Q-) start at 001 and are never reused.
- Split features: `00-shared.requirements.md` uses IDs 001–099; part N uses N01–N99 (part 1:
  BR-101, part 2: BR-201). A part's sections owned by the shared file say
  "See `00-shared.requirements.md` §N." plus anything specific to the part.
```

- [ ] **Step 4: Verify**

```bash
git diff --numstat agents/planner.md
grep -c 'Approved-requirements mode' agents/planner.md
grep -c '^## [0-9]\+\. ' templates/requirements-template.md
awk '/^## [0-9]+\. /{h=$0; getline; if ($0 !~ /^_(Required|Optional)/) {print "MISSING MARKER: " h; bad=1}} END{exit bad}' templates/requirements-template.md && echo MARKERS_OK
```

Expected: planner numstat shows `14	0` (14 added, 0 deleted); `2`; `23`; `MARKERS_OK`.

- [ ] **Step 5: Commit**

```bash
git add agents/planner.md templates/requirements-template.md
git commit -m "feat: add planner Approved-requirements mode and split ID rule

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Wire `/pipeline-all`

**Files:**
- Modify: `commands/pipeline-all.md` (Stage R, Stage Q, Stage 0.8, Stage 1, Stage 6, ledger, hard rules)

**Interfaces:**
- Consumes: Task 1's inputs and statuses; Task 2's mode name.
- Produces: ledger keys `REQUIREMENTS_SHARED`, `REMAINING_PARTS`, `split_rounds`.

Read `commands/pipeline-all.md` in chunks first (lines ~85–260 and ~540–600).

- [ ] **Step 1: Stage R step 1 — existing part paths and split folders**

old:
```
1. **Slug and path.** Derive `<slug>` from the request (kebab-case, at most 5 words). The
   requirements path is `docs/features/<slug>.requirements.md`. Check for it in one Bash call
   that also removes any stale contract (Stage 0.8 re-creates it; an old contract would make
   the context-budget hook redirect agents away from the new requirements):
   `ls docs/features/<slug>.requirements.md 2>/dev/null; rm -f docs/features/<slug>.requirements.contract.md`.
   If the file already exists, ask once: **Use the existing file** (show only its path — you
   do not read the file — and ask the step-4 question; the summary, counts and Open Questions are not available) |
   **Regenerate** (overwrite it).
```

new:
```
1. **Slug and path.** Stale contracts are removed in the same Bash call as each check below
   (Stage 0.8 re-creates them; an old contract would make the context-budget hook redirect
   agents away from the new requirements).
   - **The request is a path to an existing `*.requirements.md`** (for example the next part
     of a split feature): do not dispatch the writer. One Bash call:
     `ls <path> <dir>/00-shared.requirements.md 2>/dev/null; rm -f <dir>/<stem>.contract.md`.
     Record `<path>`, and `REQUIREMENTS_SHARED: <dir>/00-shared.requirements.md` when it
     exists. Go to the step-4 question showing only the path — you do not read the file; the
     summary, counts and Open Questions are not available.
   - **Otherwise** derive `<slug>` from the request (kebab-case, at most 5 words). The
     single-file path is `docs/features/<slug>.requirements.md`; the split folder is
     `docs/features/<slug>/`. One Bash call:
     `ls -d docs/features/<slug>.requirements.md docs/features/<slug>/*.requirements.md 2>/dev/null; rm -f docs/features/<slug>.requirements.contract.md docs/features/<slug>/*.contract.md`.
     If anything exists, ask once: **Use the existing file** (for a split folder, ask which
     part; show only its path — you do not read the file — record the shared file as above,
     and ask the step-4 question; the summary, counts and Open Questions are not available) |
     **Regenerate** (delete the listed files in one Bash call, then dispatch the writer).
```

- [ ] **Step 2: Stage R step 2 — pass the split folder**

old:
```
   - `output`: the requirements path
   - `repo_root`
```

new:
```
   - `output`: the single-file path
   - `output_dir`: the split folder
   - `repo_root`
```

- [ ] **Step 3: Stage R — split proposal handling and multi-file confirmation**

old:
```
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
```

new:
```
   unknown as Open Questions and Assumptions.

   **`SPLIT_PROPOSAL`** → the agent judged the feature too big for one run and wrote nothing
   yet. In ONE turn show its `parts`, `order` and `shared` lines, then ask with
   `AskUserQuestion`: **Approve split** | **Keep as one file** | **Change the split**.
   - **Approve split** → re-dispatch in `draft` mode with `approved_split` = the parts list
     verbatim, plus the same `request`, `input_files`, `template`, `output`, `output_dir`,
     `repo_root` and the cumulative `answers`.
   - **Keep as one file** → re-dispatch the same way with `approved_split: one-file`.
   - **Change the split** → re-dispatch the same way with the client's words as
     `split_feedback`. Count these in `split_rounds`; after 2, offer only **Approve split** |
     **Keep as one file**.
4. **`DONE` → client confirmation.** In ONE turn show each returned path with its counts
   (BR / VAL / AC / Open Q), the agent's summary and its list of questions still Open. Then
   ask ONE `AskUserQuestion` covering all files: **Approve requirements** | **Request changes**.
   - **Approve requirements** → mark every file approved in one Bash call, without reading
     them: `sed -i 's/^| Status | Draft |/| Status | Approved |/' <path> [<path> …]`.
   - **Request changes** → take the client's feedback verbatim and re-dispatch in
     `revision` mode with `feedback`, `files` (every requirements path in play, including
     `REQUIREMENTS_SHARED`), `question_round: 0`, the cumulative `answers`, plus the same
     `request`, `input_files`, `template`, `output`, `output_dir` and `repo_root`. Return to
     this step.
```

- [ ] **Step 4: Stage R step 5 — `BLOCKED`**

old:
```
5. **`PLACEHOLDER`** → say `Requirements agent not yet implemented — continuing with the raw
   request.` on the same turn as the Stage Q dispatch, record `REQUIREMENTS: none`, and go
   to Stage Q. No gate.
```

new:
```
5. **`PLACEHOLDER`** → say `Requirements agent not yet implemented — continuing with the raw
   request.` on the same turn as the Stage Q dispatch, record `REQUIREMENTS: none`, and go
   to Stage Q. No gate. **`BLOCKED`** → the same, but say
   `Requirements agent blocked: <reason> — continuing with the raw request.`
```

- [ ] **Step 5: Stage R step 6 — split ledger**

old:
```
6. Ledger: `REQUIREMENTS: <path> (approved, revisions: N)`,
   `REQUIREMENTS: <path> (existing, unrevised)` or `REQUIREMENTS: none`.
```

new:
```
6. Ledger: `REQUIREMENTS: <path> (approved, revisions: N)`,
   `REQUIREMENTS: <path> (existing, unrevised)` or `REQUIREMENTS: none`. After a split,
   `<path>` is part 1 and the entry reads `(approved, part 1 of N, revisions: N)`; also
   record `REQUIREMENTS_SHARED: <shared path>` and `REMAINING_PARTS: <part 2…N paths>`.
   **One part per run** — the rest of this run builds part 1 only.
```

- [ ] **Step 6: Stage Q — pass the shared file**

old:
```
Dispatch `qa-placeholder` with `requirements` (the approved or existing path, or `none`), `request`
(verbatim) and `repo_root`.
```

new:
```
Dispatch `qa-placeholder` with `requirements` (the approved or existing path, or `none`),
`shared` (the `REQUIREMENTS_SHARED` path, when set), `request` (verbatim) and `repo_root`.
```

- [ ] **Step 7: Stage 0.8 — source, shared file and contract directory**

old:
```
`<source>` is the requirements file, `docs/features/<slug>.requirements.md`, when the ledger
says `REQUIREMENTS: <path> (approved…)` or `(existing, unrevised)` — treat both the same. If
the ledger says `REQUIREMENTS: none`, `<source>` is any spec the client referenced instead; if
there is none, record `CONTRACT: none` in the ledger and skip to Stage 1.
```

new:
```
`<source>` is the requirements file recorded in the ledger (`docs/features/<slug>.requirements.md`,
or the current part's file after a split) when the ledger says `REQUIREMENTS: <path> (approved…)`
or `(existing, unrevised)` — treat both the same. `<shared>` is the `REQUIREMENTS_SHARED` file
when set; it travels with `<source>` everywhere below. If the ledger says
`REQUIREMENTS: none`, `<source>` is any spec the client referenced instead; if there is none,
record `CONTRACT: none` in the ledger and skip to Stage 1. `<contract dir>` is the directory of
`<source>` for a requirements file, otherwise `docs/features`.
```

- [ ] **Step 8: Stage 0.8 steps 1–2 — copy with the shared file**

old:
````
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
````

new:
````
1. One Bash call measures the source (with `<shared>` when set) and, when it is small,
   copies it to the contract path. Estimate tokens as `chars / 3` (12,000 chars ≈ 4,000
   tokens). Without `<shared>`:

   ```bash
   wc -c -l <source>
   if [ "$(wc -c < <source>)" -lt 12000 ]; then
     mkdir -p <contract dir> && cp <source> <contract dir>/<source stem>.contract.md && echo "CONTRACT: copied"
   fi
   ```

   With `<shared>`, the copy is the shared text followed by the part. Use `cp` then
   `tail -n +1 … >>`, never `cat`: the hook blocks `cat` on long Markdown even into a file,
   and this writes to the file only — nothing enters your context:

   ```bash
   wc -c -l <shared> <source>
   if [ "$(( $(wc -c < <shared>) + $(wc -c < <source>) ))" -lt 12000 ]; then
     cp <shared> <contract dir>/<source stem>.contract.md && tail -n +1 <source> >> <contract dir>/<source stem>.contract.md && echo "CONTRACT: copied"
   fi
   ```

2. Under 4,000 tokens → that call made the copy. Record `CONTRACT: copied`; `<contract>` =
   `<contract dir>/<source stem>.contract.md`. Skip to Stage 1. Wherever a stage passes the
````

- [ ] **Step 9: Stage 0.8 step 3 — distil beside the source, with the shared file**

old:
```
3. Otherwise dispatch **one** `distiller` with `<source>` and the output path
   `<contract>` = `docs/features/<source stem>.contract.md`, and record `CONTRACT: distilled`.
   For the requirements file that is `docs/features/<slug>.requirements.contract.md`. The name
   must be `<source stem>.contract.md` (copied or distilled), because the context-budget hook
   links an original to its contract by filename stem. When `<source>` is the requirements
   file, add this to the dispatch:
```

new:
```
3. Otherwise dispatch **one** `distiller` with `<source>` and the output path
   `<contract>` = `<contract dir>/<source stem>.contract.md`, and record `CONTRACT: distilled`.
   For a single requirements file that is `docs/features/<slug>.requirements.contract.md`; for
   a part it sits beside the part. The name must be `<source stem>.contract.md` (copied or
   distilled), because the context-budget hook links an original to its contract by filename
   stem. When `<shared>` is set, tell the distiller to read it as well and fold its roles,
   shared rules, security and non-functional rows into the same contract. When `<source>` is
   a requirements file, add this to the dispatch:
```

- [ ] **Step 10: Stage 1 — Approved-requirements mode and the shared original**

old:
```
- When `CONTRACT: distilled`, also pass `<source>`, the approved requirements file, labelled
  explicitly as the original the planner may read (Feature mode). When `CONTRACT: copied`,
  the contract is the same text — pass it alone. State that the approved requirements are
  the source of truth. The planner gets no raw client files.
```

new:
```
- Dispatch the planner in **Approved-requirements mode**: the client already approved the
  requirements, so it skips gstack /office-hours and superpowers:brainstorming.
- When `CONTRACT: distilled`, also pass `<source>`, the approved requirements file — and
  `<shared>` when set — labelled explicitly as the originals the planner may read. When
  `CONTRACT: copied`, the contract already holds the same text — pass it alone. State that
  the approved requirements are the source of truth. The planner gets no raw client files.
```

Then, old:
```
The planner works through
gstack /office-hours (framing) and gstack /spec (precision) alongside
superpowers:brainstorming and superpowers:writing-plans.
```

new:
```
Otherwise (`REQUIREMENTS: none`) the planner works through
gstack /office-hours (framing) and gstack /spec (precision) alongside
superpowers:brainstorming and superpowers:writing-plans.
```

- [ ] **Step 11: Stage 6 — next part**

old:
```
Report in <10 lines: what shipped, PR link, test summary, anything deferred, final ledger
line. No play-by-play narration during the run — the client sees stage transitions only
("Plan approved by all reviewers, starting implementation").
```

new:
```
Report in <10 lines: what shipped, PR link, test summary, anything deferred, final ledger
line. If `REMAINING_PARTS` is not empty, end with the next part and its command:
`/sdlc-pipeline:pipeline-all <next part path>`. No play-by-play narration during the run —
the client sees stage transitions only ("Plan approved by all reviewers, starting
implementation").
```

- [ ] **Step 12: Ledger and hard rules**

old:
```
  requirements: <path> (approved, revisions: N) | <path> (existing, unrevised) | none
```

new:
```
  requirements: <path> (approved[, part K of N], revisions: N) | <path> (existing, unrevised) | none
  requirements_shared: <path> | none   remaining_parts: <paths> | none   split_rounds: N / 2
```

Then, old:
```
- Never skip the Stage R client confirmation when `requirements-writer` returned `DONE`.
```

new:
```
- Never skip the Stage R client confirmation when `requirements-writer` returned `DONE`.
- One requirements part per run. After a split, build part 1 and give the client the command
  for the next part.
```

- [ ] **Step 13: Verify**

```bash
grep -n '^## ' commands/pipeline-all.md
grep -c 'SPLIT_PROPOSAL\|BLOCKED`\|approved_split\|split_feedback\|output_dir' commands/pipeline-all.md
grep -c 'REQUIREMENTS_SHARED\|REMAINING_PARTS' commands/pipeline-all.md
grep -c 'Approved-requirements mode' commands/pipeline-all.md
grep -cE 'Stage 1-B|investigator|nano|TYPE: bug|classif|00-overview\.md.*requirements' commands/pipeline-all.md
git diff --exit-code commands/pipeline.md commands/pipeline-parallel.md hooks scripts agents/distiller.md agents/qa-placeholder.md .claude-plugin .cursor-plugin && echo PROTECTED_UNCHANGED
claude plugin validate . 2>&1 | grep -c Found
claude plugin validate . 2>&1 | tail -1
```

Expected: the same 23 headings as before (unchanged order); `≥6`; `≥6`; `1`; `0`; `PROTECTED_UNCHANGED`; `13`; `✔ Validation passed with warnings`.

Write `git diff -U3 HEAD -- commands/pipeline-all.md > "$TEMP/t3.diff"` and read it in chunks: every hunk maps to Steps 1–12.

- [ ] **Step 14: Commit**

```bash
git add commands/pipeline-all.md
git commit -m "feat: wire requirements splitting and Approved-requirements mode into /pipeline-all

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: README and spec pointer

**Files:**
- Modify: `README.md` (Example 4, last paragraph)
- Modify: `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` (§12 item 2)

- [ ] **Step 1: README Example 4**

old:
```
In this release the requirements and QA agents are placeholders: each reports "not yet implemented" and the run continues with your original request.
```

new:
```
The requirements agent asks you only about major gaps (purpose, users, scope, main flow, security, other systems it connects to), then writes `docs/features/<slug>.requirements.md` from the plugin's template for you to approve or change. A feature that is genuinely too big for one run is split — only after you approve the split — into a shared file plus a few parts in `docs/features/<slug>/`; each run builds one part and ends with the command for the next. The QA step is still a placeholder: it reports "not yet implemented" and the run continues.
```

- [ ] **Step 2: Spec pointer**

old:
```
2. The full `requirements-writer` instructions.
```

new:
```
2. The full `requirements-writer` instructions — designed in
   `docs/superpowers/specs/2026-10-27-requirements-writer-design.md`.
```

- [ ] **Step 3: Verify and commit**

```bash
grep -c 'split' README.md
grep -c '2026-10-27-requirements-writer-design' docs/superpowers/specs/2026-10-26-pipeline-all-design.md
git add README.md docs/superpowers/specs/2026-10-26-pipeline-all-design.md
git commit -m "docs: describe the requirements agent and splitting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: `≥1`, `1`, then a commit touching 2 files.

---

### Task 5: Reinstall and manual run (user)

- [ ] **Step 1: Refresh the installed plugin**

```bash
claude plugin update sdlc-pipeline@sdlc-pipeline-dev
```

Then open a **new** Claude Code session in a scratch git repo.

- [ ] **Step 2: Small idea** — `/sdlc-pipeline:pipeline-all Let users export their saved reports as CSV`
  Expected: at most one batch of questions (only if a major gap), one file `docs/features/<slug>.requirements.md`, the approve / change question, then `| Status | Approved |` in the file. Stop at the Stage 2.5 gate.

- [ ] **Step 3: Large idea** — copy `requirement (1).md` into the scratch repo and run `/sdlc-pipeline:pipeline-all Build the system described in requirement (1).md`
  Expected: a split proposal of few parts (≈4, not 9) with a reason per part; on **Approve split**, `docs/features/<slug>/00-shared.requirements.md` plus the part files; one approval for all; the run continues with part 1 only. Stop at the Stage 2.5 gate.

- [ ] **Step 4: Next part** — `/sdlc-pipeline:pipeline-all docs/features/<slug>/02-<part>.requirements.md`
  Expected: no writer dispatch; straight to the approve / change question showing the path.

- [ ] **Step 5: Report** what matched and, for anything that did not, the stage and what you saw.

---

## Spec coverage

| Spec section | Task |
|---|---|
| §2 D1–D7, §3 agent flow, inputs, returns | Task 1 |
| §4 splitting rule, §5 layout | Task 1 (rules), Task 2 (template IDs), Task 3 (Stage R) |
| §2 D10, §6 pipeline changes | Task 3 |
| §2 D11, §7 planner | Task 2 |
| §7 README, old spec | Task 4 |
| §8 hook fit | Task 1 (chunked reads, `00-shared` name), Task 3 Step 8 (`tail` not `cat`) |
| §9 verification | Task 1–4 verify steps, Task 5 |
