# Story Management Rules

## Where things live

| Artifact | Location | Role |
|---|---|---|
| Development stories | `# Development Stories` section at the end of the user's original Markdown requirements document | The user-facing deliverable and the source of truth for story content |
| Story state | `<project-root>/stories/story-generation-state.json` | Internal: story identity, source and gap mappings, hashes, decision ledger |
| Backups | `<project-root>/stories/backups/<document>.<timestamp>.bak` | Copy of the document before each change to it |
| HTML report | `<project-root>/report/phase3-report.html` | Generated read-only view; never a source of truth |
| Atomic requirements, gap register | `atomic_requirements/`, `gaps/` | Read only in Phase 3 |

Never write project artifacts into the plugin installation directory. Never write gap decisions into the atomic requirements or any text outside the managed section.

## All writes go through the scripts

`scripts/sync-development-stories.py` is the only way to change the document, the state and the report: `apply`, `accept`, `regenerate-report` (read-only: `inspect`, `export`, `summary`). Do not hand-edit the document's managed section, the state file or the report. The script validates, detects manual edits and concurrent changes, backs up, writes a temporary file and replaces atomically, reads back and verifies, and writes the state only after verification.

## The managed section

1. The plugin owns only the top-level `# Development Stories` section. It is appended at the end if absent, updated in place if present, and never duplicated.
2. The section must be the last part of the document. If another top-level heading follows it, the heading is duplicated, or it only looks like the managed heading, stop and ask the user. The script reports this as `SECTION_AMBIGUOUS` and writes nothing.
3. Everything outside the section is preserved byte for byte, including encoding and line endings. Changes the user makes elsewhere in the document are preserved and never treated as story changes.
4. Stories that did not change are kept as written; only changed stories are rewritten.

## Story IDs

1. Format `US-001`; unique; sorted numerically.
2. A new story set is numbered sequentially from `US-001`. New stories in an existing set get the next unused number (`story_id: null` in the draft; the script assigns it).
3. Matched stories keep their ID. Never renumber because one was added or removed.
4. An ID of a deleted, retired or superseded story is never reused.

## Traceability

1. Each story records its source requirement IDs in the state. Related gaps are derived from the register: every gap whose `affected_requirements` include any of the story's requirements.
2. A gap may relate to several stories and a story to several gaps. Apply a decision only to stories it materially affects.
3. Open and skipped gaps are traceability references. They never block generation and are never decisions.
4. If the gap register is missing, generation continues and the limitation is reported. If it is invalid, ask the user to correct it or explicitly proceed without gap context; if they proceed, do not claim gap relationships were checked.

## Decision ledger and enrichment

1. A decision counts as incorporated only when the draft lists it in `decisions_reviewed` and (for `incorporated`) a story lists it in `applied_decisions`, or the agent explicitly determined that no story changes (`no_change_required`).
2. The ledger remembers which version of a decision (timestamp and hash) was reviewed, so a revised decision becomes pending again, and re-running with nothing new changes nothing.
3. If a resolved gap is reopened, never delete incorporated criteria automatically. Ask the user whether to retain, revise or remove them.
4. If a decision introduces a capability that cannot sensibly belong to an existing story, propose a new story and explain why. Do not create it silently when the relationship is uncertain.

## Manual edits and conflicts

1. Before writing, the script compares each story with the last synchronised version. A story edited by hand, a story added or deleted by hand, an ID changed by hand and edits outside the section are all detected.
2. Never overwrite or remove a manually edited story without the user's explicit consent for that story (`--overwrite`, `--allow-remove`, `--restore`). Show the current and proposed content and ask.
3. `sync-stories` records accepted manual edits in the state (`accept`) without touching the document. Stories that are new or unmapped need source requirement IDs confirmed with the user when they cannot be determined confidently.
4. A section that breaks the four-field contract (extra fields, bad or duplicate IDs, stray text) is not updated until the user fixes it.

## Safety

1. Pass `--expected-source-sha256` from `inspect` or `export` so a change made while work was in progress is never overwritten.
2. Ask before any destructive step: removing a story, overwriting a manual edit, changing the target document.
3. If the document write fails, the previous document and state are kept. If the state write fails after the document was saved, do not claim success; recover with `inspect` and `accept`.
4. If the report fails, the stories and state stay valid; say the report is stale and offer `/sdlc-pipeline:ba-generate-report`.
5. Report only counts that come from the scripts' JSON output.
6. Exit codes: `0` success, `1` refused (nothing changed), `2` I/O failure (nothing changed), `3` saved but report failed, `4` document saved but state not.

## Target document

Phase 1 does not record which Markdown files it analysed. In Phase 3 the target is chosen once and then remembered in the state.

1. One Markdown file was analysed: use it, after confirming with the user.
2. A directory or several files: ask the user to select the single primary document. Never append stories to every file. Traceability still covers requirements from all files because it works from requirement IDs.
3. If the recorded target is gone, ask the user to locate it. Never create a replacement silently.
