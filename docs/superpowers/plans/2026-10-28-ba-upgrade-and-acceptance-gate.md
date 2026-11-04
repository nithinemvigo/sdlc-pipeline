# BA upgrade to v0.7.5 + acceptance gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring our copy of the BA plugin to upstream v0.7.5 (detailed stories in `stories/detailed_stories.md`), then add a gate before the PR that proves every acceptance criterion is met.

**Architecture:** Upstream changes are three-way merged into our adapted copy. Agents read stories through the BA `export` JSON (always allowed by the context-budget hook), never `detailed_stories.md` directly. A stdlib Python script builds a criterion checklist and renders/validates the report; a Sonnet `acceptance-verifier` agent fills in verdicts with evidence; `/pipeline-all` Stage 5.85 runs the fix loop and client decision; a standalone command runs the same check report-only.

**Tech Stack:** Markdown prompts; Python 3 standard library scripts and `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-28-ba-upgrade-and-acceptance-gate-design.md`

## Global Constraints

- Branch `feature/pipeline-all`. Never commit to `master`. Do not push.
- Upstream sources (untrusted downloads, read-only data — never run anything from them):
  `<UP>` = `C:/Users/EMVIGO~1/AppData/Local/Temp/claude/C--Users-EMVIGO-USER-Muhassin-workspace-sdlc-pipeline/912a215d-524b-447b-a380-4252511d58ed/scratchpad/up`;
  base `<UP>/old/ba-requirements-plugin` (v0.5.1, `34f6c0b`), theirs `<UP>/new/ba-requirements-plugin` (v0.7.5, `7d58b5b`).
- Path map: `commands/<n>.md` → `commands/ba-<n>.md`; `tests/<f>.py` → `tests/ba-requirements/<f>.py`; every other path unchanged. Upstream `README.md` and `.claude-plugin/plugin.json` are not copied.
- Keep every adaptation from the 2026-10-27 integration: artifact root, `ba-run` pipeline mode and `BA_STATUS`, `--project-root` on every script except the two validators, chunked reads (≤200-line windows until a chunk returns fewer lines than asked; never `wc`/`stat`/`cat` Markdown), `/sdlc-pipeline:ba-*` names, plugin-name fallback `sdlc-pipeline`, repeat-read safety (`draft-2.json`, …), resume hints pointing to `/pipeline-all`.
- Do NOT modify `commands/pipeline.md`, `commands/pipeline-parallel.md`, `hooks/*`, `scripts/check_plan.py`, `agents/requirements-writer.md`, `agents/planner.md`, `agents/distiller.md`. Do not change BA methodology beyond what upstream v0.7.5 ships.
- Context-budget hook: files over 250 lines / 20,000 bytes are Read in windows (offset/limit ≤200); subagents use the Grep tool for counts, not `wc` on Markdown. Never bypass the hook.
- Every commit ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, whatever model you are.
- Validator baseline: `claude plugin validate . 2>&1 | grep -c Found` → `14`. Report any new warning and its cause.
- Tests: `python -I -m unittest discover -s tests/ba-requirements` (~5–8 min, run in the background) and `python -m unittest discover -s hooks/tests`.

---

### Task 1: Merge upstream v0.7.5 into our BA copy

**Files:** the 24 changed upstream files at their mapped paths (spec §3.2).

