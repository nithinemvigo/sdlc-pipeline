---
description: Rebuild the Phase 3 HTML report from the current stories, gaps and decisions without changing any story (BA Requirements, Phase 3)
allowed-tools: Read, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Generate Report (Phase 3)

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same).

Rebuild `report/phase3-report.html` only. This command never rewrites the requirements document, renumbers or changes stories, edits `stories/story-generation-state.json`, or changes the gap register or any recorded decision. Use whichever of `python`, `python3`, `py` works; if none does, tell the user Python 3 is required and ask before doing anything else.

If a path below still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `scripts/generate-phase3-report.py` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`).

## Step 1 — Regenerate

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/sync-development-stories.py regenerate-report --project-root <project root>
```

The report is built from the consolidated `stories/detailed_stories.md` (the full functional and non-functional stories, not the ultra-lean entries in the requirements document), from `gaps/gaps.json` and from the story state (traceability, hashes and synchronisation). The Development Stories section of the recorded target document is read only to check that each story has a matching entry. It is written to a temporary file, replaced, read back and checked. A failed run leaves the previous report untouched.

## Step 2 — Check the result

Read the JSON. Do not report success unless `ok` is true and `report.generated` is true.

- Exit `1`: the report cannot be built. Typical causes: no story state yet (run `/sdlc-pipeline:ba-generate-stories`), the recorded document is missing or its section boundary is ambiguous (see `/sdlc-pipeline:ba-sync-stories`). Say exactly which, and that any previous report is out of date.
- Exit `2`: a file could not be read or written. Say what failed and that the previous report, if any, is stale.

## Step 3 — Summarise

Run `summary --project-root <project root>` for the figures, and report real values only:

```text
Phase 3 report regenerated.

Report: report/phase3-report.html
Stories: <summary.stories>
Gaps: <open / skipped / resolved from summary.gaps.register_counts, or "gap data unavailable">
Story validation: <Passed | Failed>
Synchronisation: <In sync | Edited since the last sync: run /sdlc-pipeline:ba-sync-stories>

Stories, gaps and decisions were not changed.
```

If `summary` says a document or detailed story was edited since the last sync, point out that the report shows the detailed stories as they are now and is flagged "Out of sync". If a story has no detailed story, the report says so for that story instead of showing the shortened document text. If the report is missing sections because gap data is unavailable, say so rather than implying a complete view. Remind the user the report is a read-only view: detailed stories are edited in `stories/detailed_stories.md`, the ultra-lean stories in the requirements document, and decisions are recorded through `/sdlc-pipeline:ba-triage-gaps`.

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.