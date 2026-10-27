---
name: gap-triage
description: Guided one-at-a-time triage of requirement gaps - presenting a gap, capturing and confirming a business decision, skipping one gap or all remaining gaps, reopening a resolved gap and resuming later. Use when running /sdlc-pipeline:ba-triage-gaps.
---

# Gap Triage

Follow `rules/gap-triage-rules.md` for statuses, transitions and decision history. This skill is the conversation method. All reads and writes of the register go through `scripts/gap-register-store.py`; use `python`, `python3` or `py`, whichever works.

Commands used below (each takes `--project-root <project root>`):

```text
python <plugin-root>/scripts/gap-register-store.py list
python <plugin-root>/scripts/gap-register-store.py resolve --gap-id GAP-001 --decision-file <file> [--revise]
python <plugin-root>/scripts/gap-register-store.py skip --gap-id GAP-001
python <plugin-root>/scripts/gap-register-store.py reopen --gap-id GAP-001
python <plugin-root>/scripts/gap-register-store.py summary
python <plugin-root>/scripts/gap-register-store.py regenerate-report
```

Each prints JSON with `ok`. Exit 0 = done, 1 = refused (nothing changed), 2 = I/O failure (nothing changed), 3 = register saved but the HTML report failed.

## Presenting a gap

Show, in plain readable text:

```text
Gap 2 of 12 — GAP-005 — Critical (skipped earlier)

<gap_definition>

Affected requirements:
- REQ-001: <description>
- REQ-004: <description>

Previous decisions: <only if the gap was reopened; show them with dates>
```

Then offer the actions in words, not as a long menu:

- give the decision (the user may simply type it),
- skip this gap,
- skip all remaining gaps (ends the session),
- reopen a resolved gap,
- stop.

## Capturing a decision

1. Ask for the business decision, or take the text the user typed.
2. Check it against the gap definition. If the gap asks "whether, how many, how long" and the answer covers only part, ask one focused follow-up for the missing part. Ask again only if still unclear.
3. Treat these as not yet decisions, and offer to skip instead of recording them: "I don't know", "TBD", "ask someone else", "whatever is standard".
4. Do not propose a business answer, fill gaps with your own assumptions or choose between alternatives for the user. You may restate ambiguity and ask which meaning is intended.
5. Write the captured decision as the user's decision, in clear language and without added detail. Show it back and ask for confirmation with AskUserQuestion: "Confirm and record", "Change the wording", "Do not record". Only "Confirm and record" resolves the gap.
6. After confirmation, write the decision text to a file in the session's temporary directory with the Write tool, then run `resolve --gap-id ... --decision-file <file>`. Passing a file avoids shell quoting problems.
7. Read the JSON result. On success say that the decision was recorded and the gap is resolved, and that the report was regenerated. On any failure say what failed and that nothing was recorded; offer to retry.
8. Move to the next gap.

## Skip this gap

Run `skip --gap-id`. Say it is marked skipped, remains unresolved and will return in the next triage session. Move on.

## Skip all remaining gaps

Make no store call for the remaining gaps. Say that they keep their current status (skipped stays skipped, unreviewed stays open) and that nothing was resolved by this. Go to the session summary. Only changes already confirmed and saved in this session exist.

## Reopen a resolved gap

Only when the user asks. If no ID was given, ask which gap. Run `reopen --gap-id`. Say that its decision history is kept and that it is open again. Ask whether to revisit it now; if yes, present it next, otherwise continue.

## Revise a decision

Only when the user asks to change a recorded decision. Capture and confirm the new decision as above, then run `resolve --revise`. The old entry stays in the history; the new one becomes current.

## Resume

When a session starts and the queue already contains skipped gaps, say how many are open and how many were skipped before. Resolved gaps are not shown. If the queue is empty, say that no open or skipped gaps remain and show the summary counts.

## Session tally

Keep a count in the conversation of: gaps presented (each at most once per session), gaps resolved, gaps skipped (by this session's actions). The end summary also uses `summary` for the register's real totals.
