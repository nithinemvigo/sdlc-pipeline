---
description: Run the complete BA Requirements pipeline - atomic requirements, gap analysis and triage, development stories, enrichment and the consolidated HTML report (BA Requirements, master command)
argument-hint: [--requirements <path> --artifact-root <dir>]
allowed-tools: Read, Write, Glob, Grep, Agent, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Run (master pipeline)

You orchestrate the whole pipeline. This command contains **no phase logic of its own**: every phase is carried out by following the existing phase command file, with the hand-offs, gates and overrides below. Do not improvise methodology, hand-write any artifact, or bypass the scripts those commands use.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same). Every generated artifact goes under the project root, never into the plugin directory.

If a path below still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `commands/ba-run.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`) and use that.

Use whichever of `python`, `python3`, `py` works. If none does, tell the user Python 3 is required and ask before installing or doing anything else. Never install dependencies automatically. Do not introduce a database or vector store.

**The run is resumable.** Every pipeline operation persists its state in `<project root>/.ba-requirements/pipeline-state.json` through `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py`, so an interrupted run continues from its last completed operation instead of restarting. Never edit that file by hand. It is the orchestration source of truth only; it holds no requirements, gaps, stories or report content, which stay in their own folders.

## Pipeline mode

When the arguments include `--requirements <path>` and `--artifact-root <dir>` (as `/sdlc-pipeline:pipeline-all` passes them), run in pipeline mode:

- First resolve `--requirements` to an absolute path against the session working directory, and use that absolute path everywhere (`--sources`, `--target`, the agent prompts).
- Every script call in this command and in the phase commands and skills it follows — including shorthand mentions such as `pipeline-state.py start --operation …` or `gap-register-store.py summary` — gets `--project-root <artifact root>`. Never rely on the script default. (`validate-atomic-requirements.py` and `validate-gap-register.py` take no `--project-root`; give them their file paths as shown, with `<project root>` meaning the artifact root.)
- Step 0: `COMPLETED` with `artifacts_still_valid` → print "BA analysis already complete" with the artifact root and report path, and return `COMPLETED` to the caller without asking. `INCOMPLETE`, `CORRUPT`, `INCOMPATIBLE` and `NO_STATE` are handled as below.
- Step 1 is skipped: the source is `--requirements`, already confirmed by the client. Create the run with `begin` as Step 1 describes.
- Skip every "outside the project root" confirmation for that file, both as the source and as the story target.
- Phase 3 target document: the `--requirements` file; do not ask which document.
- In pipeline mode, every "To continue" line says: run `/sdlc-pipeline:pipeline-all <requirements path>` again (or `/sdlc-pipeline:ba-run` with the same `--requirements` and `--artifact-root`).
- End: print the Step 8 or Step 9 summary, then map the end to a status:
  - Step 8 `COMPLETED` or `COMPLETED WITH FOLLOW-UP` (or the Step 0 "already complete" return) → `BA_STATUS: COMPLETED`.
  - A stop / exit during triage (5a or 5c) → `BA_STATUS: PAUSED`.
  - **Exit and resume later** at the story-generation gate → `BA_STATUS: BLOCKED`.
  - Any other Step 9 end — `STOPPED`, a phase, validation, report or final-validation failure, a user cancel, or Step 0 **Cancel** → `BA_STATUS: BLOCKED`.

  The last line of your output is always exactly one of `BA_STATUS: COMPLETED`, `BA_STATUS: PAUSED` or `BA_STATUS: BLOCKED`.

Without these arguments, run exactly as described below.

## How to run a phase

For each phase, `Read` the phase command file in full and follow its steps and rules exactly, including every validation, confirmation and safe-write step. The files are the single source of truth:

