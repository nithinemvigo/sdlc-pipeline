# BA requirements plugin → `/pipeline-all` Stage Q — Design

- **Date:** 2026-10-27
- **Status:** Approved — implemented on feature/pipeline-all
- **Source:** `akhilvn-crypto/BA-Pipeline`, folder `ba-requirements-plugin` (v0.5.1, MIT)
- **Branch:** `feature/pipeline-all` (unreleased 3.2.0)

## 1. Goal

Replace the `qa-placeholder` slot (Stage Q) in `/pipeline-all` with the QA/BA team's
requirements-analysis pipeline, copied into this plugin. After the client approves the
requirements, Stage Q:

1. breaks the approved requirements into atomic requirements (`REQ-xxx`),
2. finds and ranks gaps, then triages them with the client one at a time (every Critical and
   High gap must be resolved),
3. writes development stories with acceptance criteria into a `# Development Stories` section
   at the end of the requirements file, enriched with the client's gap decisions, plus an
   offline HTML report.

The planner then builds from the requirements **including** those stories.

## 2. Decisions (client, 2026-10-27)

| # | Decision |
|---|---|
| D1 | **Copy** the plugin into sdlc-pipeline (not a separate dependency). Later upstream fixes are copied by hand. |
| D2 | BA artifacts go under the feature's own folder, not the project root (§5). |
| D3 | Adapt the copied agents to our context-budget hook: chunked reads, no `wc` on Markdown (§6). |
| D4 | All three BA phases run in Stage Q; `qa-placeholder` is removed. |
| D5 | Both question sets stay: `requirements-writer` asks about major gaps; BA triage asks about each gap (Medium/Low may stay open, as BA already allows). |
| D6 | Appending `# Development Stories` to the approved requirements file is fine; it stays `Approved`. |

## 3. What is copied, and where

| From `ba-requirements-plugin/` | To sdlc-pipeline | Change |
|---|---|---|
| `agents/requirement-analyst.md`, `gap-analysis-agent.md`, `story-generation-agent.md` | `agents/` (same names) | §6 read rules; plugin-name fallback text |
| `commands/<name>.md` (8) | `commands/ba-<name>.md` | renamed with `ba-` prefix; cross-references, artifact root (§5), pipeline mode (§4) |
| `skills/*/SKILL.md` (9) | `skills/*/SKILL.md` | §6 read rules where they say "read completely" |
| `rules/*.md` (8), `schemas/*.json` (3) | `rules/`, `schemas/` | none |
| `scripts/*.py` (8) | `scripts/` (beside `check_plan.py`) | user-facing command names `/ba-requirements:x` → `/sdlc-pipeline:ba-x` |
| `tests/*.py` (4) | `tests/ba-requirements/` | the plugin-root path computation (one level deeper); content assertions updated only where our edits changed text |
| `LICENSE` | `licenses/ba-requirements-LICENSE` | none (MIT notice kept) |

Commands become `/sdlc-pipeline:ba-run`, `:ba-start-analysis`, `:ba-analyse-gaps`,
`:ba-triage-gaps`, `:ba-generate-stories`, `:ba-enrich-stories`, `:ba-sync-stories`,
`:ba-generate-report`. They keep working standalone.

Every "find the plugin directory … `plugin.json` (name `ba-requirements`)" fallback becomes
name `sdlc-pipeline`. Every `${CLAUDE_PLUGIN_ROOT}/commands/<name>.md` becomes
`…/commands/ba-<name>.md`.

## 4. Pipeline mode (`/sdlc-pipeline:ba-run`)

`ba-run` accepts arguments: `--requirements <path>` and `--artifact-root <dir>`. When both are
given it runs in **pipeline mode**:

- **Step 0 (checkpoint):** `COMPLETED` with `artifacts_still_valid` → print "BA analysis
  already complete" with the artifact paths and **return** (no question). `INCOMPLETE` → ask
  Resume / Start a new run as today. `NO_STATE` → new run.
- **Step 1 (source question):** skipped; the source is `--requirements`, already confirmed.
- **"Outside the project root" confirmations** (source and story target) are skipped for that
  path: the client already approved it in Stage R.
- **Story target document:** `--requirements` itself (no target question).
- **End:** completed → final summary, then return to the caller. Paused at triage, or a
  deliberate **Exit and resume later** at the Critical/High story gate → the "stopped/paused"
  summary, then return with status `PAUSED`. A blocked gate with no exit choice, a phase or
  validation failure, or a user cancel → return with status `BLOCKED`. Either way
  `/pipeline-all` stops cleanly.

Without the arguments, `ba-run` behaves exactly as upstream (asks for the source, project root
= current directory).

## 5. Artifact root

All BA commands replace "Project root: the current working directory" with "Artifact root:
`--artifact-root` when given, otherwise the current working directory", and pass it as the
scripts' `--project-root` (the scripts already accept it). `/pipeline-all` uses:

