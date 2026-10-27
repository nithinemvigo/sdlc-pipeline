---
description: Enrich existing development stories using decisions recorded in resolved gaps (BA Requirements, Phase 3)
allowed-tools: Read, Write, Glob, Grep, Agent, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Enrich Stories (Phase 3)

You orchestrate this command. Methodology lives in the plugin's agent, skills and rules; follow them rather than improvising.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same).

Enrichment is incremental: only the stories a newly resolved or revised decision materially affects change. Never regenerate all stories, never decide a gap, never treat an open or skipped gap as a decision. Do not hand-edit the document, the state or the report; everything goes through `scripts/sync-development-stories.py`. Use whichever of `python`, `python3`, `py` works.

## Step 1 — Load the standards

Read in full and follow:

- `${CLAUDE_PLUGIN_ROOT}/rules/story-writing-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/acceptance-criteria-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/story-management-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/story-enrichment/SKILL.md`

If a path still contains `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/story-writing-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`).

## Step 2 — Inspect

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py inspect --project-root <project root>
```

Stop, with an explanation and no change, when:

- `status` is not `OK` (missing or invalid atomic requirements → Phase 1; no target recorded or `section.state` `absent` → run `/sdlc-pipeline:ba-generate-stories` first; document missing → ask the user to locate it; `SECTION_AMBIGUOUS` → show `ambiguity`).
- `state.status` is not `VALID`: the story mappings are missing or unusable. Suggest `/sdlc-pipeline:ba-sync-stories` to rebuild them from the document.
- `section.problems` is not empty: the section needs `/sdlc-pipeline:ba-sync-stories` first.
- `gaps.status` is `MISSING`: there are no decisions to apply. `INVALID`: show `gaps.errors` and ask the user to correct the register (enrichment needs valid gap data; do not offer to proceed without it).

If `manual_changes` shows edits made by hand, tell the user: those stories are left untouched unless a decision requires a change, and then the change is proposed to them first.

Resolved gaps with no recorded decision make the register invalid and are rejected by the script; do not enrich from them.

## Step 3 — Reopened gaps and other gap changes

If `gap_changes.reopened` is not empty, a gap whose decision was incorporated is no longer resolved. Do not remove anything yourself. For each such gap ask with AskUserQuestion what to do with the criteria it produced: **retain**, **revise**, or **remove**. Retain needs no story change. For revise or remove, the agent proposes exactly which criteria; show them (before and after) and get confirmation before anything is written.

`gap_changes.newly_skipped`, `new_gaps` and `removed_gaps` are informational: mention them; they do not change stories.

## Step 4 — Nothing pending

If `pending_decisions` is empty and no reopened gap needs a change:

- Say that no enrichment is required and the stories were not modified.
- If the gap register changed since the last sync (`gap_changes` lists anything, or its hash differs), refresh the state and the report without changing story content: run `export --draft-out <temp>/draft.json`, then `apply --draft <temp>/draft.json --expected-source-sha256 <sha> --acknowledge-changes` (only after the user has seen and settled any reopened gap), so the snapshot and the report are current.
- Otherwise run `regenerate-report`. Stop.

## Step 5 — Prepare the work

Create a temporary directory outside the project and the plugin (`python -c "import tempfile; print(tempfile.mkdtemp(prefix='ba-stories-'))"`). Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py export --project-root <project root> --draft-out <temp>/existing.json
```

Save the `pending_decisions` from `inspect` to `<temp>/pending.json` (Write tool) and note the reopened-gap choices from Step 3. Keep `source_sha256` from the export.

## Step 6 — Run the Story Generation Agent in `enrich` mode

Invoke `sdlc-pipeline:story-generation-agent` with: the plugin root, the artifact root (passed as `--project-root` to every script), mode `enrich`, the atomic requirements path, the gap register path, the draft path `<temp>/draft.json`, the export path, the pending file, the reopened-gap choices, and the instruction to follow the story-enrichment skill and return its final report format.

- `NEW_STORY_PROPOSALS`: put each to the user with AskUserQuestion (the proposed story and why it does not belong in an existing story). Re-invoke with the answers; a story is only added when the user agrees.
- `NEEDS_DECISION`: ask, then re-invoke.
- `INCOMPLETE` or failed validator: re-invoke with the specific problem.

Give every re-invocation (here or in Step 7) a new draft file name (`<temp>/draft-2.json`, `draft-3.json`, …) instead of rewriting the same path; from then on `<temp>/draft.json` in the steps below means the newest draft.

## Step 7 — Independent validation

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-development-stories.py <temp>/draft.json --project-root <project root>
```

Read the draft against the export. Check: only stories affected by a decision changed; IDs unchanged; unrelated criteria untouched; no duplicate criteria; every pending decision appears in `decisions_reviewed` with an honest outcome; no open or skipped gap used as a decision; the decision text is reflected accurately, with the user's values.

## Step 8 — Preview, then write

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py apply --project-root <project root> --draft <temp>/draft.json --expected-source-sha256 <sha> --dry-run
```

Handle `conflicts` and `unacknowledged_changes` exactly as in `/sdlc-pipeline:ba-generate-stories` Step 7: show them, ask per story, never overwrite a manually edited story or remove a story without consent. Show the user which stories will change, then run it again without `--dry-run`.

## Step 9 — Check the result and summarise

Read the JSON; do not report success unless `ok` is true (exit codes: `1` nothing changed; `2` I/O failure, nothing changed; `3` saved, report stale → `/sdlc-pipeline:ba-generate-report`; `4` document saved but state not → run `inspect` then `accept`). Use `summary` for validation status.

```text
Story enrichment completed.

Resolved gaps examined: <resolved gaps in the register, or the pending ones examined>
New decisions incorporated: <decisions_reviewed with outcome incorporated>
Decisions needing no story change: <no_change_required count>
Stories enriched: <apply.updated count>
Stories unchanged: <apply.unchanged count>
New stories proposed: <count proposed>   (added: <count approved and created>)

Updated stories:
- US-001 — <what changed, e.g. account lockout criteria added>

Document updated:
- <target path>   (backup: <apply.backup>)

Report: report/phase3-report.html (<generated | stale>)

Validation: <Passed | Failed>
```

Count a decision as incorporated only when a story reflects it, or the agent explicitly determined that no story change is required. Counts come from the scripts' JSON and the agent's report, never from memory.

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.