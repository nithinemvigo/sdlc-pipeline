---
description: Open (or stop) the local run dashboard for this project, from any Claude Code session, without starting a pipeline. The dashboard is read-only and shows every /pipeline-dashboard, /pipeline-all, /pipeline and /pipeline-parallel run.
argument-hint: "[stop]"
---

# /pipeline-runs — open the run dashboard

This command only opens or stops the dashboard for the project this session is in. It never
starts, resumes or changes a pipeline run, and asks the client nothing. Use `/pipeline-dashboard` to
open the dashboard and start a run together.

Arguments: $ARGUMENTS

## Open (no arguments, or anything other than `stop`)

Run exactly this script, as one Bash call:

```bash
if [ "${CLAUDECODE:-}" != "1" ]; then echo '{"error":"needs-claude-code"}'; else
  PY=""; for c in python3 python; do if "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then PY="$c"; break; fi; done
  R="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
  if [ -z "$R" ] && [ -n "$PY" ]; then R="$("$PY" -I -c '
import glob, json, os, re, sys
home = sys.argv[1]
def version(text): return [int(n) for n in re.findall(r"[0-9]+", str(text))]
def usable(path): return isinstance(path, str) and os.path.isfile(os.path.join(path, "scripts", "pipeline-dashboard.py"))
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
  elif [ -z "$R" ] || [ ! -f "$R/scripts/pipeline-dashboard.py" ]; then echo '{"error":"plugin folder not found"}'
  else "$PY" "$R/scripts/pipeline-dashboard.py" start --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd -W 2>/dev/null || pwd)" --open; fi
fi
```

It finds Python 3.8+ and the plugin folder (`CLAUDE_PLUGIN_ROOT`, else the installed version
from `~/.claude/plugins/installed_plugins.json`, else the newest copy under
`~/.claude/plugins/cache/`), starts the dashboard in the background (or reuses the one already
running for this project), opens it in the browser and prints one JSON line. Then say one line:

- `{"url": ...}` → `Dashboard: <url>`, adding ` (already running)` when `reused` is true.
- `{"error": "needs-claude-code"}` → `The dashboard needs Claude Code.`
- any other `{"error": ...}` → `Dashboard not started: <error>`

Do nothing else.

## Stop (the argument is `stop`)

Run exactly this script, as one Bash call:

```bash
if [ "${CLAUDECODE:-}" != "1" ]; then echo '{"error":"needs-claude-code"}'; else
  PY=""; for c in python3 python; do if "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then PY="$c"; break; fi; done
  R="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
  if [ -z "$R" ] && [ -n "$PY" ]; then R="$("$PY" -I -c '
import glob, json, os, re, sys
home = sys.argv[1]
def version(text): return [int(n) for n in re.findall(r"[0-9]+", str(text))]
def usable(path): return isinstance(path, str) and os.path.isfile(os.path.join(path, "scripts", "pipeline-dashboard.py"))
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
  elif [ -z "$R" ] || [ ! -f "$R/scripts/pipeline-dashboard.py" ]; then echo '{"error":"plugin folder not found"}'
  else "$PY" "$R/scripts/pipeline-dashboard.py" stop --project "$(git rev-parse --show-toplevel 2>/dev/null || pwd -W 2>/dev/null || pwd)"; fi
fi
```

It prints `{"stopped": true}`, `{"running": false}` (nothing was running) or `{"error": ...}`;
say so in one line. The dashboard also stops by itself after two hours with nobody viewing it.
