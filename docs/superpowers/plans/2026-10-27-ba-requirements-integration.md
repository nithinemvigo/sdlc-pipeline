# BA requirements integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Copy the QA/BA team's `ba-requirements` plugin into sdlc-pipeline and run it as `/pipeline-all` Stage Q, replacing `qa-placeholder`.

**Architecture:** Files are copied with commands renamed `ba-*`; all BA commands write under an *artifact root* (per requirements file) instead of the project root; `ba-run` gains a pipeline mode (`--requirements`, `--artifact-root`) that skips the source question and returns `COMPLETED`/`PAUSED`/`BLOCKED`; agents read in chunks to fit our context-budget hook. `/pipeline-all` Stage Q invokes `sdlc-pipeline:ba-run` as a skill.

**Tech Stack:** Markdown prompts; Python 3 standard library scripts and `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-27-ba-requirements-integration-design.md`

## Global Constraints

- Branch `feature/pipeline-all`. No version bump. Never commit to `master`. Do not push.
- Source (untrusted download, read-only): `C:/Users/EMVIGO~1/AppData/Local/Temp/claude/C--Users-EMVIGO-USER-Muhassin-workspace-sdlc-pipeline/912a215d-524b-447b-a380-4252511d58ed/scratchpad/ba-pipeline-src/BA-Pipeline-main/ba-requirements-plugin` (call it `<SRC>`). Never run anything from `<SRC>`; copy first, scan (Task 1), then run only the copied tests.
- Command names: `ba-run`, `ba-start-analysis`, `ba-analyse-gaps`, `ba-triage-gaps`, `ba-generate-stories`, `ba-enrich-stories`, `ba-sync-stories`, `ba-generate-report`. Agent names unchanged: `requirement-analyst`, `gap-analysis-agent`, `story-generation-agent`.
- Artifact root for `/pipeline-all`: `<directory of the requirements file>/ba/<requirements file stem without .requirements>/`.
- Do NOT modify `commands/pipeline.md`, `commands/pipeline-parallel.md`, `hooks/*`, `scripts/check_plan.py`, `agents/requirements-writer.md`, `agents/planner.md`, `agents/distiller.md`, manifests. Do not change BA methodology, rules or schemas beyond what the spec lists.
- Context-budget hook: files over 250 lines / 20,000 bytes are Read in windows (offset/limit ≤200); a subagent's Bash must not `wc`/`cat` Markdown it edited — use the Grep tool for counts. Never bypass the hook.
- Every commit ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, whatever model you are.
- Validator baseline: `claude plugin validate . 2>&1 | grep -c Found` → `14` before this plan; it may only grow by warnings that are clearly caused by the copied files lacking optional metadata — report any new warning and its cause.

---

### Task 1: Copy, rename, scan and test

**Files:** Create `agents/{requirement-analyst,gap-analysis-agent,story-generation-agent}.md`, `commands/ba-*.md` (8), `skills/*/SKILL.md` (9 folders), `rules/*.md` (8), `schemas/*.json` (3), `scripts/*.py` (8 BA scripts), `tests/ba-requirements/*.py` (4), `licenses/ba-requirements-LICENSE`.

- [ ] **Step 1: Copy** with `cp` (one Bash call): `<SRC>/agents/*.md` → `agents/`; `<SRC>/commands/<n>.md` → `commands/ba-<n>.md`; `<SRC>/skills` → `skills`; `<SRC>/rules` → `rules`; `<SRC>/schemas` → `schemas`; `<SRC>/scripts/*.py` → `scripts/`; `<SRC>/tests/*.py` → `tests/ba-requirements/`; `<SRC>/LICENSE` → `licenses/ba-requirements-LICENSE`. Confirm no existing file was overwritten (`git status --short` shows only new paths).
- [ ] **Step 2: Safety scan (before running anything).** Grep the copied `scripts/*.py` and `tests/ba-requirements/*.py` for `urllib|requests|socket|http\.client|ftplib|smtplib`, `subprocess|os\.system|Popen`, `shutil\.rmtree|os\.remove|os\.unlink|Path\(.*\)\.unlink`. For each hit, read ~10 lines around it and record in the report whether it is confined to the plugin's own scripts / a temp dir / the artifact root. If anything reaches the network or deletes outside those places, STOP and report NEEDS_CONTEXT.
- [ ] **Step 3: Rename references.** In every copied file:
  - `${CLAUDE_PLUGIN_ROOT}/commands/<n>.md` → `${CLAUDE_PLUGIN_ROOT}/commands/ba-<n>.md` (all 8 names).
  - `/ba-requirements:<n>` → `/sdlc-pipeline:ba-<n>` (commands, agents, skills, rules, scripts' user-facing strings, tests' expected strings).
  - plugin-directory fallbacks naming `plugin.json` (name `ba-requirements`) → name `sdlc-pipeline`.
  Leave the checkpoint folder name `.ba-requirements/` unchanged.
