---
description: Generate development stories from the atomic requirements and write them into the original requirements document (BA Requirements, Phase 3)
allowed-tools: Read, Write, Glob, Grep, Agent, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Generate Stories (Phase 3)

You orchestrate this command. Methodology lives in the plugin's agent, skills and rules; follow them rather than improvising.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same).

Stories are generated from the requirements known now, even when gaps are open or skipped. Never decide an open gap. Do not touch the atomic requirements or the gap register. Do not hand-edit the requirements document, `stories/story-generation-state.json` or `report/phase3-report.html`: every read and write goes through `scripts/sync-development-stories.py`. Use whichever of `python`, `python3`, `py` works; if none does, tell the user Python 3 is required and ask before doing anything else.

## Step 1 — Load the standards

Read in full and follow:

- `${CLAUDE_PLUGIN_ROOT}/rules/story-writing-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/acceptance-criteria-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/story-management-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/story-generation/SKILL.md`

If a path still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/story-writing-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`) and use that.

## Step 2 — Inspect the project

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py inspect --project-root <project root>
```

Act on `status`:

| status | Action |
|---|---|
| `INPUT_MISSING` | Stop. Say `atomic_requirements/atomic_requirements.json` was not found and Phase 1 (`/sdlc-pipeline:ba-start-analysis`) must be completed first. |
| `INPUT_INVALID` | Stop. Report `errors` and explain how to correct the file or re-run Phase 1. |
| `INPUT_EMPTY` | Stop. There are no requirements to write stories for. |
| `TARGET_REQUIRED` | Choose the target document (Step 3), then inspect again with `--target <path>`. |
| `TARGET_NOT_MARKDOWN` | The target must be a `.md` file. Ask for another. |
| `DOCUMENT_MISSING` | Ask the user to locate the original requirements document. Never create a replacement. |
| `DOCUMENT_UNREADABLE` | Report `errors` and ask for another document or a fix. |
| `SECTION_AMBIGUOUS` | Stop. Show `ambiguity` and ask the user to fix the document. Write nothing. |
| `OK` | Continue. |

Then check:

- `gaps.status`: `MISSING` — continue, and say that gap traceability is unavailable. `INVALID` — show `gaps.errors` and ask with AskUserQuestion: the user corrects the register (stop), or explicitly proceeds without gap context (add `--ignore-gaps` to every script call below and never claim gap relationships were checked).
- `section.problems` not empty: the managed section was edited into an invalid shape. Show the problems, tell the user to fix them in the document or run `/sdlc-pipeline:ba-sync-stories`, and stop.
- `manual_changes`: if stories were edited, added or deleted by hand, tell the user they will be preserved and that anything the new draft would change in them is asked about first.
- `state.status` `INVALID`: say the story state is unusable. Existing stories will not be overwritten without your consent.

Keep `target.source_sha256` from this output.

## Step 3 — Choose the target document (when `TARGET_REQUIRED`)

Phase 1 does not record which files it analysed, so ask once:

> Which Markdown requirements document should hold the Development Stories section? Give the file, or the folder you analysed.

- A file: confirm it exists and is `.md`.
- A folder: list its `.md` files (recursive; skip hidden and generated folders and `atomic_requirements/`, `gaps/`, `stories/`, `report/`). If more than one, ask the user to select the single primary document with AskUserQuestion. Never add the section to several files.
- A path outside the project root: ask for confirmation first. In pipeline mode (the master run command called with `--requirements`), the given requirements file is already confirmed — do not ask.

Stories are traced to requirement IDs, so requirements from all analysed files stay covered by the one consolidated section.

## Step 4 — Decide what there is to do

- **No section yet** (`section.state` `absent`): mode `generate`.
- **Section exists:** mode `reconcile`. Run `export --project-root <root> --draft-out <temp>/existing.json` (add `--target` if needed). If `uncovered_requirements` is empty, `requirement_changes` shows no added, changed or removed requirements, and no story is flagged, report that the stories already cover the requirements and nothing was changed, run `regenerate-report` so the report is current, and stop. Do not generate a second section or new IDs for existing stories.
- If `requirement_changes` lists removed or changed requirements, show them with `affected_story_ids` to the user and say what the draft will do about each; a story is never deleted for a removed requirement without the user's approval.