`<artifact root>` = `<directory of the requirements file>/ba/<requirements file stem without .requirements>/`

- single file `docs/features/export.requirements.md` → `docs/features/ba/export/`
- part `docs/features/emv/02-campaigns.requirements.md` → `docs/features/emv/ba/02-campaigns/`

So each part has its own atomic requirements, gap register, stories state, report and
checkpoint (`<artifact root>/.ba-requirements/pipeline-state.json`) — runs never mix.

## 6. Hook fit (`hooks/guard_context_budget.py`)

- `ba-run` is started as a skill, so its 326-line file is injected, not `Read`. The phase
  command files it reads "in full" are all under 250 lines / 20,000 bytes — allowed.
- Requirement files can exceed 250 lines. The copied agents and the
  `requirement-source-discovery` skill change "read completely / confirm lines read equals
  total lines" to: **read in `offset`/`limit` chunks of ≤200 lines until a chunk returns fewer
  lines than asked; that is the end of the file.** Never `wc`/`stat` a Markdown file (Rule 3
  blocks subagents).
- BA JSON artifacts are allow-listed (`*.json`); HTML is never read by agents.
- Stage R deletes stale contracts before Stage Q, and Stage 0.8 (which creates the contract)
  runs after Stage Q, so Rule 2 never shadows the requirements file while BA reads it.
- The hook refuses a second full `Read` of the same file, so pipeline mode re-reads a changed
  or evicted file with an explicit `offset`/`limit` window, and each agent re-invocation
  writes a new draft file (`draft-2.json`, `draft-3.json`, …).

## 7. `/pipeline-all` changes

| Stage | Change |
|---|---|
| Q | Replace the `qa-placeholder` dispatch: invoke the skill `sdlc-pipeline:ba-run` with `--requirements <REQUIREMENTS path> --artifact-root <repo root>/<artifact root>` (absolute; `ba-run` also resolves both to absolute paths). Skip Stage Q (one line) when `REQUIREMENTS: none`, and skip the skill when `pipeline-state.py inspect` on the artifact root already reports `COMPLETED` with `artifacts_still_valid`. After a completed run, write `<artifact root>/.gitignore` (`.ba-requirements/`, `stories/backups/`) if absent. On `PAUSED`/`BLOCKED`: stop the run with "Your answers are saved. Run `/sdlc-pipeline:pipeline-all <requirements path>` to continue — the BA analysis resumes where it stopped." On completion: record `BA: <artifact root> (completed)`, then ask **Continue now** \| **Stop and resume in a fresh session (Recommended — lower cost)**, because the BA files stay in this session's context for every later turn. |
| 0.8 | Requirements-mode distiller dispatch also keeps every development story: `US-xxx` · summary · one line per acceptance criterion (stories in the file carry no `REQ-` IDs), under `## Development stories`. The size check runs on the file **with** stories. |
| 1 | Planner dispatch: FR rows cite the `US-xxx` stories (and `BR-`/`AC-` IDs) they implement; every story appears in at least one FR row. |
| 3 | The requirements commit also adds `<artifact root>` (gap register, decisions, stories state, report, `.gitignore`), excluding `.ba-requirements/` (checkpoint with absolute local paths) and `stories/backups/` (copies of the requirements file). |
| Ledger | `qa_slot` → `ba: <artifact root> (completed \| paused \| blocked \| skipped)`. |
| Hard rules | Never start Stage 0.5 while BA is `PAUSED` or `BLOCKED`. |

`agents/qa-placeholder.md` is deleted.

## 8. Other files

- `README.md`: new commands and agents (counts), Stage Q description, credit and licence
  pointer for the BA plugin.
- `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` §12 item 1 → points here.

## 9. Verification

1. Safety scan of the copied Python before running anything: grep for network access
   (`urllib`, `requests`, `socket`, `http`), process spawning outside the plugin's own scripts,
   and deletes outside the artifact root (`rmtree`, `remove`, `unlink`). Report findings.
2. `python -I -m unittest discover -s tests/ba-requirements` → all pass;
   `python -m unittest discover -s hooks/tests` → all pass.
3. Greps: no `/ba-requirements:` and no `name ba-requirements` left; no reference to
   `qa-placeholder`; `ba-run` invoked in Stage Q.
4. `claude plugin validate .` → no new warnings beyond the baseline (14).
5. Manual: `/sdlc-pipeline:pipeline-all <small idea>` → approve → Stage Q runs BA on the file,
   writes under `docs/features/ba/<slug>/`, triage asks per gap, stories appended → checkpoint
   question → stop at Stage 2.5.

## 10. Out of scope

Upstream sync automation; changing BA methodology, rules or schemas; using BA's gap register
anywhere other than story enrichment.
