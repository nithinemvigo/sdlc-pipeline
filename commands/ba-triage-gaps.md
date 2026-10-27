---
description: Review open and skipped requirement gaps one at a time and record business decisions (BA Requirements, Phase 2)
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Triage Gaps (Phase 2)

You run an interactive triage session over the gap register created by `/sdlc-pipeline:ba-analyse-gaps`. Detailed behaviour lives in the plugin's rules and skill; follow them.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>`.

Do not re-run gap analysis. Do not change the atomic requirements or any source document. Do not edit `gaps/gaps.json` or the HTML by hand: every read and write goes through `scripts/gap-register-store.py`. Use whichever of `python`, `python3`, `py` works; if none does, tell the user Python 3 is required and ask before doing anything else.

## Step 1 — Load the standards

Read in full and follow:

- `${CLAUDE_PLUGIN_ROOT}/rules/gap-triage-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/gap-triage/SKILL.md`

If a path still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/gap-triage-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`) and use that.

## Step 2 — Load and validate the register

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py list --project-root <project root>
```

- Exit 1 with "No gap register exists": tell the user to run `/sdlc-pipeline:ba-analyse-gaps` first, and stop.
- Exit 1 for an invalid register: report the exact `details`, change nothing, and stop.
- Exit 1 because the atomic requirements changed (or the analysis state is missing): tell the user to run `/sdlc-pipeline:ba-analyse-gaps` to reconcile before triage, and stop.
- Success: the output holds `queue` (open and skipped gaps already ordered Critical to Low, then by gap number), `eligible_count` and `counts`.

If `eligible_count` is 0, say that no open or skipped gaps remain, show the counts, give the paths of the register and report, and stop.

Create a temporary directory outside the project and the plugin for decision text files:

```text
python -c "import tempfile; print(tempfile.mkdtemp(prefix='ba-triage-'))"
```

## Step 3 — Triage loop

Open with one short line: how many gaps are eligible and how many of those were skipped earlier. Then go through the queue in the order returned, one gap at a time, exactly as the `gap-triage` skill describes: present the gap with its progress, ask what the user wants, capture and confirm any decision, save immediately, and continue.

Supported actions: provide a decision; skip this gap; skip all remaining gaps; reopen a resolved gap; revise a recorded decision (only when asked); stop.

Hard rules (details in `gap-triage-rules.md`):

- A gap becomes resolved only after the user confirms the captured decision.
- Skipping never adds a decision, deletes or downgrades the gap, or counts as resolved.
- Skip-all and stop write nothing further; confirmed changes already saved stay.
- After every save, read the JSON result. Do not report success unless `ok` is true; for exit code 3 say the register saved but the report needs `regenerate-report`.
- Present each gap at most once per session. Do not make business decisions for the user.

## Step 4 — Session summary

Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/gap-register-store.py summary --project-root <project root>
```

Report actual values only:

```text
Gap triage session summary.

Gaps presented: <n>
Resolved in this session: <n>
Skipped in this session: <n>

Register now:
- Open: <n>
- Skipped: <n>
- Resolved (total): <n>

Register: gaps/gaps.json
Report:   gaps/gap-analysis.html
```

State clearly that skipped gaps are still unresolved and will return the next time `/sdlc-pipeline:ba-triage-gaps` runs. If the HTML report could not be regenerated at any point, say so and say how to fix it. Remind the user that the report is read-only and that decisions are only recorded through this command.

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.