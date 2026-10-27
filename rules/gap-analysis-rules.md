# Gap Analysis Rules

## Quality and traceability

1. **Analyse everything.** Every atomic requirement is considered. The analysis is by meaning, not by keyword.
2. **Genuine gaps only.** Keep missing or unclear information that needs a business answer or decision. Do not list design choices engineering can make, stylistic preferences or restatements of requirements.
3. **No invention.** Do not invent rules, behaviour or assumptions. Do not infer a definitive answer from common practice. Do not add an assumed decision anywhere.
4. **Consider related requirements** before creating a gap. Do not ask what another requirement already answers.
5. **One missing decision, one gap.** Consolidate symptoms of the same decision. Never combine unrelated decisions.
6. **Independently answerable.** Each `gap_definition` states the missing decision completely and is specific enough for a stakeholder to answer (see `skills/gap-identification/SKILL.md`).
7. **Complete traceability.** Every gap lists all materially affected requirements. Each entry carries the exact `requirement_id` and `description` from `atomic_requirements/atomic_requirements.json`. Every gap has at least one.
8. **One priority.** Exactly one of `Critical`, `High`, `Medium`, `Low`, assigned with `skills/gap-prioritisation/SKILL.md`. No rationale field in the register.
9. **No decisions, stories or criteria.** Gap analysis never resolves a gap, records a decision, writes user stories or writes acceptance criteria.

## Register contract

1. `gaps/gaps.json` is a JSON array. Each gap has exactly `gap_id`, `priority`, `status`, `gap_definition`, `decisions_recorded`, `affected_requirements`. Decisions have exactly `decision` and `recorded_at`; affected requirements have exactly `requirement_id` and `description`. No other property anywhere. Schema: `schemas/gap-register.schema.json`.
2. New gaps are `open` with `decisions_recorded: []`.
3. IDs are `GAP-001` style. A new register is numbered sequentially from `GAP-001`.
4. When reconciling, matched gaps keep their IDs, statuses and decisions. New gaps get IDs above the highest number ever used. IDs of removed or retired gaps are never reused and nothing is renumbered.

## Artifacts

1. **Project-local output.** Write to `<project-root>/gaps/` only, never the plugin directory.
   - `gaps/gaps.json` — the authoritative register.
   - `gaps/gap-analysis.html` — a generated, read-only view.
   - `gaps/gap-analysis-state.json` — internal control file (input hash, timestamp, versions, requirement fingerprints, highest gap number). It is not a gap and not shown as one.
   - `gaps/retired-gaps.json` — created only if the user approves retiring a gap whose requirements were removed.
2. **Read-only inputs.** The atomic requirements file and the original source documents are never modified in Phase 2.
3. **Validate before and after writing.** Drafts live in a temporary directory outside the project and the plugin. Everything is saved through `scripts/gap-register-store.py`, which validates, writes atomically, reads back and regenerates the report. Do not hand-write `gaps.json`, the state file or the HTML.
4. **No silent overwrite.** An existing register is reused or reconciled, never replaced by a fresh analysis. A destructive reset needs explicit user confirmation after you explain what is lost. The store backs up before a reset.
5. **Stale input.** Before reusing or updating a register, compare the atomic requirements with the saved analysis state. Changed input means reconciliation.

## Reconciliation safeguards

1. A decision is never altered, removed or reworded by analysis.
2. A resolved gap stays resolved only if the user confirms that the recorded decision still addresses the changed requirement or wording. Otherwise it goes back to `open` with its decision history intact.
3. If a gap's meaning changed materially, create a new gap with a new ID instead of reusing the old one.
4. Never delete a gap silently. A gap whose requirements were all removed is kept (re-pointed to a surviving requirement the user names) or retired to `gaps/retired-gaps.json` only after the user approves that extension of the agreed schema.
5. Match old and new gaps by missing decision, context and affected requirements. If you cannot match confidently, ask the user.
6. Show the user every material change before committing it: reopened gaps, resolved gaps whose meaning or requirements changed, gaps proposed for retirement.

## Reporting

Report counts calculated from the saved files, never illustrative numbers. Say "Validation: Passed" only when the validators ran and passed.