| Phase | Command file | Role here |
|---|---|---|
| 1 | `${CLAUDE_PLUGIN_ROOT}/commands/ba-start-analysis.md` | atomic requirements |
| 2a | `${CLAUDE_PLUGIN_ROOT}/commands/ba-analyse-gaps.md` | gap register and gap report |
| 2b | `${CLAUDE_PLUGIN_ROOT}/commands/ba-triage-gaps.md` | interactive triage |
| 3a | `${CLAUDE_PLUGIN_ROOT}/commands/ba-generate-stories.md` | development stories |
| 3b | `${CLAUDE_PLUGIN_ROOT}/commands/ba-enrich-stories.md` | enrichment from resolved decisions |
| 3c | `${CLAUDE_PLUGIN_ROOT}/commands/ba-generate-report.md` | consolidated HTML report |

Overrides that apply to every phase file when it runs under this command:

- **Skip its closing "Execution summary" and its closing "Pipeline checkpoint" step.** Print one-line phase progress instead (see "Progress lines"). The only full summary is the final one in Step 8. This command maintains the checkpoint itself (see "Checkpoint protocol").
- **"Stop" means stop the pipeline.** Where a phase file says to stop, explain why, run Step 9 (pipeline stopped) and do not start a later phase.
- **Do not repeat a question already answered here** (the source location, the target document).
- Ignore any "Next step: run /sdlc-pipeline:ba-..." suggestions in the phase files; this command is the next step.
- Every counts, status and path reported must come from the scripts' JSON output or the agents' reports. Never use illustrative or estimated numbers.

Keep a short in-conversation ledger as you go: source files confirmed and their count, atomic requirement count, per-phase validation results, gap counts before and after triage, gaps presented / resolved / skipped in this run, the story-generation gate result, stories created and updated, decisions incorporated, report status. The final summary is built from it plus a fresh `summary` call.

### Progress lines

After each phase gate print one line, for example `Phase 1 — Atomic requirements: PASSED (<n> requirements)`, using real values. Use `PASSED`, `REUSED`, `FAILED`, `PAUSED`, `BLOCKED` or `SKIPPED`. An operation that a resume skips because its recorded result is still valid is `REUSED`.

### The story-generation gate (mandatory)

Phase 3 may start only when **every Critical and High priority gap has status `resolved`**. Medium and Low gaps never affect the gate: they may be open or skipped and Phase 3 still runs.

