# BA plugin upgrade to v0.7.5 + acceptance gate before the PR — Design

- **Date:** 2026-10-28
- **Status:** Approved — implemented on feature/pipeline-all
- **Branch:** `feature/pipeline-all` (plugin 3.3.0 → 3.4.0)
- **Source:** `akhilvn-crypto/BA-Pipeline`, folder `ba-requirements-plugin`, commit `7d58b5b`
  (v0.7.5). Our copy is from `34f6c0b` (v0.5.1).

## 1. Goal

1. **Upgrade** our copy of the QA/BA team's requirements-analysis plugin from v0.5.1 to v0.7.5,
   keeping every adaptation we made in the integration (2026-10-27 spec).
2. **Add an acceptance gate** at the end of `/pipeline-all`, before the PR: every acceptance
   criterion of every BA story, read from `<BA folder>/stories/detailed_stories.md`, must be
   proven met (or explicitly accepted by the client as a follow-up) before Stage 6 opens the PR.
   The same check is available as a standalone command.

## 2. Decisions (client, 2026-10-28)

| # | Decision |
|---|---|
| D1 | Upgrade the BA copy to v0.7.5 first, then build the gate on `detailed_stories.md`. |
| D2 | Both a stage (`/pipeline-all` Stage 5.85) and a standalone command (`/sdlc-pipeline:verify-acceptance`). |
| D3 | A criterion is **Met** only with evidence: a test that checks it and passes in this run, a passing Stage 4.5 QA scenario, or — only for non-behavioural criteria (wording, a label, a config value) — a quoted `file:line`. "The code looks right" is not evidence. |
| D4 | The verifier runs only the tests it cites as evidence, once — not the whole suite. |
| D5 | Not met → fresh `implementer` fixes → re-check, max 2 rounds. Then the client decides per remaining criterion: **Fix more** \| **Accept as follow-up** (listed in the PR) \| **Stop**. |
| D6 | Criteria checked: the numbered **Acceptance Criteria** of each detailed story, plus the requirements file's §19 `AC-xxx`. Scenarios, NFRs and other detailed fields are not checked by this gate. |
| D7 | No BA folder (BA skipped, or no requirements file) → fall back to the `## Acceptance criteria` of the plan's task files. |
| D8 | Report in the BA folder (`acceptance/acceptance-report.md` + `.json`), committed on the branch; summary and accepted follow-ups in the PR body. BA files and story formats are not changed. |
| D9 | The verifier agent runs on Sonnet. |

## 3. Part A — BA upgrade v0.5.1 → v0.7.5

### 3.1 What changes upstream

v0.7.x saves every story **twice under one Story ID**:

- **Detailed story** in `<artifact root>/stories/detailed_stories.md` (authoritative; the HTML
  report is built from it): Description, Preconditions, Functional Behaviour, Business Rules,
  **Acceptance Criteria (numbered, plain sentences, no upper limit)**, Alternate and Error
  Scenarios, Non-Functional Requirements, Dependencies.
- **Ultra-lean story** in the requirements file's `# Development Stories` section: Story ID,
  summary, **one** high-level acceptance statement.

Also: refined gap-triage choices, story/AC writing rules, NFRs kept out of the supplied
stories, a richer `export` (`detailed` object per story), a stricter
`validate-development-stories.py` (every lean story has a matching detailed story), and legacy
handling — a project written by an earlier version is reconciled (detailed stories written,
lean entries rewritten after the user agrees, old file backed up).

### 3.2 How we upgrade (three-way merge)

Base = upstream `34f6c0b`, theirs = upstream `7d58b5b`, ours = our files, with the path map
from the integration spec §3 (`commands/<n>.md` → `commands/ba-<n>.md`, `tests/*` →
`tests/ba-requirements/*`, everything else same path). `git merge-file` per changed file
(24 files; upstream `README.md` and `plugin.json` are not copied). A trial merge gave
**16 conflicts in 10 files**:

| File | Conflicts |
|---|---|
| `commands/ba-generate-stories.md` | 4 |
| `commands/ba-enrich-stories.md`, `scripts/sync-development-stories.py` | 2 each |
| `commands/ba-generate-report.md`, `ba-run.md`, `ba-sync-stories.md`, `rules/story-management-rules.md`, `scripts/generate-phase3-report.py`, `skills/story-enrichment/SKILL.md`, `skills/story-generation/SKILL.md` | 1 each |

Each conflict keeps upstream's new behaviour **and** our adaptation (artifact root, pipeline
mode, `--project-root`, chunked reads, `/sdlc-pipeline:ba-*` names). After the merge:

- rename the 29 new `/ba-requirements:<x>` mentions (11 files) to `/sdlc-pipeline:ba-<x>`;
- any new "read completely / in full" wording for a Markdown file (including
  `detailed_stories.md`, which can exceed 250 lines) gets our chunked-read rule;
- README Credits: "copied from v0.7.5".

### 3.3 Effects on `/pipeline-all`

