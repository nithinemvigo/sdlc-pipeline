---
description: Detect changes made outside the plugin to the development stories or their sources and reconcile them safely (BA Requirements, Phase 3)
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Sync Stories (Phase 3)

You detect and reconcile changes made outside the plugin. You never silently replace a manual change: anything that could overwrite or discard the user's edits is put to the user first.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Project root: the current working directory of this session.

Do not rewrite stories, decide gaps or edit the requirements. This command records accepted manual edits in the story state (the document is not touched) and refreshes the report. Every read and write goes through `scripts/sync-development-stories.py`. Use whichever of `python`, `python3`, `py` works.

## Step 1 — Load the standards

Read `${CLAUDE_PLUGIN_ROOT}/rules/story-management-rules.md` in full and follow it. If the path still contains `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/story-management-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`).

## Step 2 — Inspect

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py inspect --project-root <project root>
```

Handle `status`: `INPUT_MISSING`/`INPUT_INVALID`/`INPUT_EMPTY` → stop and point to Phase 1. `TARGET_REQUIRED` → no target is recorded; ask the user which Markdown document holds the stories and inspect again with `--target`. `DOCUMENT_MISSING` → ask the user to locate the original document (never create a replacement), then use `--target` and tell them the recorded target is changing. `SECTION_AMBIGUOUS` → show `ambiguity`; the user must fix the document. `section.state` `absent` → nothing to sync; suggest `/sdlc-pipeline:ba-generate-stories`.

Keep `target.source_sha256`.

## Step 3 — Present what was found

Report, in plain language, only what the output shows:

- **Section problems** (`section.problems`): the section breaks the story contract (extra fields, invalid or duplicate IDs, stray text). List them. These must be fixed in the document before anything can be reconciled; offer no automatic repair. Stop after listing them.
- **Edited stories** (`manual_changes.edited`, with `edited_details`): which fields changed (summary, description, criteria added, how many criteria removed).
- **Added stories** (`added`), **deleted stories** (`removed`), **ID changes** (`id_changes`: a removed and an added story with identical content).
- **Edits outside the section** (`outside_section_modified`): preserved, never overwritten; mention them.
- **Formatting-only changes** (`formatting_only`): no content differs.
- **Atomic requirement changes** (`requirement_changes`): added, changed, removed requirements and `affected_story_ids`. Sync does not rewrite stories for these; recommend `/sdlc-pipeline:ba-generate-stories`, which handles them without deleting anything silently.
- **Gap register changes** (`gap_changes`, `pending_decisions`): recommend `/sdlc-pipeline:ba-enrich-stories`.
- **State missing or invalid** (`state.status`): if `recoverable_from_document` is true the state can be rebuilt from the document (Step 4); otherwise explain what must be fixed.

If nothing needs reconciling (`section_modified` false, no differences, state valid), say the stories are in sync and stop. Do not modify anything.

## Step 4 — Decide how to proceed

Ask with AskUserQuestion for each kind of change that touches user edits or story identity:

- Edited, added or reformatted stories: **accept as the new baseline** (record them as they are) or **leave for now** (change nothing).
- Deleted stories: **confirm deletion** — their IDs are retired and never reused — or **leave for now**. Restoring a deleted story is done by `/sdlc-pipeline:ba-generate-stories` with the user's consent.
- Renamed stories (`id_changes`): **accept the rename** (the mapping moves to the new ID, the old ID is retired) or leave for now.
- New stories (added, or a state rebuilt from the document): each needs its source requirement IDs. Work them out from the story text and the atomic requirements, state your reasoning, and ask the user to confirm any you are not confident about. Never guess silently. Write the confirmed mapping with the Write tool to a temporary file outside the project and the plugin, as `{"US-020": {"source_requirement_ids": ["REQ-006"]}}`.

## Step 5 — Record the accepted changes

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py accept --project-root <project root> [--target <doc>] --expected-source-sha256 <sha> [--mappings <file>] [--rename OLD=NEW,...] [--retire US-004,...]
```

If it is refused, read `error`, `details`, `deleted` and `needs_mapping`, resolve with the user and retry. The command never edits the document; it updates the state and regenerates the report.

Read the JSON; do not report success unless `ok` is true. Exit code `3` means the state was saved but the report is stale (`/sdlc-pipeline:ba-generate-report`).

## Step 6 — Verify and summarise

Run `inspect` again to confirm that `manual_changes.section_modified` is false and nothing is left unreconciled, then report real values:

```text
Story synchronisation completed.

Changes detected: <edited n, added n, deleted n, renamed n, outside-section edits yes/no>
Accepted into the story state: <list>
Left unreconciled at your request: <list or none>
Document modified: no (the document was not touched)

Report: report/phase3-report.html (<generated | stale>)
```

Mention requirement or gap-register changes that still need `/sdlc-pipeline:ba-generate-stories` or `/sdlc-pipeline:ba-enrich-stories`.

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.