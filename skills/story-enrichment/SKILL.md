---
name: story-enrichment
description: Incrementally update existing development stories from resolved gap decisions - finding the stories a decision affects, changing only what is needed in the detailed story and its ultra-lean story, keeping IDs and unrelated criteria, handling revised and reopened decisions, and staying idempotent. Use when running /sdlc-pipeline:ba-enrich-stories.
---

# Story Enrichment

Enrichment is incremental. Never regenerate the stories. Follow `rules/story-management-rules.md` and `rules/acceptance-criteria-rules.md`.

## Preconditions

Enrichment applies only confirmed decisions from resolved gaps. In the master pipeline every Critical and High gap is already resolved before stories exist; Open or Skipped Medium and Low gaps stay out of the stories. Enrichment touches only the affected parts of a story and preserves the story ID, the summary and unrelated criteria.

## Inputs

- The `export` output: for each story the detailed story (from `stories/detailed_stories.md`) and its lean criteria (from the document), with mappings and the flags `lean_edited`, `detailed_edited`, `lean_needs_update` and `edited_since_last_sync`.
- The `pending_decisions` list from `inspect`: for each resolved gap whose latest decision has not been reviewed yet - `gap_id`, `kind` (`new` or `revised`), the decision text, the affected requirements and candidate story IDs.
- The gap register (read only) for the full decision history when a decision was revised.

## Workflow, per pending decision

1. Read the gap definition, affected requirements and the **latest** decision (earlier entries are history).
2. Find the stories that are built from the affected requirements (candidate stories). A gap may affect several; consider each one.
3. For each candidate, compare the detailed story as written with the decision. Does the decision change expected behaviour of **this** story?
   - Yes: **update the detailed story first.** Put the decision where it belongs: a rule in `business_rules`, behaviour in `functional_behaviour`, a testable outcome in `acceptance_criteria` (merge it into an existing criterion where it fits; add one only for a genuinely distinct behaviour), an alternate or error flow in `scenarios`, a quality target in `non_functional_requirements`. Update the description only if the capability itself changes. Use the decision's own values. Then **derive the matching change in the ultra-lean story**, only when the decision changes the primary functional outcome of the story, and keep it one short, high-level functional statement without the decision's detailed conditions. A decision that is purely detail (a limit, an alternate flow, an edge case, a business rule) or purely non-functional changes the detailed story only. Set `lean_reviewed: true`.
   - No: leave both versions alone. A shared category is not a reason to add a decision to a story.
4. Keep everything else: the story ID, the summary (unless the decision materially changes the capability; it changes in both versions), unrelated criteria, wording that is not affected. Do not reformat.
5. Do not duplicate: if an existing item already says what the decision says, change nothing and say so. If one covers the same behaviour but lacks the decision's detail, merge the detail into it rather than appending a verbose second one. Do this in the detailed story and in the lean statement (a decision is merged into the one statement, never added as a second item).
6. If the decision conflicts with an existing criterion or rule, revise or remove it and report which and why. If something looks obsolete but you are not certain, ask.
7. If the decision introduces a capability that does not belong in any existing story, do **not** add a story silently. Describe the proposed story and the reason in `NEW_STORY_PROPOSALS`; the command asks the user. When the relationship is clear and the user approved, add it (`story_id: null`).
8. Record the outcome:
   - Stories changed: list the gap in each changed story's `applied_decisions`, and add `{"gap_id": ..., "outcome": "incorporated"}` to `decisions_reviewed`.
   - No story needs to change: add `{"gap_id": ..., "outcome": "no_change_required"}` and say why. Never count a decision as incorporated when no story reflects it.
9. Do not touch stories flagged `edited_since_last_sync` (`lean_edited` or `detailed_edited`) unless the decision requires it; if it does, propose the change instead of making it, because a manual edit must not be overwritten without consent.

## Revised decisions (`kind: revised`)

The latest decision replaces the earlier one for expected behaviour. Find the items that came from the earlier decision (compare with the earlier decision text in the gap history), update them in the detailed story and, where they surface there, in the ultra-lean story, and keep the rest. Report what you changed.

## Reopened gaps

A gap that was resolved and is now open or skipped no longer supplies a confirmed decision, but its criteria stay until the user says otherwise. Never delete them yourself. The command asks the user to retain, revise or remove; do exactly what was chosen.

## Idempotency

Running enrichment again with no new or revised decisions must produce no change: no duplicated criteria or rules, no new IDs, no reformatting, no rewrite of unrelated stories. When nothing is pending, the draft equals the export.

## Output

Start from the exported draft, change only the affected stories (the detailed story first, then its ultra-lean story), and write the draft file. Validate it with `scripts/validate-development-stories.py`. Report as the agent's final response format describes, including what each decision did to which stories.