| Stage | Change |
|---|---|
| Q | No flow change. `detailed_stories.md` is under the artifact root, so the Stage 3 commit already includes it; `.gitignore` already excludes `stories/backups/` (where the detailed file's backups go). |
| Story export (new helper, used by Stage 1 and Stage 5.85) | `python <PLUGIN_ROOT>/scripts/sync-development-stories.py export --project-root <abs artifact root> --target <abs requirements file> --draft-out <abs artifact root>/.ba-requirements/stories-export.json`. JSON is always allowed by the context-budget hook, so agents read the stories from this file, never `detailed_stories.md` itself. `.ba-requirements/` is already git-ignored. |
| 0.8 | Distiller story line becomes `US-xxx` · summary · the one acceptance statement (that is all the requirements file now holds). Size check unchanged. |
| 1 | Planner also gets the export path. Each task file's `## Acceptance criteria` lists the detailed criteria it implements by ID and text (`US-003.2 — <text>`); every detailed criterion appears in at least one task. |
| Existing v0.5.1 BA folders | Upstream's legacy path handles them when Stage Q resumes; noted in the README, no extra code. |

## 4. Part B — Acceptance gate

### 4.1 Criterion IDs and the checklist

A new script `scripts/acceptance-checklist.py` (Python 3, stdlib only, tested):

- `build` → `<artifact root>/acceptance/checklist.json`, one item per criterion:
  - story criteria from the export: ID `US-003.2` (story ID + number in the detailed list),
    story summary, criterion text, the story's `source_requirement_ids`;
  - §19 criteria from the requirements file: `### AC-001 — <name>` blocks → ID `AC-001`, text
    `Given … When … Then …`, `Covers`;
  - fallback (`--tasks <plan dir>`): every bullet under `## Acceptance criteria` in
    `task-NN-*.md` → ID `T03.1`.
- `render --checklist <json> --verdicts <json>` → validates that every checklist item has
  exactly one verdict, the status is `met | not_met | cannot_verify | accepted_followup`, a
  `met` verdict has evidence of an allowed type (`test`, `qa`, `code`), and an
  `accepted_followup` has the client's note. Writes `acceptance-report.md` (summary line, then
  a table: ID · criterion · status · evidence) and `acceptance-report.json`. Prints a JSON
  summary (`total`, counts per status, `open` IDs). Exit 0 when nothing is open, 1 when items are
  `not_met`/`cannot_verify`, 2 on invalid input.

### 4.2 Agent `acceptance-verifier` (Sonnet)

Tools: Read, Grep, Glob, Bash, Write (Write only for its verdicts file). Never edits code, never
commits. Inputs: checklist path, verdicts output path, repo root, branch, base branch, plan
directory, the Stage 4 test summary and Stage 4.5 QA findings (when run), and optionally a
list of IDs to re-check.

For each criterion it finds evidence in the branch diff (`git diff <base>...HEAD`, Grep, windowed
reads): the test that asserts the behaviour (name + file:line), a Stage 4.5 scenario, or for
non-behavioural criteria a quoted `file:line`. It then runs **only the cited tests, in one
command** and marks `met` only when they pass. No evidence → `not_met` with a one-line fix hint.
Behaviour it cannot exercise in this environment (external service, real email) →
`cannot_verify` with the reason. Returns `DONE` (counts) or `BLOCKED` (reason).

### 4.3 Stage 5.85 in `/pipeline-all` (after 5.8 Docs, before 5.9 Pre-ship checkpoint)

1. **Checklist.** `ba: completed` → run the export, then `build` from the export + the
   requirements file. `ba: skipped` or `REQUIREMENTS: none` → `build --tasks`. No criteria at
   all → skip with one line and ledger `acceptance: skipped (no criteria)`.
2. **Verify.** Dispatch `acceptance-verifier` → `render`.
3. **Fix loop.** `not_met` items → a fresh `implementer` per affected task (sequential), with the
   failing IDs, criterion text and fix hints → re-verify only those IDs → `render`. Max 2
   rounds. If any fix commit was made, dispatch `code-reviewer` on the fix commits only.
4. **Client decision.** Still `not_met` or `cannot_verify` → one batched question listing them;
   per item **Fix more** (one more round) \| **Accept as follow-up** (status
   `accepted_followup` with the client's note) \| **Stop** (run ends, branch kept, no PR). This
   question is asked even in run-to-completion mode — the PR never ships with an open criterion.
5. **Commit** `acceptance/checklist.json`, `acceptance-report.md` and `.json` to the branch.
   Fallback location when there is no BA folder: `docs/plans/<slug>/acceptance/`.
6. **Ledger:** `acceptance: <met>/<total> met, <n> follow-ups, report <path>`.

Stage 5.9 shows the summary line. Stage 6 passes the report path to `ship-pr`, whose PR body
adds "Acceptance criteria: X/Y met" and the accepted follow-ups. **Hard rule:** never start
Stage 6 while any criterion is `not_met` or `cannot_verify`.

### 4.4 Standalone `/sdlc-pipeline:verify-acceptance <requirements file> [--plan <dir>]`

Steps 1, 2 and 5 of §4.3 on the current branch, **report-only**: no fix loop, no client
question, no commit. Prints the summary and the report path. Without a BA folder it needs
`--plan`.

## 5. Other files

- `agents/ship-pr.md`: PR body includes the acceptance summary and follow-ups when given.
- `README.md`: 12 commands, 20 agents, Stage 5.85 in the `/pipeline-all` diagram, Example 4
  mentions the gate, Credits v0.7.5.
- Manifests → 3.4.0.
- `/pipeline` and `/pipeline-parallel` are unchanged (no BA stories there).

## 6. Verification

1. BA tests: `python -I -m unittest discover -s tests/ba-requirements` — all pass (count grows
   with upstream's new tests). Hook tests pass.
2. New tests `tests/acceptance/` for `acceptance-checklist.py`: build from a sample export +
   requirements, `--tasks` fallback, render validation errors, exit codes.
3. Greps: no `/ba-requirements:` and no `name ba-requirements`; no conflict markers.
4. `claude plugin validate .` → no new warnings beyond the baseline (14).
5. Manual: `/pipeline-all` on a small idea → BA writes `detailed_stories.md` → plan cites
   `US-xxx.n` → Stage 5.85 report → PR body shows the summary.

## 7. Out of scope

Checking NFRs, scenarios or other detailed fields; the gate in `/pipeline` and
`/pipeline-parallel`; automatic upstream sync.
