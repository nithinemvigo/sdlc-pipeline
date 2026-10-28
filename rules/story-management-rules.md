# Story Management Rules

## Where things live

| Artifact | Location | Role |
|---|---|---|
| Detailed stories | `<project-root>/stories/detailed_stories.md`: **one** consolidated Markdown file for all stories | The complete functional and non-functional stories. The single detailed story repository and the source of the HTML report |
| Ultra-lean stories | `# Development Stories` section at the end of the user's original Markdown requirements document | The high-level, functional-oriented version of each story (Story ID, concise summary, one short high-level acceptance-criteria statement), derived from its detailed story, so the requirements document stays short |
| Story state | `<project-root>/stories/story-generation-state.json` | Internal: story identity, requirement-to-story and gap-to-story mappings, hashes of both versions, decision ledger, synchronisation metadata |
| Backups | `<project-root>/stories/backups/<file>.<timestamp>.bak` | Copy of the requirements document or of `detailed_stories.md` before it is changed |
| HTML report | `<project-root>/report/phase3-report.html` | Generated read-only view; never a source of truth |
| Atomic requirements, gap register | `atomic_requirements/`, `gaps/` | Read only in Phase 3 |

No per-story Markdown files are ever created. `stories/detailed/`, `stories/US-001.md` and `stories/lean-stories.md` come from earlier plugin versions; they are no longer read or written, and the validator reports them.

Never write project artifacts into the plugin installation directory. Never write gap decisions into the atomic requirements or any text outside the managed section.

## All writes go through the scripts

`scripts/sync-development-stories.py` is the only way the commands change the document, `detailed_stories.md`, the state and the report: `apply`, `accept`, `regenerate-report` (read-only: `inspect`, `export`, `summary`). Do not hand-edit the document's managed section, the detailed stories file, the state file or the report from a command (a user may edit them by hand; the scripts detect that, see "Manual edits and conflicts"). The script validates, detects manual edits and concurrent changes, backs up, writes temporary files and replaces atomically, reads back and verifies, and writes the state only after verification. If a write fails, the detailed stories file and the document are put back as they were.

## One story, two representations

1. Every story has one section in `stories/detailed_stories.md` and one ultra-lean entry in the managed section, with the same Story ID and the same summary (both are in the heading `## US-001 — Registered user login`). Each is listed in the state with its own content hash.
2. The detailed story is authoritative and is written first. The ultra-lean story is derived from it and must not contradict it, lose its core intent, or add behaviour it lacks. A draft supplies both (`lean_acceptance_criteria` and the `detailed` object).
3. The state records, per story, the hash of the ultra-lean story (`story_content_hash`), the hash of the detailed story (`detailed_content_hash`) and the detailed version the ultra-lean story was last derived from (`lean_derived_from`). When a detailed story changes and its ultra-lean story has not been updated (or confirmed with `lean_reviewed`), `inspect` and the report flag it as `lean_needs_update`. The state also records the hash of the whole detailed stories file (`detailed_document_hash`).
4. Mappings (requirements, gaps, decisions), hashes and synchronisation metadata are never written into either representation; they live only in the state.
5. A project created by an earlier plugin version (stories with Summary and Detailed Description fields, or one file per detailed story) is migrated by `/sdlc-pipeline:ba-generate-stories`: `inspect` reports the old layout, the agent writes the detailed stories from the atomic requirements and confirmed decisions and rewrites each ultra-lean story, and `apply --overwrite` replaces the old entries after the user agrees. IDs are kept. The replaced document is backed up.

## The managed section

1. The plugin owns only the top-level `# Development Stories` section. It is appended at the end if absent, updated in place if present, and never duplicated.
2. The section must be the last part of the document. If another top-level heading follows it, the heading is duplicated, or it only looks like the managed heading, stop and ask the user. The script reports this as `SECTION_AMBIGUOUS` and writes nothing.
3. Everything outside the section is preserved byte for byte, including encoding and line endings. Changes the user makes elsewhere in the document are preserved and never treated as story changes.
4. Stories that did not change are kept as written; only changed stories are rewritten.
5. Each story in the section is `## <ID> — <short summary>` followed by `**Acceptance Criteria:**` and one inline statement. Any other field is a contract violation.

## The detailed stories file

1. `stories/detailed_stories.md` holds a `# Detailed Stories` title, a maintenance note and one `## <ID> — <short summary>` section per story, in ID order, with the fields listed in `story-writing-rules.md`.
2. The file is wholly plugin-managed. Stories that did not change are kept as written (including a hand-made formatting change that does not alter content); only changed stories are rewritten.
3. A detailed story without a matching entry in the requirements document is kept and reported; it is never dropped silently. A story removed with the user's consent leaves the file, and the earlier file is kept in `stories/backups/`.

## Story IDs

1. Format `US-001`; unique; sorted numerically.
2. A new story set is numbered sequentially from `US-001`. New stories in an existing set get the next unused number (`story_id: null` in the draft; the script assigns it).
3. Matched stories keep their ID. Never renumber because one was added or removed.
4. An ID of a deleted, retired or superseded story is never reused.

## Traceability

1. Each story records its source requirement IDs in the state. Related gaps are derived from the register: every gap whose `affected_requirements` include any of the story's requirements.
2. A gap may relate to several stories and a story to several gaps. Apply a decision only to stories it materially affects.
3. Open and skipped gaps are traceability references and are never decisions. Priority decides whether they block generation (see "Story-generation gate").
4. If the gap register is missing, generation continues and the limitation is reported. If it is invalid, ask the user to correct it or explicitly proceed without gap context; if they proceed, do not claim gap relationships were checked.
5. The report shows story-to-requirement and gap-to-story traceability from the state and the register, in its own section.

