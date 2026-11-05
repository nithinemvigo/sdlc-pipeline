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

Run exactly this script, as one Bash call:

```bash
if [ "${CLAUDECODE:-}" != "1" ]; then echo '{"error":"needs-claude-code"}'; else
  PY=""; for c in python3 python; do if "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then PY="$c"; break; fi; done
  R="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
  if [ -z "$R" ] && [ -n "$PY" ]; then R="$("$PY" -I -c '
import glob, json, os, re, sys
home = sys.argv[1]
def version(text): return [int(n) for n in re.findall(r"[0-9]+", str(text))]
def usable(path): return isinstance(path, str) and os.path.isfile(os.path.join(path, "scripts", "pipeline-ui.py"))
found = []
try:  # the installed version first
    with open(os.path.join(home, "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
        plugins = json.load(fh)["plugins"]
    found = [(version(e.get("version")), e["installPath"]) for name, entries in plugins.items()
             if name.startswith("sdlc-pipeline@") and isinstance(entries, list)
             for e in entries if isinstance(e, dict) and usable(e.get("installPath"))]
except Exception:
    found = []
if not found:  # else the newest cached copy
    pattern = os.path.join(glob.escape(home), "plugins", "cache", "*", "sdlc-pipeline", "*")
    found = [(version(os.path.basename(p)), p) for p in glob.glob(pattern) if usable(p)]
print(max(found)[1].replace(chr(92), "/") if found else "")
' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" 2>/dev/null)"; fi
  if [ -z "$PY" ]; then echo '{"error":"python 3.8+ not found"}'
  elif [ -z "$R" ] || [ ! -f "$R/scripts/pipeline-ui.py" ]; then echo '{"error":"plugin folder not found"}'
  else "$PY" "$R/scripts/pipeline-ui.py" start --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd -W 2>/dev/null || pwd)" --open; fi
fi
```

It picks the first `python3` or `python` that is 3.8 or newer (so the Windows Store `python3`
stub is skipped), finds the plugin folder (`CLAUDE_PLUGIN_ROOT`, else the installed version from
`~/.claude/plugins/installed_plugins.json`, else the newest copy under `~/.claude/plugins/cache/`),
prints one JSON line and returns at once; the dashboard keeps running in the background.

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
now, run this as one Bash call (the same lookup as Step 1, with `stop`):

```bash
if [ "${CLAUDECODE:-}" != "1" ]; then echo '{"error":"needs-claude-code"}'; else
  PY=""; for c in python3 python; do if "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then PY="$c"; break; fi; done
  R="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
  if [ -z "$R" ] && [ -n "$PY" ]; then R="$("$PY" -I -c '
import glob, json, os, re, sys
home = sys.argv[1]
def version(text): return [int(n) for n in re.findall(r"[0-9]+", str(text))]
def usable(path): return isinstance(path, str) and os.path.isfile(os.path.join(path, "scripts", "pipeline-ui.py"))
found = []
try:  # the installed version first
    with open(os.path.join(home, "plugins", "installed_plugins.json"), encoding="utf-8") as fh:
        plugins = json.load(fh)["plugins"]
    found = [(version(e.get("version")), e["installPath"]) for name, entries in plugins.items()
             if name.startswith("sdlc-pipeline@") and isinstance(entries, list)
             for e in entries if isinstance(e, dict) and usable(e.get("installPath"))]
except Exception:
    found = []
if not found:  # else the newest cached copy
    pattern = os.path.join(glob.escape(home), "plugins", "cache", "*", "sdlc-pipeline", "*")
    found = [(version(os.path.basename(p)), p) for p in glob.glob(pattern) if usable(p)]
print(max(found)[1].replace(chr(92), "/") if found else "")
' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" 2>/dev/null)"; fi
  if [ -z "$PY" ]; then echo '{"error":"python 3.8+ not found"}'
  elif [ -z "$R" ] || [ ! -f "$R/scripts/pipeline-ui.py" ]; then echo '{"error":"plugin folder not found"}'
  else "$PY" "$R/scripts/pipeline-ui.py" stop --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd -W 2>/dev/null || pwd)"; fi
fi
```

It prints `{"stopped": true}`, `{"running": false}` (nothing was running) or `{"error": ...}`.
