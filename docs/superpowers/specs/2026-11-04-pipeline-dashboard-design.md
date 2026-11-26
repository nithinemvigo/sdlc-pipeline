# /pipeline-dashboard — local, read-only run dashboard — Design

- **Date:** 2026-11-04
- **Status:** Draft — awaiting review
- **Branch:** `feature/pipeline-dashboard`, cut from `feature/pipeline-all` (plugin 3.4.1 → 3.5.0)

## 1. Goal

Give every developer a browser dashboard that shows, live, what a pipeline run on their own
machine is doing: which stage it is in, which agents ran and are running, what each one cost
in tokens and time, which questions were asked and answered, and what each task changed in
the code.

It is launched by a new command, `/sdlc-pipeline:pipeline-dashboard`, which opens the dashboard and
then runs one of the existing flows. **The existing pipelines are not modified.**

## 2. Decisions (client, 2026-11-04)

| # | Decision |
|---|---|
| D1 | Read-only first. No start, pause, retry or approve from the UI in this version. |
| D2 | Local only. Each developer sees only their own runs, on their own machine. No shared server, no login, nothing leaves the laptop. |
| D3 | Scope is the current repository (including its git worktrees). |
| D4 | A new command, `/pipeline-dashboard`, opens the dashboard and then asks which flow to run: `pipeline-all`, `pipeline` or `pipeline-parallel`. |
| D5 | `/pipeline`, `/pipeline-all` and `/pipeline-parallel` are unchanged. The dashboard learns everything from files Claude Code and git already write, so a run adds no orchestrator tokens for tracking, and improvements to the flows reach `/pipeline-dashboard` automatically. |
| D6 | Approach A: a Python standard-library server on `127.0.0.1` plus one self-refreshing HTML page. No Node, no npm, no build step. |
| D7 | Renamed from /pipeline-ui (confusing) to /pipeline-dashboard; the view-only command is /pipeline-runs (client, 2026-11-26). |

## 3. Scope

**In:** run list, run view (stage timeline, agents, checkpoints, tasks and diffs, artifact
links), token usage and estimated cost, live refresh, the `/pipeline-dashboard` command, tests,
README section, version bump.

**Out (this version):** controlling runs (D1), sharing or other machines' runs (D2), runs in
other repositories (D3), editing anything, Cursor (Cursor does not write Claude Code
transcripts — see 5.2).

## 4. Files

All new, except the README and the three version fields.

| File | Purpose |
|---|---|
| `commands/pipeline-dashboard.md` | The `/pipeline-dashboard` command (section 5). |
| `commands/pipeline-runs.md` | The `/pipeline-runs` command (section 5.3): opens or stops the dashboard only. |
| `scripts/pipeline-dashboard.py` | CLI: `start`, `serve`, `stop`, `status`. Starts the server and holds the HTTP handlers. |
| `scripts/pipeline_dashboard/` | Package with one module per reader, so each is testable on its own: `transcripts.py`, `runs.py`, `agents.py`, `stages.py`, `checkpoints.py`, `usage.py`, `gitinfo.py`, `artifacts.py`, `status.py`. |
| `scripts/pipeline-dashboard.html` | The page: vanilla HTML/CSS/JS in one file, no external requests. |
| `scripts/pipeline-dashboard-prices.json` | Editable per-model price table for the cost estimate. |
| `tests/pipeline-dashboard/` | Tests and hand-written fixtures (section 12). |
| `README.md` | New "Watching a run" section. |
| `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json` | Version 3.4.1 → 3.5.0; 3.5.1 for the hidden-console fix and the view-only command; 3.6.0 for the rename (`/pipeline-ui` → `/pipeline-dashboard`, view-only command → `/pipeline-runs`); 3.6.1 for the review fixes and the command-header quoting. |

Everything must run on **Python 3.8+**, matching the README's existing requirement.

## 5. The `/pipeline-dashboard` command

### 5.1 Steps

Arguments: `[--flow pipeline-all|pipeline|pipeline-parallel] <the request, as for the flow>`.

