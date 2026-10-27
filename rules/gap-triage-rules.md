# Gap Triage Rules

## Statuses

| Status | Meaning | In the triage queue? |
|---|---|---|
| `open` | Not yet resolved. | Yes |
| `skipped` | Intentionally deferred during triage. Still unresolved. | Yes, in a later or resumed session |
| `resolved` | The user gave a decision and confirmed it. | No, unless the user explicitly asks to reopen it |

A skipped gap is never counted, shown or described as resolved.

## Allowed transitions (only these)

| Action | From | To | Decision recorded? |
|---|---|---|---|
| Provide a confirmed decision | `open`, `skipped` | `resolved` | Yes, appended |
| Revise a decision | `resolved` | `resolved` | Yes, appended (explicit user request only) |
| Skip this gap | `open` | `skipped` | No |
| Reopen | `resolved`, `skipped` | `open` | No (history kept) |
| Skip all remaining | none | none | No |

Anything else is refused. A resolved gap is not skipped; reopen it first.

## Decision history

1. `decisions_recorded` is append-only. Never overwrite, edit, reorder or delete an entry.
2. The latest entry is the current decision.
3. Record the decision in the user's meaning and, as far as practical, in their words. Do not add detail the user did not give. Do not turn a likely answer into a decision.
4. Each entry gets an ISO 8601 `recorded_at` with a timezone offset, created by the store script when it saves.
5. A gap becomes `resolved` only after the user has confirmed the captured decision text. Typing an answer is not confirmation.

## Triage session

1. **Order:** Critical, High, Medium, Low; within a priority, ascending gap number. Take the order from the store's `list` output, do not re-sort.
2. **One gap at a time.** Show the ID, priority, definition, affected requirement IDs and descriptions, and progress ("Gap 2 of 12").
3. **Persist every change immediately** through `scripts/gap-register-store.py`. It validates, saves atomically, reads back and regenerates the HTML. Never edit `gaps.json` or the HTML by hand.
4. **Skip all remaining** is a session control, not a decision. Write nothing for the remaining gaps: skipped ones stay skipped, unreviewed ones stay open.
5. **Cancel** (the user stops) preserves everything already saved and ends the session with a summary.
6. **Resume** by running the command again. Load, validate, queue open and skipped gaps, start at the highest priority. Never repeat a recorded decision or create duplicates.
7. **No re-analysis.** Triage never runs gap analysis. If the store reports that the atomic requirements changed, tell the user to run `/sdlc-pipeline:ba-analyse-gaps` and stop.
8. **If a save fails** the last valid register is kept. Tell the user exactly what failed, do not claim the change was made, and offer to retry. If the report fails but the JSON saved (exit code 3), say so and offer `regenerate-report`.

## Session summary

Report numbers taken from the store (`summary`) and your session tally: gaps presented; resolved this session; skipped this session; still open; currently skipped; total resolved; paths of `gaps/gaps.json` and `gaps/gap-analysis.html`. Never describe skipped gaps as resolved.
