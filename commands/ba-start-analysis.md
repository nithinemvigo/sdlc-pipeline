---
description: Analyse Markdown requirements and save validated atomic requirements as JSON (BA Requirements, Phase 1)
allowed-tools: Read, Glob, Grep, Agent, AskUserQuestion, Bash(python:*), Bash(python3:*), Bash(py:*)
---

# BA Requirements — Start Analysis (Phase 1)

You orchestrate this command. Detailed methodology lives in the plugin's agent, skills and rules; follow them rather than improvising.

Plugin root: `${CLAUDE_PLUGIN_ROOT}`
Artifact root: the `--artifact-root` given in the arguments, otherwise the current working directory of this session. Every `<project root>` below means the artifact root, and is passed to the scripts as `--project-root <artifact root>` (`<project-root>` in rules and skills means the same).

This phase only analyses requirements and decomposes them into atomic requirements. Do not perform gap analysis, write user stories, integrate with Jira, enrich requirements, or modify any source document.

## Step 1 — Ask for the source (always first)

Your first message must be this question, and nothing else happens before the answer. Stop and wait for the reply.

> Where does your requirement document reside? You can provide a folder name, directory path, or individual filename.

## Step 2 — Load the standards

After the user replies, read these files in full and follow them for the rest of the command:

- `${CLAUDE_PLUGIN_ROOT}/rules/atomic-requirement-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/requirement-id-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/rules/artifact-management-rules.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/requirement-source-discovery/SKILL.md`

If a path above still contains the literal text `${CLAUDE_PLUGIN_ROOT}`, find the plugin directory by searching for `rules/atomic-requirement-rules.md` under the directory that contains this plugin's `.claude-plugin/plugin.json` (name `sdlc-pipeline`) and use that.

## Step 3 — Resolve and confirm the source

Apply the `requirement-source-discovery` skill:

- Resolve the answer to a file or directory; Markdown (`.md`) only.
- Invalid path: ask for a valid one. Several matches: list them and ask the user to choose. Never choose silently.
- Non-Markdown file: explain Phase 1 supports only `.md` and ask for a Markdown source.
- Directory: discover `.md` files recursively, excluding hidden and generated directories and `atomic_requirements/`. If more than one file remains, show the list (and a count of non-Markdown files excluded) and ask the user to confirm the source set before analysis.
- Empty directory, empty file or unreadable file: tell the user and ask for another source or stop.
- Source outside the project root: ask for confirmation before reading. In pipeline mode (the master run command called with `--requirements`), the given requirements file is already confirmed — do not ask.

Use AskUserQuestion for choices between candidates. Proceed only with a confirmed list of absolute `.md` paths.

## Step 4 — Prepare a draft location

Create a temporary directory outside the project and the plugin, using whichever of `python`, `python3`, `py` works:

```text
python -c "import tempfile; print(tempfile.mkdtemp(prefix='ba-requirements-'))"
```

The draft path is `<temp-dir>/atomic_requirements.draft.json`. If no Python is available, tell the user that Python 3 is required and ask before installing or doing anything else.

## Step 5 — Run the Requirement Analyst

Invoke the `sdlc-pipeline:requirement-analyst` agent. Its prompt must include:

- the plugin root absolute path;
- the confirmed absolute source paths;
- the draft path;
- the instruction to follow the source-discovery, decomposition and quality-validation skills and all three rules files, and to return its final report in its required format.

If the agent reports `INCOMPLETE`, a `PARTIAL`, `EMPTY` or `UNREADABLE` source, or a failed validator, do not claim full completion. Either have it correct the problem (re-invoke with the specific issue) or tell the user what was not processed and ask how to proceed.

Give every re-invocation (here or in Step 6) a new draft file name (`<temp-dir>/atomic_requirements.draft-2.json`, `draft-3.json`, …) instead of rewriting the same path; from then on "the draft path" means the newest draft.

## Step 6 — Independent validation

Do not rely on the agent's word. Run the validator yourself on the draft:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/validate-atomic-requirements.py <draft path>
```

On failure, send the errors back to the analyst to correct, then validate again. Read the draft and spot-check that every object has exactly `requirement_id`, `title` and `description`, with no wrapper or extra metadata.

## Step 7 — Persist safely

Output file: `<project-root>/atomic_requirements/atomic_requirements.json`.

1. Check whether it exists.
2. If it exists, do not overwrite. Explain that it exists, that IDs will be freshly assigned and may differ from the previous file, and ask with AskUserQuestion: replace it, save under a different file name in `atomic_requirements/`, or cancel. Act only on the answer.
3. Create `atomic_requirements/` if needed, then copy the validated draft to the chosen path (shell copy, so the saved content is exactly what was validated).
4. Read the saved file back, run the validator on it, and compare it with the draft (for example `cmp`). Report any mismatch as a failure.
5. Never write inside the plugin directory or to a source document.

## Step 8 — Execution summary

Report actual values only. On full success:

```text
BA REQUIREMENT ANALYSIS — COMPLETED

Source:
<source path(s) as confirmed>

Analysis:
Source files analysed: <n>
Atomic requirements generated: <n>
Validation status: PASSED

Output:
<absolute path to the saved file>

Original requirement documents:
UNCHANGED

Status:
Phase 1 completed successfully.
```

If any source was not fully read, a file was excluded or failed, validation did not pass, or the user cancelled, do not print "COMPLETED". Use "BA REQUIREMENT ANALYSIS — INCOMPLETE" (or "CANCELLED"), say exactly what was and was not processed, and list non-Markdown files that were excluded. Mention notes from the analyst that the user should know (duplicates consolidated, ambiguities kept as written, content skipped).

## Pipeline checkpoint (final step, non-fatal)

If `<project root>/.ba-requirements/pipeline-state.json` exists, an unfinished pipeline run must not keep relying on results this command may have just changed. Run:

```text
python ${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-state.py refresh --project-root <project root>
```

It re-validates the recorded run and resets any operation whose inputs or outputs changed, together with the operations after it, so the next run offers to continue from there. It never changes a phase artifact. If `invalidated` is not empty, say so in one line. A missing or unusable checkpoint, or a failure of this call, is not an error for this command: ignore it. Never edit the checkpoint by hand.