1. **One Bash call** (a short script in the command file) that resolves three things and
   starts the dashboard with `<python> "<root>/scripts/pipeline-dashboard.py" start --project <project> --open`:
   - **Python** (first, because the root lookup uses it): the first of `python3`, `python` for
     which `-c 'import sys; sys.exit(sys.version_info < (3, 8))'` succeeds, so the Windows Store
     `python3` stub is skipped. None → `{"error": "python 3.8+ not found"}`.
   - **root**, in this order:
     1. `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}` (Claude Code's Bash tool sets neither today);
     2. the installed version: `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json`
        (version 2, `{"plugins": {"sdlc-pipeline@<marketplace>": [{"installPath", "version"}, ...]}}`),
        the `installPath` of an `sdlc-pipeline@*` entry that contains `scripts/pipeline-dashboard.py`,
        the highest `version` if there are several;
     3. only when that file is missing, unreadable or has no usable entry: the newest version
        folder under `.../plugins/cache/*/sdlc-pipeline/*/` that contains the script.

     The JSON parsing and the numeric version order run in the chosen Python (`-I -c`), not in
     `sort -V`, which BSD/macOS `sort` lacks. None → `{"error": "plugin folder not found"}`.
   - **project:** `git rev-parse --show-toplevel`, else `pwd -W` (Git Bash), else `pwd`.

   It prints one JSON line: `{"url": ..., "pid": ..., "reused": true|false}`, or
   `{"error": ...}`. The URL carries the per-launch key in its fragment (`/#k=<key>`, 9.3).
2. **One line to the client:** `Dashboard: <url>` (or `Dashboard not started: <error> — continuing without it.`).
   A failed start never blocks the run.
3. **Flow choice.** If `--flow` was given, use it. Otherwise one `AskUserQuestion`:
   `pipeline-all` (features, requirements first — recommended for new features) ·
   `pipeline` (features or bugs) · `pipeline-parallel` (features or bugs, parallel build).
4. **Hand off:** invoke the Skill `sdlc-pipeline:<flow>` with the remaining arguments,
   unchanged, then follow that skill exactly. `/pipeline-dashboard` adds no stages, rules or
   questions of its own after this point.

Total added cost per run: two or three orchestrator tool calls.

### 5.2 Cursor

Cursor is detected by `CLAUDECODE` not being `1` (Claude Code sets `CLAUDECODE=1` in its Bash
tool; `CLAUDE_PLUGIN_ROOT` is not a usable signal, since Claude Code does not set it there
either). In Cursor step 1 prints `{"error": "needs-claude-code"}`, step 2 prints
`The dashboard needs Claude Code; continuing without it.`, and steps 3–4 run as normal.

### 5.3 `/pipeline-runs`

Opens the dashboard for the current project from any Claude Code session, without starting a
run: it runs the same start block as Step 1 (byte-identical, so the same plugin lookup) and
prints `Dashboard: <url>`. With the argument `stop` it runs the same stop block as
`/pipeline-dashboard`. It never invokes a flow, asks nothing, and changes nothing else.

## 6. Where the data comes from

### 6.1 Transcript folders

- Config dir = `$CLAUDE_CONFIG_DIR` if set, else `~/.claude`.
- Project paths = the repo root plus every path from `git worktree list --porcelain`.
- For each project path, its transcript folder is `<config dir>/projects/<encoded>`, where
  `<encoded>` is the absolute path with every character outside `[A-Za-z0-9]` replaced by
  `-` (verified: `C:\Users\EMVIGO-USER\Muhassin\workspace\claude-investigation\emi` →
  `C--Users-EMVIGO-USER-Muhassin-workspace-claude-investigation-emi`).
- **Fallback** when that folder does not exist (for example, Claude Code shortened a very
  long path): scan the folders under `<config dir>/projects/` and keep those whose first
  entry carrying a `cwd` field has a `cwd` equal to a project path. The folder list is
  computed on first use and kept, except that an empty list is recomputed on the next
  request (so a project whose first session starts after the server does still appears).
- Each session: `<folder>/<session id>.jsonl` (main session) and
  `<folder>/<session id>/subagents/agent-<id>.jsonl` plus `agent-<id>.meta.json`
  (`agentType`, `description`, `toolUseId`, `spawnDepth`).

### 6.2 Runs

- **Run start:** a main-session entry with `type: "user"`, `isSidechain: false`, not
  `isMeta`, whose message text *starts with* `<command-message>` or `<command-name>` and
  matches
  `<command-name>/?(?:sdlc-pipeline:)?(pipeline-all|pipeline-parallel|pipeline-dashboard|pipeline-ui|pipeline)</command-name>`.
  `pipeline-ui` is the command's name before 3.6.0, still matched so earlier runs show.
  Runs started directly with an existing flow are listed too. The "starts with" rule matters:
  subagent hand-back reports arrive in the main session as user messages, and one that quotes
  a command must not open a new run. (Verified on the 2026-10-29 EMI run: a Skill hand-off
  such as `/pipeline-dashboard` → `pipeline-all` is logged as a `tool_result`
  "Launching skill: …", not as a new `<command-name>` entry, so it does not split the run.)
- **Run end:** the next run start in the same session, or the end of the file.
- **Run id:** `<session id>:<line number of the start entry>`.
- **Flow:** the matched command name. For `pipeline-dashboard` (or the legacy `pipeline-ui`), the flow is the name in the first
  `Skill` tool call to `sdlc-pipeline:pipeline*` after the start; until that call exists the
  flow shows as `choosing…`.
- **Title:** the first line of `<command-args>`, cut to 120 characters (`(no request text)`
  if empty).
- **Branch:** the `gitBranch` of the latest entry in the window that is not the base branch;
  else the base branch; else (no entry names a branch) the fallback in §6.6.
- **Linked runs:** runs on the same non-base branch are shown as parts of one feature
  ("resumed from <run>").

### 6.3 Agents

- An agent belongs to the run whose window contains the main-session `Agent` tool call with
  id = the agent's `toolUseId`. If that call is not found, the agent's first timestamp
  decides.
- Agents with `spawnDepth` > 1 are listed under the agent that spawned them: in the page's
  default (start-time) order each child row comes right after its parent, recursively, shown
  as `↳ <type> (from <parent type>)`. The cost and duration sorts are flat.
- Per agent: type (without the `sdlc-pipeline:` prefix), description, model (the most common
  `message.model`, ignoring `<synthetic>`), first and last timestamp, duration, usage
  (section 7), state:
  - **finished:** the agent called `SubagentHandback` and has no assistant entry after that
    call; or, with no hand-back in its transcript, the main session has a
    `<task-notification>` whose `<task-id>` is the agent's id; or its last entry is an
    assistant entry with `stop_reason: "end_turn"` (foreground agents);
  - **running:** otherwise, and the file was written in the last 10 minutes;
  - **interrupted:** otherwise.

  (Verified on the EMI run: pipeline agents run asynchronously, every assistant entry has
  `stop_reason: "tool_use"`, and a finished agent's transcript ends with the
  `SubagentHandback` call and its "Report delivered to your caller." result. The agent id is
  the `agent-<id>` file name, which is also the notification's `<task-id>`.)

### 6.4 Stages

The stage of an agent comes from its type:

| Agent type | Stage |
|---|---|
| `requirements-writer` | R — Requirements |
| `requirement-analyst`, `gap-analysis-agent`, `story-generation-agent` | Q — BA analysis |
| `distiller` | 0.8 — Distil |
| `planner` | 1 — Plan |
| `investigator` | 1-B — Investigate |
| `ceo-reviewer`, `eng-reviewer`, `design-reviewer` | 2 — Plan review |
| `adr-writer` | 2.7 — ADR |
| `implementer` | 3 — Build (see the rule below) |
| `unit-tester` | 4 — Unit tests |
| `qa-tester` | 4.5 — QA |
| `code-reviewer`, `security-reviewer` | 5 — Code + security review |
| `perf-tester` | 5.5 — Performance |
| `doc-writer` | 5.8 — Docs |
| `acceptance-verifier` | 5.85 — Acceptance |
| `ship-pr` | 6 — Ship |
| any other type | Other (shown in the stage reached at the time) |

- **Fix rounds:** an `implementer` that starts after an agent of a later stage has started
  belongs to that later stage, labelled `fix`. (In the EMI run, an implementer after the
  acceptance verifier is an acceptance fix, not Build.)
- **Stages per flow:** `pipeline-all` shows R, Q, 0.8, 1, 2, 2.7, 3, 4, 4.5, 5, 5.5, 5.8,
  5.85, 6. `pipeline` and `pipeline-parallel` show 0.8, 1 or 1-B, 2, 2.7, 3, 4, 4.5, 5, 5.5,
  5.8, 6.
- **Stage state:**
  - **in progress:** it has a running agent, or it is the latest stage with agents and the
    run's status (section 8) is *running*;
  - **done:** it has agents and is not in progress (so at plan approval, Plan review shows
    done while the run waits for the client);
  - **skipped:** it has no agents and a later stage has agents;
  - **not reached:** otherwise.
- **Checkpoints** (section 6.5) are placed on the timeline by time, between stages.

The table lives in `stages.py` as data, so a new agent type is a one-line change.

### 6.5 Checkpoints

- Every main-session `AskUserQuestion` tool call in the run window, with time, header,
  question text and option labels.
- **Answer:** the text of the matching `tool_result`. If that result is an error (the
  client answered in chat instead, as happens in the desktop app), the answer is the first
  300 characters of the next message the client typed, marked `answered in chat`. A typed
  message is a user entry that is not `isMeta`, carries no `tool_result`, has no `origin`
  other than the user (task notifications and hand-back reports carry one), and has text left
  after removing `<system-reminder>` blocks.
- A normal answer like `User has answered your questions: "Q"="A". …` is shown as the
  `A` values joined with `; `; any other result text is shown as is (first 300 characters).
- No result yet: **pending**.

### 6.6 Tasks and changes

- **Plan folder:** `docs/plans/<slug>/`, where `<slug>` is the branch name after its first
  `/` (`feature/calculate-emi` → `calculate-emi`). Tasks are the `task-NN-<name>.md` files.
- **Base:** `git merge-base <base> <branch>`, where base is `master` or `main`, whichever
  exists (`main` if both do).
- **Commits:** `git log --format=%H%x09%aI%x09%s <merge-base>..<branch> --`. A commit belongs to
  task `NN` when its subject matches `\btask[ -]?0*<N>\b` (case-insensitive), where `<N>` is
  the task number without leading zeros, so `task 03`, `Task 3` and `task-03` all match task
  `03`. Others are listed as "other commits".
- **Run without a branch:** when no entry in the window carries a usable `gitBranch` (for
  example every entry says `HEAD`, as on the 2026-11-05 EMI demo, where the repo had no
  commit when the run started), the slug comes from evidence already in the run window, first
  match wins:
  1. a `Write` tool call whose `file_path` is `docs/plans/<slug>/00-overview.md`: the run's
     `planner` agents first, then any other agent of the run, then the orchestrator; else a
     `planner` agent's own output (its text and `SubagentHandback` message) naming that file;
  2. else the `feature/<slug>` branch created by a `git switch -c|-C|--create` or
     `git checkout -b|-B` call (flags such as `-q` allowed) in a `Bash` or `PowerShell` tool
     call of the orchestrator, then of the run's agents;
  3. else no slug, and no plan or commits, as before.

  A slug taken this way must be one plain path segment (`[A-Za-z0-9][A-Za-z0-9._-]*`, no
  `..`); anything else is ignored. If `refs/heads/feature/<slug>` exists in git, it becomes the
  run's branch: it is shown in the run list and run view, it links runs (§6.2), and it gives
  the commit list and the diffs. If it does not exist, the plan tasks and plan files are still
  shown, with no commits. Nothing is written, and the git check is cached with the other git
  queries (§9.4).
- **Bug track:** for a `fix/` or `hotfix/` branch with no plan folder, the investigator's
  mini-plan (`docs/bugs/<slug>*.md`) is shown in place of the task list, and every commit is
  listed under it.
- **Diff:** `git show --stat --patch --no-color --no-ext-diff --no-textconv <sha>`, cut at 1 MB with a `truncated`
  notice.

### 6.7 Artifacts

Links are offered only for files that exist from this list (paths relative to the repo):

- `docs/plans/<slug>/00-overview.md` and the task files, and on the bug track only (a `fix/` or
  `hotfix/` branch) `docs/bugs/<slug>*.md`;
- the requirements file, from the `--requirements` argument of the run's first
  `sdlc-pipeline:ba-run` Skill call, and its artifact root
  (`<requirements dir>/ba/<stem without .requirements>/`), from which:
  `stories/detailed_stories.md`, `acceptance/acceptance-report.md`, and any `*.html` file
  under the artifact root. A requirements file or artifact root (given or derived) that is not
  inside the repository is ignored, before any glob runs.

## 7. Usage and cost

- Usage is read from `message.usage` on assistant entries. **Each `message.id` is counted
  once**, because Claude Code can write several entries for one response with the same
  usage repeated.
- Four numbers are kept separately: input, output, cache write (`cache_creation_input_tokens`)
  and cache read (`cache_read_input_tokens`). The page shows all four, plus their total.
- Rows: one per agent, plus an **orchestrator** row for the main session's own usage within
  the run window. The run total is their sum.
- **Estimated cost** = tokens × the model's rates in `pipeline-dashboard-prices.json` (USD per
  million tokens for input, output, cache write 5m, cache write 1h, cache read). Cache writes
  are split by `cache_creation.ephemeral_5m_input_tokens` and
  `ephemeral_1h_input_tokens` when present, else priced as 5m. The shipped values are copied
  from the Anthropic pricing reference (the `claude-api` skill) when this is implemented.
  The page labels it "estimate".
- Models missing from the table (including `<synthetic>`) show tokens and `—` for cost.

## 8. Run status

Checked in this order:

1. **finished:** a `ship-pr` agent in the run is finished.
2. **stopped:** the run's window was closed by a later run in the same session.
3. **waiting for you:** a checkpoint is pending.
4. **running:** any of the run's agents is running (6.3), or the main-session file was
   written in the last 2 minutes and its last entry in the window is not an assistant entry
   with `stop_reason: "end_turn"`. (Agents can keep working in the background after the
   orchestrator's turn ends, so this check comes before rule 5.)
5. **waiting for you:** the last main-session entry in the window is an assistant entry with
   `stop_reason: "end_turn"` (the turn ended and the next move is the client's, for example
   "type Continue now").
6. **stopped:** otherwise (the session was closed or interrupted mid-turn).

Both *waiting for you* rules show how long it has waited (`waiting for you · 3 h`).

## 9. Server

### 9.1 CLI

- `start --project <path> [--open]`: if a server for this project is already healthy,
  reuse it. Otherwise spawn `serve` in the background: on Windows with
  `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` (a hidden console of its own), elsewhere with
  `start_new_session`. Not `DETACHED_PROCESS`: a server with no console makes Windows open a
  new console window for every console program it runs, so each `git` query flashed a window
  up. Every `git` call also passes `CREATE_NO_WINDOW` on Windows. Then wait up to 5 s for `/api/health`, then print the JSON line
  from 5.1. `--open` does not pass the URL to the browser (on Linux a process's argv is
  readable by other users): it writes `<ui dir>/<digest>-open.html` (0600 on POSIX), a
  meta-refresh and a link to the `#k=` URL, and opens that file's `file://` URI. The file is
  rewritten on each start and deleted by `stop` and by the server's own cleanup.
- `serve --project <path> --port <n>`: run the server in the foreground.
- `stop --project <path>`: stop that project's server.
- `status --project <path>`: print its JSON line, or `{"running": false}`.

### 9.2 State and lifecycle

- State file: `<config dir>/sdlc-pipeline/dashboard/<first 12 hex of sha1(repo root)>.json` with
  `pid`, `port`, `project`, `token` (the per-launch key, 9.3) and `started_at`; created 0600 on
  POSIX (on Windows the user profile's ACL protects it). The server also writes its log next
  to it (`<same name>.log`, the detached process's stderr), and `start --open` writes the
  redirect file `<same name>-open.html` (9.1). These are the only files the dashboard writes,
  and they are outside the repository.
- A state file whose `token` is missing or not a non-empty string is stale: it is removed and
  treated as no state, and its server is never probed or stopped. `start` then starts a fresh
  server (possibly on the next port); `stop` and `status` return `{"running": false}`.
- Reuse check: `GET /api/health` on the stored port, sent with the stored key, returns the same
  `project`. A server that does not accept the key is not ours: it is never reused and never
  stopped. A healthy server from another plugin version is stopped and a new one started.
- `stop`: nothing answers → the stale state file is deleted, `{"running": false}`; the server
  answers but the key, project or pid does not match →
  `{"error": "the server on port N is not this project's dashboard; not stopped"}` and the
  state file is kept; otherwise the process is ended, `{"stopped": true}`.
- Port: 8765 first, then the next 19 ports. If none is free, `start` returns
  `{"error": "no free port in 8765-8784"}`.
- Idle shutdown: after 2 hours with no HTTP request, the server exits and deletes its state
  file. `stop` does the same immediately. Only requests that pass the Host and key checks count
  as activity.

### 9.3 HTTP API (all `GET`, JSON unless noted)

How the key travels: `start` prints `http://127.0.0.1:<port>/#k=<key>`. A fragment is never
sent to a server and never appears in a Referer. On load the page moves the key to
`sessionStorage` (per origin, so per port) and clears it from the address bar with
`history.replaceState`; `#run=` routing then works as before. Every `fetch` sends
`X-Pipeline-Dashboard-Token: <key>`; the CLI sends the same header. There are no cookies.

- `GET /` serves the page without a key; it holds no data and does not count as activity.
- Every other request, `/api/health` included, needs the header (compared with
  `hmac.compare_digest`), else `403 {"error": "missing or wrong dashboard key"}`. Without a
  key, or on a 403, the page shows "Open the dashboard with the link /pipeline-dashboard printed (it
  contains a one-time key)." instead of retrying.
- HTML reports open in a new tab, which cannot send a header. The page asks
  `/api/file-link?run=&key=` (with the header) for
  `/api/file?run=<run>&key=<key>&exp=<now+60>&sig=<hex HMAC-SHA256(key, run "\n" file key "\n" exp)>`
  and opens it with `window.open(url, "_blank", "noopener")`. `/api/file` accepts the header or
  such a signature: constant-time compare, unexpired, `exp` at most 120 s ahead. The signature
  covers the run and the file key, so it opens nothing else. Other files are fetched with the
  header.
- `HEAD`, `POST`, `PUT`, `DELETE` and `OPTIONS` get `405` (after the same Host and key checks).

| Path | Returns |
|---|---|
| `/` | `pipeline-dashboard.html` (no key needed) |
| `/api/health` | `project`, plugin version, `pid` |
| `/api/runs` | `project`, the transcript `folders` searched (for the empty state), and `runs`: id, flow, title, branch, status, started, duration, token total, estimated cost, linked run ids |
| `/api/runs/<id>` | Run view: the above plus stages, agents, checkpoints, tasks with commits, artifact keys, read warnings (section 10) |
| `/api/diff?run=<id>&commit=<sha>` | Text of the diff |
| `/api/file?run=<id>&key=<key>` | One artifact from 6.7 (header, or `&exp=&sig=` from `/api/file-link`) |
| `/api/file-link?run=<id>&key=<key>` | `{"url": ...}`: a signed `/api/file` link valid for 60 s |

### 9.4 Reading efficiently

Each transcript file is read incrementally: the server keeps, per file, its size, the byte
offset already parsed and the summary built so far, and on each request parses only new
bytes. A file that shrank or was replaced (size smaller than the offset) is re-read from the
start. The plan folder and git results are cached for 5 seconds.

## 10. The page

- **Runs list** (newest first): started, flow, title, branch, status badge, duration, total
  tokens, estimated cost. A run that continues an earlier run's branch is marked "resumed
  from an earlier run on this branch".
- **Run view:**
  - header: title, flow, branch, status, duration, total tokens, estimated cost;
  - stage timeline across the top, with checkpoints between stages;
  - agents table: stage, type, description, model, start, duration, the four token
    numbers, estimated cost, state; sortable by cost and by duration;
  - checkpoints: time, question, answer (or pending);
  - tasks: each task file with its commits; "show diff" expands the diff inline, with added
    and removed lines coloured;
  - artifacts: links that open the file as text (`.md`, `.json`) or in a new tab (`.html`).
- **Refresh:** every 3 seconds while the run is *running* or *waiting for you*; every 30
  seconds otherwise. A small "updated 2 s ago" line shows freshness.
- Follows the system light or dark setting. No fonts, scripts or styles from the internet,
  so it works offline.
- **Empty state:** "No pipeline runs found for <repo>. Looked in: <folders>."

## 11. Errors and edge cases

- **Transcript format changes:** the transcript format is not a documented contract and may
  change between Claude Code versions. Readers skip lines that are not valid JSON and ignore
  entry types and fields they do not know. The run view shows a warning line, for example
  `12 lines could not be read · Claude Code 2.1.312`, taking the version from the entries'
  `version` field.
- A missing subagent `meta.json` → the agent shows type `unknown`.
- No git, or the branch was deleted → tasks are listed without commits; the diff button is
  hidden.
- A plan folder that is not there yet → the tasks section says "No plan yet".
- One reader failing must not break the page: each section of `/api/runs/<id>` is built
  separately, and a failure becomes that section's `error` field, shown in place.

## 12. Security

- Binds to `127.0.0.1` only. Never `0.0.0.0`.
- Requests whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` get a 403,
  so a web page using DNS rebinding cannot read transcripts through the server.
- **Per-launch key.** Each server generates `secrets.token_urlsafe(32)` and keeps it in its
  state file. Every data request needs it, compared with `hmac.compare_digest`. It travels in
  the URL fragment (`/#k=`), then in `sessionStorage`, then in the `X-Pipeline-Dashboard-Token`
  header; the CLI sends the same header. Other local users and sandboxed processes that can
  reach the loopback port therefore cannot read transcripts. The order is Host check, then the
  key, and only then does the request count as activity, so refused requests do not keep an
  idle server alive.
- **No cookies.** A cookie for `127.0.0.1` is sent to every port on that host (RFC 6265 §8.5;
  SameSite ignores ports), so another account's server on another port could collect it. The
  dashboard sets none and accepts none.
- **Signed links** for HTML reports: HMAC-SHA256 over run, file key and expiry, valid 60 s
  (at most 120 s ahead), for `/api/file` only.
- **Referrer-Policy: no-referrer** on every response.
- **`--open` uses a redirect file** (0600 on POSIX) instead of putting the key on the
  browser's command line.
- **Residual risks:** the key appears in the transcript of every Claude Code session that opened the
  dashboard (the JSON line and `Dashboard: <url>`) and in the browser's history (the `#k=` URL),
  both the user's own data; any process running as the same user can read the state file, the
  transcript or the history, and so the key. The key protects against other accounts and web pages,
  not against the user's own processes.
- **No port sharing on Windows:** the server does not set `SO_REUSEADDR` there and sets
  `SO_EXCLUSIVEADDRUSE`, so no second socket can bind a port the dashboard is listening on.
- The CLI's own health checks bypass any `HTTP_PROXY` setting.
- Branch names read from transcripts are never passed to git if they start with `-`.
- Every endpoint is read-only. The only files written are the state file, the log and the
  `--open` redirect file (9.2).
- BA requirements and artifact-root paths read from transcripts are ignored unless they are
  inside the repository; this is checked before any glob.
- git is called with `--` after the `log` range and with `--no-textconv` for diffs.
- `/api/diff` accepts only a 40-character hex sha that is in that run's commit list; git is
  called with an argument list, never through a shell.
- `/api/file` accepts only keys from that run's artifact list (6.7); there is no path
  parameter. Resolved paths must stay inside the repository.
- HTML artifacts are served with `Content-Security-Policy: sandbox allow-scripts`: the BA
  reports keep working, but run in an opaque origin, so they cannot read the dashboard's API
  (the server sends no CORS headers).
- The page itself is served with a Content-Security-Policy that allows no external scripts,
  styles, fonts or connections, and builds every element with text nodes (no `innerHTML`),
  so transcript text can never run as markup.
- Every response, including the standard library's own errors (400, 404, 501), sets
  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: no-referrer`, so transcript content is not cached by the browser.

## 13. Testing

Standard library `unittest`, like `tests/acceptance`:
`python -I -m unittest discover -s tests/pipeline-dashboard`.

- **Fixtures** (hand-written, shaped like the 2026-10-29 EMI run, no real content): a project
  transcript folder with
  - a session holding two runs (one `/pipeline-dashboard` that hands off to `pipeline-all`, one
    plain `/pipeline`);
  - subagents covering every stage in 6.4, an implementer after the acceptance verifier
    (fix round), one running agent, one interrupted agent, one with no `meta.json`, one
    nested (`spawnDepth` 2);
  - checkpoints answered normally, answered in chat after an error result, and pending;
  - repeated entries with the same `message.id`, an invalid JSON line, an unknown entry
    type, and `<synthetic>` model entries.
- **Unit tests per module:** path encoding and the fallback scan; run windows, flow and title;
  agent attribution by `toolUseId` and by time; the stage table, fix rounds and per-flow stage
  lists; stage states; checkpoint answers; usage de-duplication and the four token numbers;
  cost with 5m/1h cache writes and unknown models; each status rule in order, with file
  times faked; commit-to-task matching; artifact discovery.
- **Git reader** against a temporary repo built in `setUp` (base branch, feature branch,
  commits mentioning `task 01`, `Task-02` and `task 3`, one with no task), plus a `fix/`
  branch with a `docs/bugs/` mini-plan and no plan folder.
- **Security tests:** `/api/diff` rejects a sha outside the run; `/api/file` rejects an
  unknown key; the server is bound to `127.0.0.1`.
- **Smoke test:** start `serve` on a free port against the fixtures, call `/api/health`,
  `/api/runs` and `/api/runs/<id>`, check the shapes, stop it.
- **Manual check** before shipping: run `/pipeline-dashboard` on a small feature (the EMI demo) in
  the Claude Code CLI and the desktop app, and watch the dashboard through a full run.

## 14. Release

- README: a "Watching a run" section with what `/pipeline-dashboard` does, the stop command, where
  the data comes from, that the dashboard sends nothing anywhere and the link's key is private,
  and the Cursor limitation.
- Version 3.4.1 → 3.5.0 in the three version fields, then 3.5.1, 3.6.0 and 3.6.1 as in section 4; the
  released version is 3.6.1.

## 15. Risks

| Risk | Mitigation |
|---|---|
| A Claude Code update changes the transcript format | Tolerant readers and a visible warning (11). Fixtures make breakage easy to locate and fix. |
| Stage shown wrongly for a new agent type or a new flow step | Stage table is data in one place (6.4); unknown types go to "Other" rather than failing. |
| Cost estimate drifts from real billing | Labelled "estimate"; prices in an editable file. |
| The server is left running | Idle shutdown after 2 hours; `stop` command. |
| Large transcripts make polling slow | Incremental reads (9.4). |
