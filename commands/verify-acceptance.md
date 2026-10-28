---
description: Check every acceptance criterion of the BA stories (or of the plan's task files) against the current branch and write an evidence report. Report-only - no fixes, no commit.
argument-hint: <requirements file> [--plan <plan dir>]
---

# /verify-acceptance — Acceptance check (report-only)

You are the **orchestrator**. You never write production code. You build the criteria
checklist, dispatch one verifier, render the report and print the result. No fix loop, no
client question, no commit.

Arguments: $ARGUMENTS

## Step 1 — Preflight and paths

One Bash call:

```bash
echo "PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-unset}}"
echo "REPO_ROOT=$(git rev-parse --show-toplevel)"
echo "BRANCH=$(git branch --show-current)"
B=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
[ -n "$B" ] || { git show-ref --verify -q refs/heads/main 2>/dev/null && B=main || B=master; }
echo "BASE_BRANCH=$B"
```

Record `<PLUGIN_ROOT>`, `<repo root>`, `<branch>` and `<base branch>`. `PLUGIN_ROOT=unset` →
stop: "Plugin root not found; run this command from the installed plugin."

Parse the arguments: `<REQUIREMENTS>` (first path) and optional `--plan <plan dir>`.

`<artifact root>` = `<directory of the REQUIREMENTS file>/ba/<its stem without .requirements>/`
(e.g. `docs/features/emv/ba/02-campaigns/`); `<absolute artifact root>` =
`<repo root>/<artifact root>`. `<absolute REQUIREMENTS path>` = `<repo root>/<REQUIREMENTS>`
(`<REQUIREMENTS>` unchanged when already absolute); `<absolute plan dir>` = the `--plan` value
resolved the same way. The scripts and the verifier always get absolute paths.

Decide the mode with one Bash check, `[ -f <absolute artifact root>/stories/detailed_stories.md ]`:

- **Exists (BA mode)** → `<acceptance dir>` = `<absolute artifact root>/acceptance`.
- **Missing and `--plan` given (plan mode)** → `<acceptance dir>` = `<absolute plan dir>/acceptance`.
- **Missing and no `--plan`** → stop with one line: `Usage: /sdlc-pipeline:verify-acceptance
  <requirements file> [--plan <plan dir>] — no BA stories found, so --plan is required.`

## Step 2 — Checklist

BA mode, one Bash call (export, then build; stop at the first non-zero exit):

```bash
python <PLUGIN_ROOT>/scripts/sync-development-stories.py export --project-root <absolute artifact root> --target <absolute REQUIREMENTS path> --draft-out <absolute artifact root>/.ba-requirements/stories-export.json \
&& python <PLUGIN_ROOT>/scripts/acceptance-checklist.py build --export <absolute artifact root>/.ba-requirements/stories-export.json --requirements <absolute REQUIREMENTS path> --out <acceptance dir>/checklist.json
```

Plan mode, one Bash call:

```bash
python <PLUGIN_ROOT>/scripts/acceptance-checklist.py build --tasks <absolute plan dir> --out <acceptance dir>/checklist.json
```

Exit 0 → ignore the stdout (the export prints the whole draft). Any non-zero exit (exit 2 =
invalid input or no criteria) → show the output and stop. Agents
read the stories from the export JSON only, never from `detailed_stories.md`.

## Step 3 — Verify

Dispatch `sdlc-pipeline:acceptance-verifier` (Sonnet) with: checklist path
`<acceptance dir>/checklist.json`, verdicts output path `<acceptance dir>/verdicts.json`,
repo root, branch, base branch, plan directory (`<absolute plan dir>`, or `none`), and "Stage 4 test
summary and Stage 4.5 QA findings: not available (standalone run)". No re-check IDs.

- `Status: BLOCKED` → show its reason and stop. Do not guess verdicts.
- `Status: DONE` → continue.

## Step 4 — Report

One Bash call:

```bash
python <PLUGIN_ROOT>/scripts/acceptance-checklist.py render --checklist <acceptance dir>/checklist.json --verdicts <acceptance dir>/verdicts.json --out-dir <acceptance dir>
```

Exit 2 → show its output and stop. Exit 0 or 1 → read the JSON it prints (`total`, counts per
status, `open`, `report_md`) and print:

- the summary line: `X/Y met · N follow-ups · M open` (X = `met`, Y = `total`,
  N = `accepted_followup`, M = `not_met` + `cannot_verify`);
- the report path (`report_md`);
- when M > 0, the open IDs with their status (`not_met`, `cannot_verify`).

Then stop. Nothing is fixed, asked or committed — the files under `<acceptance dir>` stay
uncommitted for the client to review.