Evaluate the gate with a fresh call, never from memory or the ledger:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py list --project-root <project root>
```

`queue` holds every gap that is `open` or `skipped`, each with `gap_id`, `priority`, `status` and `gap_definition`. The **blockers** are the queue entries whose `priority` is `Critical` or `High`. The gate **passes** only when there are no blockers (an empty register or an empty queue passes). The gate **fails** when there is at least one blocker, and also when `list` itself fails (exit 1: the register is missing, invalid or stale against the atomic requirements), because the gate then cannot be verified; stop the pipeline (Step 9) with the exact `error` and `details`.

Nothing the user selects can bypass the gate: not "skip this gap", not "skip all remaining gaps", not "continue anyway". Skipped and open are both unresolved. There is no override option; do not offer one, and do not start Phase 3 on the user's say-so while a blocker remains.

## Checkpoint protocol (mandatory)

`${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py` takes `--project-root <project root>` on every call and prints JSON (exit 0 = done, 1 = refused, blocked or invalid with the reason in `error` and `details`, 2 = a file could not be read or written). The pipeline has nine operations, tracked separately and in this order:

| # | Operation name | Carried out by |
|---|---|---|
| 1 | `resolve_source` | Step 2, source resolution and confirmation |
| 2 | `atomic_requirements` | Step 3 |
| 3 | `gap_analysis` | Step 4 |
| 4 | `gap_triage` | Step 5a |
| 5 | `gate_validation` | Steps 5b–5c |
| 6 | `generate_stories` | Step 6 |
| 7 | `enrich_stories` | Step 7, enrichment |
| 8 | `phase3_report` | Step 7, report |
| 9 | `final_validation` | Step 8 |

For every operation:

1. **Before the work:** `pipeline-state.py start --operation <name> --project-root <project root>` persists `in_progress`. A refusal means an earlier operation is not completed or a gate does not pass: do not do the work.
2. **Immediately before each write that applies results** (saving the atomic requirements, the gap register, the stories): `pipeline-state.py check-inputs --operation <name> --project-root <project root>`. If it exits 1 with code `INPUTS_CHANGED`, a source file or an upstream artifact changed while the operation ran. Apply nothing, report the changed inputs, and ask with AskUserQuestion whether to **restart from source analysis** (`pipeline-state.py invalidate --from resolve_source --reason <why> --project-root <project root>`, then go to Step 2) or **stop** (Step 9, `BLOCKED`).
3. **Immediately after the operation's gate passes:** `pipeline-state.py complete --operation <name> --project-root <project root>`. It verifies the result itself (validators, register state, story validation, report) and records the output fingerprints. If it exits 1 the operation is recorded `failed` (or `blocked` for the gate): report its `error` and `details` and go to Step 9; never print `PASSED` for it.
4. **On any failure you detect yourself** (an agent reports `INCOMPLETE`, a save or read-back fails, the user cancels): `pipeline-state.py fail --operation <name> --error <one-line reason> --project-root <project root>`, then Step 9. A failed operation keeps its error and every earlier checkpoint.

A reused output (for example an existing, valid `atomic_requirements.json`) is still started and completed, so it is checkpointed; its progress line says `REUSED`. Persist the checkpoint after each operation; do not batch these calls up.

**Interactive triage.** Saving an answer stays with `gap-register-store.py`. As soon as a store call succeeds, call `pipeline-state.py triage-event --gap-id <GAP-id> --action <resolved|revised|skipped|reopened> --project-root <project root>`; also record `--action presented` when a gap is shown. Save in the store first, then record the event, so the register is never behind the checkpoint. The event holds the gap ID, action and resulting status only; the decision text stays in the register. The script refuses an event the register does not confirm. Do this for every answer, skip and status change in 5a and 5c, one at a time, not at the end of the pass.

**Never repeat valid work.** Never run, re-ask or re-confirm an operation the resume reported as reused. Never mark an operation `completed` yourself: only `complete` does.

**Safe reruns.** An operation that was `in_progress` when the session ended is rerun from its start. Every phase file you follow is already safe to rerun (read-back verified, atomic replace, nothing overwritten without confirmation), so existing artifacts are reconciled, not replaced: user decisions, gap IDs, story IDs and manual edits to the stories section are preserved, and the phase files' own questions ask before anything is overwritten.

## Step 0 — Check the pipeline checkpoint (always first)

Before any question, read the checkpoint:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py inspect --project-root <project root>
```

Act on `state_status`:

| `state_status` | Action |
|---|---|
| `NO_STATE` | A new run. Go to Step 1. |
| `INCOMPLETE` | Show the run ID, `run_status`, `last_completed_operation`, one line per operation (its recorded status and verdict `valid`, `invalid` or `not_completed`), where it would continue (`resume_from`), the `problems` of every `invalid` operation, any `triage_drift` and the triage counts. Then ask with AskUserQuestion: **Resume** (Recommended) or **Start a new run**. |
| `COMPLETED` | Show the run ID, its last completed operation and `artifacts_still_valid` (with the `artifact_problems` if not). A completed run is never reused as a new execution. Ask: **Start a new run** or **Cancel**. |
| `CORRUPT` or `INCOMPATIBLE` | Show `errors` plainly. Say the checkpoint file was not changed, that nothing in it is assumed completed, that the phase artifacts on disk are untouched and will be detected in Step 2, and that a fresh run archives the file under `.ba-requirements/history/` (it is not deleted). Ask: **Start a fresh run** or **Cancel**. |

**Resume.** Run `pipeline-state.py resume --project-root <project root>`. It re-validates every completed operation (source and artifact fingerprints, output files, validators, the gate), invalidates the first invalid operation and everything after it, and returns `resume_from`, `reused`, `rerun` and `reasons`. Then:

- Tell the user in a few lines what is reused, what reruns and why. If `reasons` name a changed source file or artifact, say which and that the dependent operations rerun with decisions and story IDs preserved.
- Use `source_files` from the checkpoint; do not ask the source question again. If one of those files is gone, ask where it is now (Step 1 wording) and continue from Step 2 with the new location.
- Rebuild the ledger from `pipeline-state.py summary --project-root <project root>` and fresh script calls, never from memory.
- Print a `REUSED` progress line for each reused operation, then continue at the step for `resume_from` and skip every step whose operation was reused. Continue through Step 5 and the gate exactly as in a first run: after a resume the gate is evaluated again and Critical and High gaps still block Phase 3.
- Resuming after a pause at the gate returns to 5b: re-evaluate the gate, and if it is blocked offer 5c.

**Start a new run.** Go to Step 1; the checkpoint is replaced there (`begin --replace`), after the old file is archived.

## Step 1 — Ask for the source (new run only)

Your first message of a new run must be this question, and nothing else happens before the answer. Stop and wait for the reply. (A resumed run does not ask it; see Step 0.)

> Where does your requirements document reside? You can provide a folder name, directory path, or individual filename.

After the reply, create the run: `pipeline-state.py begin --project-root <project root>`, with `--replace` when the user chose **Start a new run** or **Start a fresh run** in Step 0.

## Step 2 — Detect existing work

Operation 1, `resolve_source`. Skipped when a resume reused it. Do this before any phase runs, and never overwrite anything silently.

1. `pipeline-state.py start --operation resolve_source --project-root <project root>`. Resolve and confirm the source exactly as Phase 1 Steps 2–3 describe (`requirement-source-discovery` skill: Markdown only, ambiguity asked, multi-file sets confirmed, outside-project sources confirmed). Keep the confirmed absolute `.md` paths. Then `pipeline-state.py complete --operation resolve_source --sources <confirmed path> [<confirmed path> ...] --project-root <project root>`; this records the source files and their fingerprints (the requirements text outside any `# Development Stories` section). If it fails, the source is not usable: Step 9.
2. Inspect the three artifact areas with the read-only inspectors:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py inspect --project-root <project root>
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py inspect --project-root <project root>
```

   Both are read-only and may report missing or invalid inputs; that is information, not an error, at this point. Also check whether `report/phase3-report.html` exists.

3. Decide the starting point for Phase 1. On a resume that reused `atomic_requirements`, skip this item and the staleness heuristic: the checkpoint already compared the recorded fingerprints. Otherwise:

| Finding | Action |
|---|---|
| `atomic_requirements/atomic_requirements.json` absent | Run Phase 1. |
| Present but fails `validate-atomic-requirements.py` | Tell the user the existing file is invalid and why. Phase 1 will not overwrite it silently; its Step 7 asks replace / save under another name / cancel. Run Phase 1. |
| Present and valid | Ask with AskUserQuestion: **reuse it** or **re-run Phase 1**. Show its requirement count and date, and the evidence about staleness (below). Recommend reuse only when no source file is newer. Re-running goes through Phase 1 Step 7, which asks before replacing, and warns that IDs can change and gap and story mappings then need reconciliation. |

Staleness evidence for a valid existing file in a run that has no earlier record of it: Phase 1 does not record its source hashes, so compare file modification times of the confirmed source files with `atomic_requirements.json` (for example `python -c "import os,sys; ..."`) and report plainly whichever source files are newer. Say this is a heuristic, not proof. From here on the checkpoint records the real fingerprints, so a later resume compares hashes, not times.

4. If the gap register or stories section already exists, say so in one line (counts from the inspectors), so the user knows this is a continuation of earlier work and that Phases 2 and 3 will reconcile, not restart.

## Step 3 — Phase 1: atomic requirements

Operation 2, `atomic_requirements`. Skipped when a resume reused it. `pipeline-state.py start --operation atomic_requirements` first.

If reusing the existing file, skip to the gate. Otherwise follow `ba-start-analysis.md` Steps 4–7 (draft location, Requirement Analyst, independent validation, safe persistence), calling `check-inputs` right before its Step 7 writes. Step 1 of that file (the source question) and the confirmation in Step 3 are already done.

**Gate — must pass to continue.** The saved `atomic_requirements/atomic_requirements.json` must pass:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-atomic-requirements.py <project root>/atomic_requirements/atomic_requirements.json
```

Then `pipeline-state.py complete --operation atomic_requirements`. Stop the pipeline (Step 9, operation `fail`ed) if the source cannot be read, was only partially processed, the file is empty, validation fails, the save or read-back check fails, or the user cancels. A Phase 1 failure blocks every later operation: never run Phase 2 after it. Record: source files analysed, requirement count, validation result.

## Step 4 — Phase 2a: gap analysis

Operation 3, `gap_analysis`. Skipped when a resume reused it. `pipeline-state.py start --operation gap_analysis` first. Gap analysis must complete before triage and story generation.

Follow `ba-analyse-gaps.md` Steps 1–7 and 9 (inspect, agent, validation, reconciliation review, safe save, verify), calling `check-inputs` right before its Step 7 save. Reconciliation of an existing register, including keep/reopen and retire decisions, is asked of the user exactly as that file specifies. A destructive reset (its Step 8) happens only if the user asks for it.

**Gate — must pass to continue.** `validate-gap-register.py` passes on the saved `gaps/gaps.json`, `gap-register-store.py inspect` reports `UNCHANGED`, and `gaps/gap-analysis.html` exists (a failed HTML regeneration with a saved, valid register is a warning: run `regenerate-report` once, then continue and report it as stale if it still fails). Then `pipeline-state.py complete --operation gap_analysis`. Stop the pipeline (Step 9) on `INPUT_*`, `REGISTER_INVALID`, a failed save or a failed validation. If the register is empty (no gaps), say so and continue to Phase 3 with triage skipped (the story-generation gate passes because there is nothing to resolve).

Record: gaps by priority and status from `gap-register-store.py summary`.

## Step 5 — Phase 2b: interactive gap triage

Operations 4 and 5, `gap_triage` and `gate_validation`. Skipped when a resume reused them. If only the gate is incomplete, go straight to 5b.

Run `gap-register-store.py list`. If `eligible_count` is 0, run `pipeline-state.py start --operation gap_triage` and `pipeline-state.py complete --operation gap_triage --note "no open or skipped gaps"`, report `Phase 2 triage: SKIPPED (no open or skipped gaps)`; the gate passes; go to 5b.

Otherwise run triage, then the gate.

### 5a — First triage pass

`pipeline-state.py start --operation gap_triage` first (a resumed triage simply starts again and presents the remaining open and skipped gaps, Critical and High first). Follow `ba-triage-gaps.md` Steps 1–3 (the `gap-triage` skill): one gap at a time, Critical first, each decision confirmed before it is recorded and saved immediately through the store, and each answer, skip or status change recorded at once with `triage-event` (see "Checkpoint protocol"). The user can:

- provide a decision, which resolves the gap once confirmed;
- **skip** the current gap (it becomes `skipped` and stays unresolved). If the gap is Critical or High, say in one line that it still blocks story generation until it is resolved;
- **skip all remaining gaps**: nothing further is written and the remaining gaps keep their status. This ends the pass; it does **not** continue to Phase 3. Complete `gap_triage` and go to 5b;
- **stop / exit**: the pipeline **pauses**. Everything already confirmed is already saved in the register and the checkpoint. Leave `gap_triage` as it is (`in_progress`), do not start Phase 3. Go to Step 9 with status `PAUSED` and tell the user that running `/sdlc-pipeline:ba-run` again offers Resume (the source and Phase 1 and 2 outputs are validated and reused, and triage returns to the remaining open and skipped gaps, Critical and High first).

If the session is interrupted unexpectedly, no special handling is needed: each answer was saved the moment it was confirmed and recorded in the checkpoint, and the next run offers Resume from the interrupted operation.

Skipped and open gaps are never treated as resolved. A failed save of a decision is reported and offered a retry; it is not ignored.

When the queue is exhausted, or after skip all remaining, `pipeline-state.py complete --operation gap_triage` and go to 5b.

### 5b — Story-generation gate

`pipeline-state.py start --operation gate_validation`, then evaluate the gate (see "The story-generation gate"), then `pipeline-state.py complete --operation gate_validation`. That call evaluates the gate itself and does not trust the ledger: it exits 1 with the `blockers` and leaves the operation `blocked` while any Critical or High gap is `open` or `skipped`, and it stays blocked across resumes until the condition holds.

- **Passes:** print `Phase 2 — Story gate: PASSED (all Critical and High gaps resolved)` and state how many Medium/Low gaps remain open or skipped, saying they do not block Phase 3. Go to 5d.
- **Fails:** print `Phase 2 — Story gate: BLOCKED` and list every blocker with its `gap_id`, priority, status (`open` or `skipped`) and a one-line form of its `gap_definition`. Say plainly that Phase 3 cannot start while any Critical or High gap is unresolved, and that skipping does not change that. Then ask with AskUserQuestion, with exactly these two options and no way to continue to Phase 3:
  1. **Resolve the blocking gaps now (Recommended)** — go to 5c.
  2. **Exit and resume later** — the pipeline **pauses**. Nothing is lost; `gate_validation` stays `blocked` in the checkpoint. Go to Step 9 with status `PAUSED`, reason "story-generation gate blocked", the blockers listed, and the instruction to run `/sdlc-pipeline:ba-run` again and choose Resume.

### 5c — Blocker triage pass

Triage only the current blockers, in the order `list` returned them (Critical first), with the same rules, confirmations, immediate saves and `triage-event` records as 5a. Override the skill's "present each gap at most once per session" rule for this: a blocker skipped in an earlier pass is presented again, but at most once per pass. The user may still skip a gap, skip all remaining, or stop; stop pauses as in 5a. When the pass ends for any reason other than stop, return to 5b (`start` then `complete` on `gate_validation` again, with a fresh `list`). Repeat 5b–5c until the gate passes or the user exits.

Medium and Low gaps are not presented in this pass. They are only presented in 5a, or by running `/sdlc-pipeline:ba-triage-gaps` later.

### 5d — Triage result

Run `gap-register-store.py summary` and record gaps presented / resolved / skipped in this run and the register totals by status. Print `Phase 2 — Gaps: <open> open, <skipped> skipped, <resolved> resolved`. Continue to Step 6.

## Step 6 — Phase 3: development stories

Operation 6, `generate_stories`. Skipped when a resume reused it.

**Precondition: the story-generation gate must have passed.** Run `pipeline-state.py start --operation generate_stories` first; it re-evaluates the gate itself and refuses (exit 1, `blocked_operation` `gate_validation`) while a Critical or High gap is `open` or `skipped`, or the gate cannot be verified, and it puts `gate_validation` back to `blocked`. Then, immediately before the `apply` call in `ba-generate-stories.md` Step 7 (dry run and real write), evaluate the gate again with a fresh `list` and call `check-inputs`; the register may have changed since Step 5. If either fails, do not write anything: return to Step 5b. Never run, resume or partially run this step while a Critical or High gap is `open` or `skipped`. This applies equally on a resume where stories already exist.

Follow `ba-generate-stories.md` Steps 1–8 with these hand-offs:

- **Target document.** If the confirmed source in Step 2 is a single `.md` file, use it as `--target`. If several files were confirmed, ask the user to select the single primary document that holds the `# Development Stories` section (Step 3 of that file). If `inspect` already shows a recorded target, reuse it and do not ask again. Never add the section to several files.
- **Gap register.** The register was validated in Phase 2, so pass no `--ignore-gaps`. If the register has become invalid or unreadable, stop the pipeline (Step 9); do not continue without gap context from this command. The user can run `/sdlc-pipeline:ba-generate-stories` on its own to make that choice explicitly.
- **Only open or skipped Medium and Low gaps can remain at this point, and they do not block story generation.** Generate stories from the validated atomic requirements and the resolved decisions. Never decide an open or skipped gap and never invent answers or acceptance criteria.
- **Story contract.** Each story in the document holds exactly four fields: Story ID, Summary, Detailed Description, Acceptance Criteria. Requirement-to-story and gap-to-story mappings stay in `stories/story-generation-state.json` only. `validate-development-stories.py` enforces this; treat its failure as a gate failure.
- **Safe update.** Keep using the dry-run, conflict, `--expected-source-sha256`, backup and read-back protections. If the managed section or a story was edited by hand, the conflict process in the phase file asks the user before anything is changed. Existing story IDs and unrelated content are preserved.
- If the stories already cover all requirements and nothing changed, report that and keep the existing section untouched (Step 4 of that file), then continue to enrichment.

**Gate — must pass to continue.** `apply` returned `ok` true (exit `0`, or `3` where only the report is stale), and `summary` reports story validation passed. Stop the pipeline (Step 9) on any other result. Exit `4` (document saved, state not) is not complete: follow that file's `accept` guidance and re-check before continuing.

Then `pipeline-state.py complete --operation generate_stories`, which checks the gate and the stories again. Record: stories created (from `apply`), stories in the document, requirements covered, validation result.

## Step 7 — Phase 3: enrichment and report

**Enrichment.** Operation 7, `enrich_stories`; `pipeline-state.py start --operation enrich_stories` first, `check-inputs` before its `apply`, and `complete` after it (which refuses while resolved decisions are not yet reflected in the stories). Skipped when a resume reused it. Run `sync-development-stories.py inspect` again. Then follow `ba-enrich-stories.md` Steps 2–9:

- Use only confirmed decisions from **resolved** gaps. Open and skipped gaps are not decisions.
- With `pending_decisions` empty and no reopened gap needing a change, that file's Step 4 applies: report that no enrichment was required, change no story.
- Reopened gaps, new-story proposals and conflicts are put to the user exactly as that file specifies.

Record: decisions incorporated, decisions needing no story change, stories enriched (from `apply`), stories unchanged, validation result.

**Report.** Operation 8, `phase3_report`; `pipeline-state.py start --operation phase3_report` first and `complete` after. Skipped when a resume reused it. Follow `ba-generate-report.md` to refresh `report/phase3-report.html` from the authoritative artifacts, unless an `apply` in this run already produced it and `summary` shows it current. The report shows development stories, open gaps, resolved gaps, skipped gaps, recorded business decisions, summary counts and a generation timestamp; stories, gaps and decisions stay in their own sections and no gap or requirement metadata appears inside a story entry. All of that is done by the script; you only check the result.

If report generation fails: the requirements document and the state are valid and stay as they are, the previous report is retained, and `phase3_report` is recorded `failed` (`pipeline-state.py fail`) with its reason, so the run is not marked completed. Go to Step 9 with status `STOPPED`; the summary says clearly that the report is **STALE** (a previous report exists) or **UNAVAILABLE** (none exists), with the reason, and that `/sdlc-pipeline:ba-run` with Resume reruns only the report (or `/sdlc-pipeline:ba-generate-report` as the fix). This is not a reason to undo anything. Never print `GENERATED` for it.

## Step 8 — Final execution summary

Operation 9, `final_validation`. `pipeline-state.py start --operation final_validation`, then `pipeline-state.py complete --operation final_validation`. It re-validates every earlier result (atomic requirements, gap register, the Critical/High gate, story validation, enrichment, the report) and only then marks the run `completed`. If it exits 1, report its `details` and go to Step 9 with status `STOPPED`.

Run `pipeline-state.py summary --project-root <project root>` for the run facts (run ID, last completed operation, skipped and rerun operations), and `gap-register-store.py summary` and `sync-development-stories.py summary` once more. Print this, replacing every placeholder with an actual value (counts and statuses from script output and the ledger; priority counts from the register, for example by reading `gaps/gaps.json` with `python -c` and counting `priority` against `status`, or `gaps.unresolved_by_priority` from the pipeline summary; decisions recorded as the total number of entries in the `decisions_recorded` arrays). Omit nothing; write `0`, `none` or `not run` where that is the truth.

```text
BA REQUIREMENTS PIPELINE — <COMPLETED | COMPLETED WITH FOLLOW-UP | STOPPED | PAUSED>

Run: <run id>   (checkpoint: .ba-requirements/pipeline-state.json, status <completed | ...>)
Last completed operation: <operation name>
Resumed (skipped, still valid): <operation names | none>
Rerun: <operation names | none>

Source files analysed: <n>
Atomic requirements generated: <n>   (<new | reused existing file>)

Gaps (<total>):
- By priority:  Critical <n>, High <n>, Medium <n>, Low <n>
- By status:    Open <n>, Skipped <n>, Resolved <n>
- This run:     presented <n>, resolved <n>, skipped <n>
- Story gate:   <PASSED — all <n> Critical and High gaps resolved | BLOCKED>
- Unresolved:   Critical <n>, High <n>, Medium <n>, Low <n>   (open + skipped)
Business decisions recorded: <n total>   (<n> this run)

Stories:
- Generated this run: <n>   (in document: <n>)
- Enriched this run: <n>    (decisions incorporated: <n>, needing no story change: <n>)
- Requirements covered: <n> of <n>

Validation:
- Phase 1 atomic requirements: <Passed | Failed | Not run>
- Phase 2 gap register:        <Passed | Failed | Not run>
- Phase 3 stories:             <Passed | Failed | Not run>

Artifacts:
- atomic_requirements/atomic_requirements.json
- gaps/gaps.json, gaps/gap-analysis.html
- <target document> (Development Stories section; backup: <path>)
- stories/story-generation-state.json
- HTML report: <project root>/report/phase3-report.html — <GENERATED <timestamp> | STALE: <reason> | UNAVAILABLE: <reason>>

Follow-up required:
- <n> Medium/Low gaps remain open and <n> skipped (list their IDs); they did not block story generation. Stories contain only what the requirements and resolved decisions support. Re-run /sdlc-pipeline:ba-run (or /sdlc-pipeline:ba-triage-gaps then /sdlc-pipeline:ba-enrich-stories) after they are decided.
- <any stale report, unreconciled manual edit, requirement not covered, or warning from earlier steps>
```

A pipeline that reaches this summary has always passed the story-generation gate, so the Critical and High unresolved counts are `0` here. Use `COMPLETED` only when all phases passed their gates, the report is `GENERATED`, and no open or skipped gaps remain. Use `COMPLETED WITH FOLLOW-UP` when final validation succeeded but Medium/Low gaps remain open or skipped. A stale or unavailable report is a `STOPPED` run (Step 9), not a completed one. Remind the user that original requirement text outside the `# Development Stories` section was not modified, and that the report is a read-only view.

## Step 9 — Pipeline stopped or paused

When a gate fails, an operation fails or is blocked, the user cancels, or the user stops triage, make sure the checkpoint records it (`fail` or `block` with the reason; a user pause leaves the interrupted operation `in_progress` and a blocked gate `blocked`), then run `pipeline-state.py summary --project-root <project root>` for the run facts and print this instead of Step 8, with actual values:

```text
BA REQUIREMENTS PIPELINE — <STOPPED | PAUSED>

Run: <run id>   (checkpoint status <in_progress | blocked | failed>)
Last completed operation: <operation name | none>
Stopped at: <phase, step and operation name>
Reason: <exact error or user choice, with the script's details>

Completed before the stop:
- <phase>: <result and artifact path>

Blocking gaps (only when stopped at the story-generation gate; from the latest `list`):
- <GAP-id> — <Critical | High> — <open | skipped> — <one-line definition>

Not started: <phases>

Preserved: <artifacts kept as they were, including all gap answers and triage status already saved>
To continue: <the fix, if any>, then run /sdlc-pipeline:ba-run again and choose Resume; it continues from the first incomplete or invalid operation, and completed operations whose inputs and outputs are still valid are not repeated. (At the gate: resolve the blocking gaps, in the pipeline or with /sdlc-pipeline:ba-triage-gaps; Phase 3 starts once every Critical and High gap is resolved.)
```

A pause at the gate uses status `PAUSED`, stage "Phase 2 — story-generation gate", and "Not started: Phase 3 (stories, enrichment, report)". The Phase 2 gap register and gap report are complete and valid and are listed under "Completed before the stop".

Never claim a later phase ran, never call a stopped pipeline completed, and do not delete or roll back valid earlier outputs.