Create a temporary directory outside the project and the plugin:

```text
python -c "import tempfile; print(tempfile.mkdtemp(prefix='ba-stories-'))"
```

## Step 5 — Run the Story Generation Agent

Invoke the `sdlc-pipeline:story-generation-agent` agent. Its prompt must include: the plugin root, the artifact root (passed as `--project-root` to every script), the mode, the atomic requirements path, the gap register path (or "none/ignored"), the draft path `<temp>/draft.json`, for `reconcile` the export path and the relevant `inspect` findings (added, changed, removed requirements; uncovered requirements; stories edited by hand), and the instruction to follow its files and return its final report format.

If it reports `INCOMPLETE` or a failed validator, re-invoke it with the specific problem or tell the user what is missing. If it reports `NEEDS_DECISION` or `NEW_STORY_PROPOSALS`, put each question to the user with AskUserQuestion, then re-invoke with the answers.

Give every re-invocation (here or in Step 6) a new draft file name (`<temp>/draft-2.json`, `draft-3.json`, …) instead of rewriting the same path; from then on `<temp>/draft.json` in the steps below means the newest draft.

## Step 6 — Independent validation

Do not rely on the agent's word:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-development-stories.py <temp>/draft.json --project-root <project root>
```

On failure send the errors back to the agent. Then read the draft and spot-check: coherent stories (not one per requirement by rote), testable criteria, no open or skipped gap turned into a decision, every confirmed decision accurately reflected, no metadata in any story.

## Step 7 — Preview, then write

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py apply --project-root <project root> --draft <temp>/draft.json [--target <doc>] --expected-source-sha256 <sha from inspect> --dry-run
```

Read the JSON. If it is refused with `conflicts`, show each (current vs proposed content) and ask the user, per story, whether to keep their version, overwrite it, restore it (deleted by hand) or allow its removal. Translate the answers into `--overwrite`, `--restore`, `--allow-remove`; if the user keeps their version, change the draft instead. If it asks for `--acknowledge-changes`, show `unacknowledged_changes` to the user first and pass the flag only after they have seen them and the draft deals with them. Re-run the dry run until it succeeds, show the user the plan (created, updated, unchanged, removed), then run the same command without `--dry-run`.

## Step 8 — Check the result

Read the JSON. Do not report success unless `ok` is true. Exit code `1`: nothing changed, explain. `2`: nothing changed, explain the I/O failure. `3`: stories and state saved, the HTML report is stale — say so and point to `/sdlc-pipeline:ba-generate-report`. `4`: the document was saved and verified but the state was not — do not call this complete; run `inspect` then `accept` (see `/sdlc-pipeline:ba-sync-stories`).

Run `summary --project-root <root>` for the real counts.

## Step 9 — Execution summary

Report actual values only:

```text
Development story generation completed.

Atomic requirements analysed: <summary.requirements.analysed>
Stories generated: <created count from apply>   (stories in document: <summary.stories>)
Requirements covered: <summary.requirements.covered>
Requirements requiring review: <count of summary.requirements.not_covered + uncovered_unexplained>

Gap traceability:
- Open gaps referenced: <summary.gaps.referenced.open>
- Skipped gaps referenced: <summary.gaps.referenced.skipped>
- Resolved gaps referenced: <summary.gaps.referenced.resolved>
(or: Gap register not available — gap traceability was not checked.)

Document updated:
- <target path>   (backup: <apply.backup>)

Report: report/phase3-report.html (<generated | stale: run /sdlc-pipeline:ba-generate-report>)

Validation: <Passed | Failed>
```

Explain every requirement listed as not covered. If any resolved decision is still pending (`pending_decisions` in a fresh `inspect`), say so and suggest `/sdlc-pipeline:ba-enrich-stories`. Remind the user that open and skipped gaps are still unresolved, that stories contain only what the requirements and resolved decisions support, and that the report is read-only.

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.