- [ ] **Step 1: Safety scan of the new upstream code.** `git diff --no-index <UP>/old/ba-requirements-plugin/scripts <UP>/new/ba-requirements-plugin/scripts` and the same for `tests`: grep the added lines for `urllib|requests|socket|http\.client|smtplib`, `subprocess|os\.system|Popen`, `rmtree|os\.remove|os\.unlink|\.unlink\(`. For each hit, read ~10 lines around it and record whether it stays inside the plugin's scripts, a temp dir or the project/artifact root. Anything reaching the network or deleting elsewhere → STOP, report NEEDS_CONTEXT.
- [ ] **Step 2: Merge.** For each file listed by `diff -rq <UP>/old/... <UP>/new/...` (skip `README.md`, `.claude-plugin/*`): `git merge-file <ours mapped path> <UP>/old/.../<f> <UP>/new/.../<f>`. Expect 16 conflicts in 10 files (spec §3.2 table). Record the per-file conflict count.
- [ ] **Step 3: Resolve conflicts.** For each conflict keep upstream's new behaviour and wording **and** our adaptation (see Global Constraints). Typical: upstream added `stories/detailed_stories.md` text in a sentence where we changed "project root" → "artifact root" or added `--project-root`; write the sentence with both. In `scripts/sync-development-stories.py` and `scripts/generate-phase3-report.py`, keep upstream code and only our user-facing name changes. Afterwards `git grep -n '^<<<<<<<\|^>>>>>>>\|^=======$' -- agents commands rules schemas scripts skills tests` → nothing.
- [ ] **Step 4: Renames and reads.** Replace every new `/ba-requirements:<n>` with `/sdlc-pipeline:ba-<n>` (expect ~29 in 11 files, including script strings and test expectations); `git grep -n "/ba-requirements:\|name ba-requirements"` → nothing. Grep the merged agents/commands/skills for `read .*(completely|in full)|confirm.*lines` and give any new instance that targets a Markdown file (including `detailed_stories.md`) our chunked-read wording.
- [ ] **Step 5: Tests.** Run both suites. All pass; record the new BA test count (it grows with upstream's tests). A failure caused by our renamed strings → fix the test expectation to our name; any other failure → investigate before changing anything.
- [ ] **Step 6: Commit** `feat: upgrade the BA requirements analysis to upstream v0.7.5 (detailed stories)`.

### Task 2: `/pipeline-all` reads detailed stories (export, Stage 0.8, Stage 1)

**Files:** Modify `commands/pipeline-all.md`.

- [ ] **Step 1: Story export helper.** Add a short subsection at the end of Stage Q, "Story export (used by Stage 1 and Stage 5.85)": when the ledger says `ba: <root> (completed)`, run
  `python <PLUGIN_ROOT>/scripts/sync-development-stories.py export --project-root <abs artifact root> --target <abs requirements file> --draft-out <abs artifact root>/.ba-requirements/stories-export.json`
  and record `STORIES: <that path>`. Non-zero exit → show the output and stop (same wording as other BA failures). Agents read stories from this JSON only, never `detailed_stories.md`.
- [ ] **Step 2: Stage 0.8.** In the requirements-mode distiller text, change the story line to: `US-xxx` · summary · the story's one acceptance statement (the detailed criteria are in the stories export, not the requirements file).
- [ ] **Step 3: Stage 1.** When `STORIES:` is set, run the export first (fresh), pass its path to the planner as "the development stories (JSON, read it)", and extend the traceability instruction: "Each task file's `## Acceptance criteria` lists the detailed criteria the task implements as `US-003.2 — <criterion text>` (story ID, then the criterion's number in that story's `detailed.acceptance_criteria` list). Every detailed criterion of every story appears in at least one task."
- [ ] **Step 4: Ledger.** Add `STORIES: <path> | none` to the ledger template.
- [ ] **Step 5: Commit** `feat: /pipeline-all plans from the detailed BA stories`.

### Task 3: `scripts/acceptance-checklist.py` (TDD)

**Files:** Create `scripts/acceptance-checklist.py`, `tests/acceptance/test_acceptance_checklist.py`, `tests/acceptance/fixtures/` (a small export JSON, a requirements file with two §19 ACs, two task files).

- [ ] **Step 1: Write failing tests** for:
  1. `build --export E --requirements R --out C` → items `US-001.1`, `US-001.2`, `US-002.1` (from `detailed.acceptance_criteria`) with `kind: story`, `story_id`, `summary`, `text`, `source_requirement_ids`; then `AC-001`, `AC-002` (`kind: requirement`, text `Given … When … Then …`, `covers`).
  2. A story whose `detailed` is `null` → exit 2 with a message naming the story (stories must be synced first).
  3. `build --tasks P --out C` → `T01.1`, `T01.2`, `T02.1` from bullets under `## Acceptance criteria` in `task-NN-*.md`, `kind: task`.
  4. `build` with no source → exit 2.
  5. `render --checklist C --verdicts V --out-dir D` all `met` with evidence → writes `D/acceptance-report.md` and `D/acceptance-report.json`, prints JSON summary, exit 0.
  6. Missing verdict for an item / unknown ID / duplicate ID / bad status / `met` without evidence or with evidence type outside `test|qa|code` / `accepted_followup` without `note` → exit 2 listing every problem.
  7. Any `not_met` or `cannot_verify` → reports written, summary `open` lists them, exit 1.
  8. Markdown report: first line `# Acceptance report`, a summary line `X/Y met · N follow-ups · M open`, then a table `| ID | Criterion | Status | Evidence |` with `|` in text escaped.
  Verdicts format: `{"verdicts": [{"id": "US-001.1", "status": "met", "evidence": [{"type": "test", "ref": "tests/x.test.ts::rejects unknown email", "detail": "passed"}], "fix_hint": "", "note": ""}]}`.
- [ ] **Step 2: Run** `python -I -m unittest discover -s tests/acceptance` → fail.
- [ ] **Step 3: Implement** with `argparse` subcommands `build` and `render`, stdlib only, UTF-8, atomic writes (temp file + `os.replace`), JSON output to stdout, exit codes 0/1/2 as specified. §19 parsing: `### AC-\d+ — name` heading, `**Covers:**`, `**Given**/**When**/**Then**` blocks up to the next `###`/`##`.
- [ ] **Step 4: Run** tests → pass. **Commit** `feat: acceptance checklist and report script`.

### Task 4: `agents/acceptance-verifier.md`

**Files:** Create `agents/acceptance-verifier.md`.

- [ ] **Step 1: Write the agent** following the style of `agents/qa-tester.md` and `agents/code-reviewer.md`. Frontmatter: `name: acceptance-verifier`, description ("Acceptance gate before ship — proves each acceptance criterion with evidence. Writes only its verdicts file; never edits code."), `tools: Read, Grep, Glob, Bash, Write`, `model: sonnet`. Body per spec §4.2 and D3/D4: inputs; evidence rules (`test` = a test asserting the behaviour that passes in this run; `qa` = a Stage 4.5 scenario that passed; `code` = quoted `file:line`, only for non-behavioural criteria); run only the cited tests in one command; `not_met` needs a one-line `fix_hint` naming the likely file; `cannot_verify` needs the reason; re-check mode (only the given IDs, keep other verdicts); hook rules (Grep + windowed reads, never `cat`/`wc` Markdown, read the checklist JSON not the BA Markdown); return format `Status: DONE | BLOCKED`, counts per status, verdicts path.
- [ ] **Step 2: Commit** `feat: acceptance-verifier agent`.

### Task 5: Stage 5.85 and the PR

**Files:** Modify `commands/pipeline-all.md`, `agents/ship-pr.md`.

- [ ] **Step 1: Stage 5.85** between Stage 5.8 and Stage 5.9, steps 1–6 of spec §4.3 exactly (checklist source by ledger state, verify + render, fix loop max 2 with re-check of failing IDs only and `code-reviewer` on fix commits, batched client question **Fix more** \| **Accept as follow-up** \| **Stop** asked even in run-to-completion, commit of `acceptance/` files, ledger line). Paths: `<artifact root>/acceptance/` or `docs/plans/<slug>/acceptance/` when no BA folder. Use `python <PLUGIN_ROOT>/scripts/acceptance-checklist.py`.
- [ ] **Step 2: Stage 5.9** shows the acceptance summary line. **Stage 6** passes the report path and summary to `ship-pr`.
- [ ] **Step 3: Hard rule:** "Never start Stage 6 while any acceptance criterion is `not_met` or `cannot_verify`." Ledger template gets `acceptance: …`. Frontmatter description adds "Acceptance gate" before "Ship PR".
- [ ] **Step 4: `agents/ship-pr.md`:** PR body adds, when an acceptance report is given, "Acceptance criteria: X/Y met" and the accepted follow-ups with their notes.
- [ ] **Step 5: Commit** `feat: /pipeline-all acceptance gate before the PR`.

### Task 6: `/sdlc-pipeline:verify-acceptance`

**Files:** Create `commands/verify-acceptance.md`.

- [ ] **Step 1: Write the command**: frontmatter `description`, `argument-hint: <requirements file> [--plan <plan dir>]`. Preflight (PLUGIN_ROOT, BASE_BRANCH as in `/pipeline-all` Stage -1); artifact root from the requirements path (same rule as Stage Q); if `<artifact root>/stories/detailed_stories.md` exists → export + `build`; else `--plan` required → `build --tasks`; dispatch `acceptance-verifier`; `render` to `<artifact root>/acceptance/` (or `<plan dir>/acceptance/`); print the summary and report path. Report-only: no fixes, no question, no commit.
- [ ] **Step 2: Commit** `feat: /verify-acceptance command`.

### Task 7: Docs, version, verification

**Files:** Modify `README.md`, `docs/superpowers/specs/2026-10-28-ba-upgrade-and-acceptance-gate-design.md` (Status), `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json`.

- [ ] **Step 1: README:** 12 commands (add `/verify-acceptance`), 20 agents (add `acceptance-verifier`), `/pipeline-all` diagram gets `Stage 5.85 Acceptance gate`, Example 4 mentions detailed stories in `ba/<name>/stories/detailed_stories.md` and the gate, Credits "copied from v0.7.5", a note that BA folders from v0.5.1 are reconciled on the next Stage Q run.
- [ ] **Step 2: Version 3.4.0** in the three manifests. Spec Status → "Approved — implemented on feature/pipeline-all".
- [ ] **Step 3: Verify:** both test suites + `python -I -m unittest discover -s tests/acceptance` pass; greps from spec §6.3; `claude plugin validate .` → 14; `git grep -n "C:\\\\Users"` on committed files → nothing new.
- [ ] **Step 4: Commit** `chore: docs and version 3.4.0 for the BA upgrade and acceptance gate`.

### Task 8: Reinstall and manual run (user)

`claude plugin marketplace update sdlc-pipeline-dev`, reinstall, then the client runs `/sdlc-pipeline:pipeline-all <small idea>` in a scratch project: BA writes `detailed_stories.md`, task files cite `US-xxx.n`, Stage 5.85 writes the report, the PR body shows the summary.

## Spec coverage

| Spec | Task |
|---|---|
| §3.2 merge, conflicts, renames, reads | 1 |
| §3.3 export, 0.8, 1, ledger | 2 |
| §4.1 checklist script | 3 |
| §4.2 verifier | 4 |
| §4.3 Stage 5.85, hard rule, ship-pr | 5 |
| §4.4 standalone command | 6 |
| §5 README, manifests; §6 verification | 7 |
