---
description: Analyse atomic requirements for gaps, prioritise them and save the gap register and HTML dashboard (BA Requirements, Phase 2)
allowed-tools: Read, Write, Glob, Grep, Agent, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Analyse Gaps (Phase 2)

You orchestrate this command. Methodology lives in the plugin's agent, skills and rules; follow them rather than improvising.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same).

This phase identifies and prioritises gaps only. Do not record decisions, resolve gaps, write user stories or acceptance criteria, integrate with Jira, or modify the atomic requirements or any source document. Do not hand-write `gaps.json`, the state file or the HTML: every write goes through `scripts/gap-register-store.py`.

In every command below use whichever of `python`, `python3`, `py` works. If none does, tell the user Python 3 is required and ask before installing or doing anything else.

## Step 1 — Load the standards

Read these files in full and follow them:

- `${CLAUDE_PLUGIN_ROOT}/rules/gap-analysis-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/artifact-management-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/gap-identification/SKILL.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/gap-prioritisation/SKILL.md`

If a path still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/gap-analysis-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`) and use that.

## Step 2 — Inspect the project

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py inspect --project-root <project root>
```

Act on `status`:

| status | Action |
|---|---|
| `INPUT_MISSING` | Stop. Say `atomic_requirements/atomic_requirements.json` was not found and that Phase 1 must be run first with `/sdlc-pipeline:ba-start-analysis`. |
| `INPUT_INVALID` | Stop. Report the validation errors from `errors` and explain how to correct the file or re-run Phase 1. Create nothing. |
| `INPUT_EMPTY` | Stop. Explain there are no requirements to analyse. Create nothing. |
| `REGISTER_INVALID` | Stop. Report the exact errors. Do not overwrite or repair the register; the user decides (fix it, or ask for a reset in Step 8). |
| `NO_REGISTER` | New analysis: Step 3 with mode `new`. |
| `UNCHANGED` | Step 3 is skipped; go to Step 7. |
| `CHANGED` or `NO_STATE` | Reconciliation: Step 3 with mode `reconcile`. For `NO_STATE` the change report is "unknown" (an analysis state file is missing); treat every requirement as possibly changed. |

If `stray_state_found` is true with `NO_REGISTER`, an earlier analysis state exists without a register. Do not proceed silently: explain that gap IDs from that history must not be reused and ask (Step 8) whether to start over.

## Step 3 — Prepare a draft location

Create a temporary directory outside the project and the plugin:

```text
python -c "import tempfile; print(tempfile.mkdtemp(prefix='ba-gaps-'))"
```

The draft path is `<temp-dir>/gaps.draft.json`.

## Step 4 — Run the Gap Analysis Agent

Invoke the `sdlc-pipeline:gap-analysis-agent` agent. Its prompt must include:

- the plugin root absolute path;
- the absolute path of `atomic_requirements/atomic_requirements.json` (read only);
- the draft path and the mode (`new` or `reconcile`);
- for `reconcile`: the absolute path of `gaps/gaps.json` (read only), the `changes` object from `inspect` (or "unknown"), the highest gap number in use (`next_gap_id` minus one), and any answers the user has already given;
- the instruction to follow the gap-identification and gap-prioritisation skills and both rules files, never to make decisions, and to return its final report in its required format.

Handle the report:

- `INCOMPLETE` or `VALIDATOR: FAILED`: do not claim success. Re-invoke it with the specific problem, or tell the user what was not processed.
- `NEEDS_DECISION`: ask the user each listed question with AskUserQuestion (show the old gap and the new finding), then re-invoke the agent with the answers. Never guess a match.

Give every re-invocation (here or in Step 5) a new draft file name (`<temp-dir>/gaps.draft-2.json`, `draft-3.json`, …) instead of rewriting the same path; from then on "the draft path" means the newest draft.

## Step 5 — Independent validation