- [ ] **Step 4: Fix the tests' plugin root.** In each `tests/ba-requirements/*.py`, the line computing `PLUGIN_ROOT` from `__file__` goes one directory up further (tests now live in `tests/ba-requirements/`).
- [ ] **Step 5: Run the tests.**

```bash
python -I -m unittest discover -s tests/ba-requirements
python -m unittest discover -s hooks/tests
```

Expected: both `OK`. A test failing only because it asserts the old command name or path → update that expected string; any other failure → STOP and report.
- [ ] **Step 6: Verify and commit.**

```bash
grep -rn "/ba-requirements:" agents commands skills rules scripts tests | head
grep -rln "name \`ba-requirements\`\|(name ba-requirements)" agents commands skills | head
claude plugin validate . 2>&1 | grep -c Found
```

Expected: no output; no output; `14` (or report new warnings and causes).

```bash
git add agents/requirement-analyst.md agents/gap-analysis-agent.md agents/story-generation-agent.md commands/ba-*.md skills rules schemas scripts tests/ba-requirements licenses
git commit -m "feat: copy the BA requirements plugin (commands renamed ba-*)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Artifact root, pipeline mode, chunked reads

**Files:** Modify `commands/ba-*.md` (8), `agents/requirement-analyst.md`, `agents/gap-analysis-agent.md`, `agents/story-generation-agent.md`, `skills/requirement-source-discovery/SKILL.md`, `tests/ba-requirements/*.py` (expected strings only).

- [ ] **Step 1: Artifact root.** In every `commands/ba-*.md`, replace the line "Project root: the current working directory of this session." (run.md adds a sentence after it) with:

```
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>`.
```

Keep run.md's sentence about never writing into the plugin directory.
- [ ] **Step 2: Pipeline mode in `commands/ba-run.md`.** Add a `## Pipeline mode` section right after the artifact-root line:

```
## Pipeline mode

When the arguments include `--requirements <path>` and `--artifact-root <dir>` (as `/sdlc-pipeline:pipeline-all` passes them), run in pipeline mode:

- Step 0: `COMPLETED` with `artifacts_still_valid` → print "BA analysis already complete" with the artifact root and report path, and return `COMPLETED` to the caller without asking. `INCOMPLETE`, `CORRUPT`, `INCOMPATIBLE` and `NO_STATE` are handled as below.
- Step 1 is skipped: the source is `--requirements`, already confirmed by the client. Create the run with `begin` as Step 1 describes.
- Skip every "outside the project root" confirmation for that file, both as the source and as the story target.
- Phase 3 target document: the `--requirements` file; do not ask which document.
- End: a completed run prints the Step 8 summary and returns `COMPLETED`. A pause or a blocked gate prints the Step 9 summary and returns `PAUSED` or `BLOCKED`. The last line of your output is exactly `BA_STATUS: COMPLETED`, `BA_STATUS: PAUSED` or `BA_STATUS: BLOCKED`.

Without these arguments, run exactly as described below.
```

In the phase commands, where they ask for confirmation of a path outside the project root (start-analysis source, generate-stories target), add: "In pipeline mode (`/sdlc-pipeline:ba-run` with `--requirements`), the given requirements file is already confirmed — do not ask."
- [ ] **Step 3: Chunked reads.** In `agents/requirement-analyst.md`, `agents/gap-analysis-agent.md`, `agents/story-generation-agent.md` and `skills/requirement-source-discovery/SKILL.md`, wherever a source/requirements Markdown file must be read completely (e.g. "page through long files; confirm lines read equals total lines", "Read the whole file"), state the method:

```
Read it in `offset`/`limit` chunks of at most 200 lines, continuing until a chunk returns fewer lines than requested — that is the end of the file. Never run `wc`, `stat` or `cat` on a Markdown file (this plugin's context-budget hook blocks it). Rules, skills and JSON files under 250 lines may be read in one call.
```

- [ ] **Step 4: Tests.** `python -I -m unittest discover -s tests/ba-requirements` → OK; update only expected strings that assert the old "Project root" wording.
- [ ] **Step 5: Verify and commit.** Grep tool: `Artifact root:` in all 8 `commands/ba-*.md`; `## Pipeline mode` and `BA_STATUS:` in `commands/ba-run.md`; `fewer lines than requested` in the 3 agents and the skill. Validator `Found` count unchanged from Task 1.

```bash
git add commands/ba-*.md agents/requirement-analyst.md agents/gap-analysis-agent.md agents/story-generation-agent.md skills/requirement-source-discovery/SKILL.md tests/ba-requirements
git commit -m "feat: BA artifact root, pipeline mode for ba-run, chunked reads

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `/pipeline-all` Stage Q

**Files:** Modify `commands/pipeline-all.md`; delete `agents/qa-placeholder.md`.

Read `commands/pipeline-all.md` in windows first; the 23 `## ` headings stay unchanged (the Stage Q heading text may stay "Stage Q — QA slot" or become "Stage Q — BA requirements analysis" — if renamed, it is the only heading change).

- [ ] **Step 1: Stage Q body** → replace the `qa-placeholder` dispatch and its bullets with:

```
`<artifact root>` = `<directory of the REQUIREMENTS file>/ba/<its stem without .requirements>/`
(e.g. `docs/features/emv/ba/02-campaigns/`).

- `REQUIREMENTS: none` → say `No requirements file — skipping BA analysis.`, record `ba: skipped`, continue to Stage 0.5.
- Otherwise invoke the skill `sdlc-pipeline:ba-run` with arguments
  `--requirements <REQUIREMENTS path> --artifact-root <artifact root>`. It runs atomic requirements, gap analysis, gap triage with the client (one gap at a time; every Critical and High gap must be resolved) and development stories appended to the requirements file, then returns a last line `BA_STATUS: …`.
- `BA_STATUS: PAUSED` or `BLOCKED` → record `ba: <artifact root> (paused | blocked)` and end the run with: "Your answers are saved. Run `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` to continue — the BA analysis resumes where it stopped."
- `BA_STATUS: COMPLETED` → record `ba: <artifact root> (completed)`. Then ask with `AskUserQuestion`: **Stop and resume in a fresh session (Recommended — lower cost)** | **Continue now**. The BA instructions stay in this session's context for every later turn. **Stop** ends the run with: "Run `/sdlc-pipeline:pipeline-all <REQUIREMENTS path>` in a new session — requirements and BA analysis are kept and skipped."
```

- [ ] **Step 2: Stage 0.8 requirements mode** — append to the quoted requirements-mode instruction: "Also keep every development story from the `# Development Stories` section, one line each: `US-xxx` · title · one line per acceptance criterion · source `REQ-` IDs, under `## Development stories`."
- [ ] **Step 3: Stage 1** — extend the FR-rows sentence: each FR row also cites the `US-xxx` stories it implements, and every story appears in at least one FR row.
- [ ] **Step 4: Stage 3 commit** — the requirements commit also `git add`s `<artifact root>` when it exists.
- [ ] **Step 5: Ledger and rules** — replace the `qa_slot …` TOKEN LEDGER line with `ba: <artifact root> (completed | paused | blocked | skipped)`; remove `QA_OPEN`/`QA_ARTIFACTS` mentions; add hard rule "Never start Stage 0.5 while `ba` is `paused` or `blocked`."; replace any remaining `qa-placeholder` / "QA slot" wording.
- [ ] **Step 6: Delete** `agents/qa-placeholder.md` (`git rm`).
- [ ] **Step 7: Verify.** Grep tool: `qa-placeholder` → 0 in `commands/` and `agents/`; `sdlc-pipeline:ba-run` ≥1 and `BA_STATUS` ≥1 in `commands/pipeline-all.md`; heading count 23. `git diff --exit-code commands/pipeline.md commands/pipeline-parallel.md hooks agents/requirements-writer.md agents/planner.md && echo PROTECTED_UNCHANGED`. Validator count.
- [ ] **Step 8: Commit** `feat: /pipeline-all Stage Q runs the BA requirements analysis` (trailer as above).

---

### Task 4: README and spec pointer

- [ ] README: "What's inside" counts (commands 3 → 11, agents → 19 with the 3 BA agents in and `qa-placeholder` out), list the `ba-*` commands, describe Stage Q in Example 4 and the `/pipeline-all` diagram ("Stage Q  BA analysis: atomic requirements → gaps → triage with you → stories"), add a short "Credits" line: BA requirements analysis by the QA/BA team (`akhilvn-crypto/BA-Pipeline`), MIT — see `licenses/ba-requirements-LICENSE`.
- [ ] `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` §12 item 1 → "The QA agent — replaced by the BA requirements analysis; see `docs/superpowers/specs/2026-10-27-ba-requirements-integration-design.md`."
- [ ] Commit `docs: README and spec for the BA requirements analysis` (trailer as above).

---

### Task 5: Reinstall and manual run (user)

- [ ] `claude plugin uninstall sdlc-pipeline@sdlc-pipeline-dev` then `claude plugin install sdlc-pipeline@sdlc-pipeline-dev`; new session in a scratch git repo.
- [ ] `/sdlc-pipeline:pipeline-all <small idea>` → approve requirements → Stage Q: BA writes under `docs/features/ba/<slug>/`, asks gaps one by one, appends `# Development Stories` to the requirements file, report at `<artifact root>/report/phase3-report.html` → checkpoint question → choose Stop → new session, same command → requirements and BA skipped → continue to Stage 2.5 and stop.

## Spec coverage

| Spec | Task |
|---|---|
| §3 copy table, renames, licence | Task 1 |
| §4 pipeline mode, §5 artifact root, §6 hook fit | Task 2 |
| §7 `/pipeline-all` changes | Task 3 |
| §8 README, old spec | Task 4 |
| §9 verification | Tasks 1–3 verify steps, Task 5 |
