---
description: Open the local run dashboard, then run /pipeline-all, /pipeline or /pipeline-parallel unchanged. The dashboard is read-only and shows stages, agents, token usage, questions and each task's changes live.
argument-hint: [--flow pipeline-all|pipeline|pipeline-parallel] <request, as for the chosen flow>
---

# /pipeline-ui — dashboard + pipeline

You are the **orchestrator**. This command puts a dashboard in front of an existing flow and
nothing else. After Step 4 you follow the chosen flow's own instructions exactly; this file adds
no stages, rules or questions after the hand-off.

Arguments: $ARGUMENTS

## Step 1 — Start the dashboard (one Bash call)

If the arguments contain `--flow <name>`, remember `<name>` and remove `--flow <name>`; what is
left is `<request>`.

Run exactly this one command:

```bash
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then python "${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-ui.py" start --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" --open; else echo '{"error":"needs-claude-code"}'; fi
```

It prints one JSON line and returns at once; the dashboard keeps running in the background.

## Step 2 — Tell the client (one line, in the same turn as Step 3)

- `{"url": ...}` → `Dashboard: <url>`, adding ` (already running)` when `reused` is true.
- `{"error": "needs-claude-code"}` → `The dashboard needs Claude Code; continuing without it.`
- any other `{"error": ...}` → `Dashboard not started: <error> — continuing without it.`

A failed start never stops the run.

## Step 3 — Choose the flow

If `--flow` named `pipeline-all`, `pipeline` or `pipeline-parallel`, use it. If it named
anything else, say `Unknown flow "<name>".` and ask as below. Otherwise ask once with
`AskUserQuestion` — question "Which flow should run?", header "Flow":

- `pipeline-all (Recommended)` — New features, requirements first: requirements document, BA analysis, plan, build, reviews, acceptance gate, PR.
- `pipeline` — Features or bugs, built one task at a time.
- `pipeline-parallel` — Features or bugs, independent tasks built in parallel waves.

Drop ` (Recommended)` from the answer to get `<flow>`.

## Step 4 — Hand off

Invoke the Skill tool with skill `sdlc-pipeline:<flow>` and args `<request>` exactly as given
(empty if there is none). From then on, follow that skill's instructions exactly, as if the
client had typed `/sdlc-pipeline:<flow> <request>`.

## Stopping the dashboard

It stops by itself after two hours with nobody viewing it. Only if the client asks to stop it
now, run:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/pipeline-ui.py" stop --project "$(git rev-parse --show-toplevel)"
```