Do not rely on the agent's word. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-gap-register.py <draft path> --requirements <project root>/atomic_requirements/atomic_requirements.json
```

On failure, send the errors back to the agent and validate again. Read the draft and spot-check: exactly six properties per gap, every affected requirement carries its ID and description, no decisions on new gaps, nothing that reads as an assumed answer.

## Step 6 — Review reconciliation with the user (reconcile mode only)

Before anything is saved, show the user a concise change report in plain words: requirements added, changed and removed; gaps kept, updated, newly created (with IDs); and then the material items, each decided by the user with AskUserQuestion:

1. **Resolved gaps the agent left resolved** (`CONFIRM`): show the recorded decision and what changed. Ask: "Does this decision still address the changed requirement?" Options: keep resolved / reopen. If reopened, set that gap's `status` to `open` in the draft (decisions untouched) and re-validate. Remember the IDs the user kept resolved for `--confirmed`.
2. **Resolved gaps the agent reopened** (`REOPENED`): tell the user; no decision is lost.
3. **Gaps that no longer apply** (`RETIRE_CANDIDATES`): all their requirements were removed. Never delete one silently. Explain that keeping the register valid needs either (a) re-pointing the gap to a surviving requirement the user names, or (b) retiring it into `gaps/retired-gaps.json`, a separate history file that extends the agreed schema and therefore needs the user's explicit approval; the gap and its decisions are preserved there. Ask which, per gap. For (a) update the draft and re-validate; for (b) remember the ID and the user's reason for `--retire`.

Skip a category with nothing in it. Make no save before the user has answered everything.

## Step 7 — Persist safely

New analysis:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py save --project-root <project root> --draft <draft path> --mode new
```

Reconciliation:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py save --project-root <project root> --draft <draft path> --mode reconcile [--confirmed GAP-002,...] [--retire GAP-004 --approve-retirement --retire-reason "<reason>"]
```

Add `--approve-retirement` only if the user approved in Step 6.

Unchanged input (`UNCHANGED`): do not analyse. Tell the user the existing register is current, no duplicate gaps will be created and no decisions or statuses change. Run `regenerate-report` so `gap-analysis.html` is present and current.

The store validates the draft, refuses to overwrite an existing register or alter decisions, writes atomically, reads the file back, validates again, updates `gap-analysis-state.json` and regenerates the HTML. If it exits non-zero, show the `error` and `details`, say nothing was saved (the previous register is intact), and either correct the draft or stop. Exit code 3 means the register is saved but the report failed: say so and run `regenerate-report` once; if it still fails, report it and tell the user the JSON is safe.

## Step 8 — Destructive reset (only on request)

Only if the user explicitly asks to start over, or Step 2 requires it. Explain exactly what is lost (the gaps, every recorded decision, statuses, the analysis state, the retired-gap archive) and that the old files are backed up under `gaps/backup-<timestamp>/` first. Ask for explicit confirmation with AskUserQuestion. Only then run Steps 3–6 in `new` mode and save with `--mode reset --confirm-reset`.

## Step 9 — Verify

1. `python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-gap-register.py <project root>/gaps/gaps.json` must pass.
2. `gap-register-store.py inspect --project-root <project root>` must now report `UNCHANGED`.
3. Confirm `gaps/gap-analysis.html` exists.
4. `gap-register-store.py summary --project-root <project root>` gives the counts for the report.

## Step 10 — Execution summary

Use actual values only; counts come from `summary` and the agent's report, never from memory or example numbers.

```text
Gap analysis completed.

Atomic requirements analysed: <n>
Gaps identified: <n>

Priority distribution:
- Critical: <n>
- High: <n>
- Medium: <n>
- Low: <n>

Affected requirements: <n>
Duplicate gaps consolidated: <n>

Artifacts:
- gaps/gaps.json
- gaps/gap-analysis.html
- gaps/gap-analysis-state.json

Validation: Passed
```

For a reconciliation also list gaps kept, updated, reopened, new and retired. For an unchanged input say "Existing gap analysis is current; register reused." If there are no gaps, say that the register is empty and the report shows an empty state. Show the open / skipped / resolved counts, mention that the HTML report is read-only, and suggest `/sdlc-pipeline:ba-triage-gaps` as the next step.

If validation did not pass, a save failed, or the user cancelled, do not print "Gap analysis completed." Say exactly what was and was not done. Mention the notes from the agent that the user should know (consolidations, judgement calls).

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.