## Story-generation gate

1. Every Critical and High gap must be `resolved` before stories are generated. An open or skipped Critical or High gap blocks generation.
2. Open or skipped Medium and Low gaps never block generation.
3. `/sdlc-pipeline:ba-run` enforces the gate (`pipeline-state.py gate`) on a first run and on every resume. The standalone `/sdlc-pipeline:ba-generate-stories` does not evaluate it; it works from the requirements as they stand and never decides an open gap.

## Ultra-lean stories

1. Generation and enrichment follow the standards in `story-writing-rules.md` and `acceptance-criteria-rules.md`: a concise 3-7 word summary and one short, high-level statement of the primary expected functional outcome.
2. Ultra-lean keeps the story's core intent and adds nothing unsupported. Detailed conditions, alternate flows, edge cases, exhaustive business rules, implementation notes, technical design and non-functional criteria are excluded from the document and kept in the detailed story, whose acceptance criteria are not duplicated.
3. The document and the detailed file hold no requirement IDs, gap IDs, decisions or priorities. Those stay in the internal state and in the report's own sections.

## Decision ledger and enrichment

1. A decision counts as incorporated only when the draft lists it in `decisions_reviewed` and (for `incorporated`) a story lists it in `applied_decisions`, or the agent explicitly determined that no story changes (`no_change_required`).
2. The ledger remembers which version of a decision (timestamp and hash) was reviewed, so a revised decision becomes pending again, and re-running with nothing new changes nothing.
3. Only confirmed decisions of resolved gaps are applied: to the relevant detailed story first, then to its ultra-lean story, which stays concise and functional. Unrelated stories and criteria are preserved, and nothing is duplicated.
4. If a resolved gap is reopened, never delete incorporated criteria automatically. Ask the user whether to retain, revise or remove them.
5. If a decision introduces a capability that cannot sensibly belong to an existing story, propose a new story and explain why. Do not create it silently when the relationship is uncertain.

## Manual edits and conflicts

1. Before writing, the script compares each story with the last synchronised version, separately for the ultra-lean story and the detailed story. A story edited by hand in either place, a story added or deleted by hand in either place, an ID changed by hand and edits outside the section are all detected.
2. Never overwrite or remove a manually edited ultra-lean or detailed story without the user's explicit consent for that story (`--overwrite`, `--allow-remove`, `--restore`). Show the current and proposed content (each conflict names its `representation`) and ask. Silent overwriting never happens.
3. For an edited story the user chooses one of three outcomes:
   - **Keep:** record the edit as it is. `accept` takes a hand-edited document entry or detailed story as the new baseline without touching the document. A kept detailed edit leaves the ultra-lean story flagged until it is updated.
   - **Reconcile:** `export` yields the detailed story from the detailed file and the lean criteria from the document; the agent updates the other representation so both agree (a detailed edit is carried into the ultra-lean story, a document edit is reflected in the detailed story), and `apply` writes the result. The agent sets `lean_reviewed` on a story whose ultra-lean version it re-derived or confirmed.
   - **Regenerate:** `apply --overwrite <ID>` replaces the edited version with the draft. The replaced file is kept in `stories/backups/`.
4. `sync-stories` records accepted manual edits in the state (`accept`) without touching the document. Stories that are new or unmapped need source requirement IDs confirmed with the user when they cannot be determined confidently. When a story is renamed or retired its detailed story follows the new ID or leaves `detailed_stories.md` (after a backup).
5. A section or a detailed stories file that breaks its contract (extra fields, bad or duplicate IDs, stray text, a heading without a short summary) is not updated until the user fixes it.

## Validation before completion

Story generation or synchronisation is complete only when all of these hold (`validate-development-stories.py --document <doc>`, `sync-development-stories.py summary`):

1. Every story in the supplied requirements document has a matching Story ID in `stories/detailed_stories.md`, and no detailed story is left without a matching entry.
2. The supplied document contains only Story ID, concise summary and one functional acceptance-criteria statement.
3. Story IDs and summaries match across both representations.
4. The detailed stories include the required functional and non-functional detail, and their criteria remain testable and keep confirmed rules and edge cases.
5. The HTML report sources story content from `stories/detailed_stories.md`.
6. Traceability and the hashes in the state are current (`in_sync` is true in `summary`).
7. Manual edits have not been silently overwritten.

## Safety

1. Pass `--expected-source-sha256` from `inspect` or `export` so a change made while work was in progress is never overwritten.
2. Ask before any destructive step: removing a story, overwriting a manual edit, changing the target document.
3. If the document write fails, the previous document, detailed stories and state are kept. If the state write fails after the document was saved, do not claim success; recover with `inspect` and `accept`.
4. If the report fails, the stories and state stay valid; say the report is stale and offer `/sdlc-pipeline:ba-generate-report`.
5. Report only counts that come from the scripts' JSON output.
6. Exit codes: `0` success, `1` refused (nothing changed), `2` I/O failure (nothing changed), `3` saved but report failed, `4` document and detailed stories saved but state not.

## Target document

Phase 1 does not record which Markdown files it analysed. In Phase 3 the target is chosen once and then remembered in the state.

1. One Markdown file was analysed: use it, after confirming with the user.
2. A directory or several files: ask the user to select the single primary document. Never append stories to every file. Traceability still covers requirements from all files because it works from requirement IDs.
3. If the recorded target is gone, ask the user to locate it. Never create a replacement silently.
