---
name: story-enrichment
description: Incrementally update existing development stories from resolved gap decisions - finding the stories a decision affects, changing only what is needed, keeping IDs and unrelated criteria, handling revised and reopened decisions, and staying idempotent. Use when running /sdlc-pipeline:ba-enrich-stories.
---

# Story Enrichment

Enrichment is incremental. Never regenerate the stories. Follow `rules/story-management-rules.md` and `rules/acceptance-criteria-rules.md`.

## Inputs

- The `export` output: the stories as they are in the document, with mappings and an `edited_since_last_sync` flag.
- The `pending_decisions` list from `inspect`: for each resolved gap whose latest decision has not been reviewed yet - `gap_id`, `kind` (`new` or `revised`), the decision text, the affected requirements and candidate story IDs.
- The gap register (read only) for the full decision history when a decision was revised.

## Workflow, per pending decision

1. Read the gap definition, affected requirements and the **latest** decision (earlier entries are history).
2. Find the stories that are built from the affected requirements (candidate stories). A gap may affect several; consider each one.
3. For each candidate, compare the story as written with the decision. Does the decision change expected behaviour of **this** story?
   - Yes: update the description only if the capability itself changes; otherwise add or adjust acceptance criteria. Use the decision's own values.
   - No: leave the story alone. A shared category is not a reason to add a decision to a story.
4. Keep everything else: the story ID, the summary (unless the decision materially changes the capability), unrelated criteria, wording that is not affected. Do not reformat.
5. Do not duplicate: if an existing criterion already says what the decision says, change nothing and say so.
6. If the decision conflicts with an existing criterion, revise or remove that criterion and report which and why. If a criterion looks obsolete but you are not certain, ask.
7. If the decision introduces a capability that does not belong in any existing story, do **not** add a story silently. Describe the proposed story and the reason in `NEW_STORY_PROPOSALS`; the command asks the user. When the relationship is clear and the user approved, add it (`story_id: null`).
8. Record the outcome:
   - Stories changed: list the gap in each changed story's `applied_decisions`, and add `{"gap_id": ..., "outcome": "incorporated"}` to `decisions_reviewed`.
   - No story needs to change: add `{"gap_id": ..., "outcome": "no_change_required"}` and say why. Never count a decision as incorporated when no story reflects it.
9. Do not touch stories flagged `edited_since_last_sync` unless the decision requires it; if it does, propose the change instead of making it, because a manual edit must not be overwritten without consent.

## Revised decisions (`kind: revised`)

The latest decision replaces the earlier one for expected behaviour. Find the criteria that came from the earlier decision (compare with the earlier decision text in the gap history), update them, and keep the rest. Report what you changed.

## Reopened gaps

A gap that was resolved and is now open or skipped no longer supplies a confirmed decision, but its criteria stay until the user says otherwise. Never delete them yourself. The command asks the user to retain, revise or remove; do exactly what was chosen.

## Idempotency

Running enrichment again with no new or revised decisions must produce no change: no duplicated criteria, no new IDs, no reformatting, no rewrite of unrelated stories. When nothing is pending, the draft equals the export.

## Output

Start from the exported draft, change only the affected stories, and write the draft file. Validate it with `scripts/validate-development-stories.py`. Report as the agent's final response format describes, including what each decision did to which stories.
