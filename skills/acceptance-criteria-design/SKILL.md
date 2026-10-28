---
name: acceptance-criteria-design
description: Design testable acceptance criteria for a development story - complete plain-text criteria for the detailed story, one short, high-level functional statement for the ultra-lean story, coverage of success, failure, boundary and security behaviour, and how to treat open, skipped and resolved gaps without inventing decisions. Use whenever acceptance criteria are written or revised.
---

# Acceptance Criteria Design

Follow `rules/acceptance-criteria-rules.md`. This skill is the working method.

Every story has two sets of criteria. Design the **detailed** set first: complete criteria in plain text (no Given/When/Then), no upper limit. Then derive the **ultra-lean** set for the requirements document (steps 6-7): one short, high-level functional statement of the primary outcome, not Gherkin and not a copy of the detailed criteria.

## Steps

1. **List what the requirements state** for the story: actions, conditions, limits, rules, constraints, who may do what.
2. **Turn each statement into an observable outcome.** Ask: what would a tester see, measure or be unable to do? If nothing is observable, the statement is a constraint to phrase declaratively or it is too vague to test (report that; do not make it up).
3. **Choose the form for the detailed set.** One plain sentence per criterion: the condition (if there is one) and the observable outcome, in everyday business wording ("An unknown email address is rejected with a generic error message."). No Given / When / Then, no step lists. A standing rule with no trigger is written the same way ("The system must not expose passwords in URLs, logs or error messages.").
4. **Cover only what is supported.** Where the requirements address them, include: the normal outcome, invalid input, failure and error outcomes, boundaries (limits, empty, maximum), permissions, security and privacy expectations. If the requirements are silent on a category, leave it out.
5. **Use exact values.** Copy numbers, durations, limits and names from the requirements or from the confirmed decision. Do not round, soften or extend them.
6. **One behaviour per detailed criterion.** Split checks that have different outcomes ("validates input" and "sends the email"). Combine closely related checks that share the same behaviour and outcome (several required fields rejected in the same way) into one criterion. Measurable non-functional targets go in the story's non-functional requirements and, where they can be checked like other behaviour, in a criterion.
7. **Derive the ultra-lean statement.** One short, high-level statement of the primary expected functional outcome from the user's perspective ("Users can log in with valid credentials and are prevented from accessing the system with invalid credentials."). Plain language; no bullets; no Given/When/Then; no detailed conditions, alternate flows, edge cases, exhaustive business rules, implementation notes or non-functional criteria; do not duplicate the detailed criteria; preserve the story's core intent.
8. **Check for duplicates and conflicts** within the story and against the other criteria already present.

## Gap handling

| Gap status | What you do |
|---|---|
| Open | Write criteria for supported behaviour only. Leave the undecided behaviour out. Do not add "TBD". |
| Skipped | Same as open. A skipped gap is not a decision. |
| Resolved | The latest entry of `decisions_recorded` is confirmed. Add or adjust the criteria it implies, with the user's values, in the stories it materially affects (detailed first, then the ultra-lean statement if a high-level functional outcome changes). |

If an unresolved gap prevents the whole story from being defined, keep the known capability, state the limitation in the detailed description, and write no invented criteria.

## Example

Requirement: "The system shall authenticate users using their registered email address and password."
Open gap: "Should the account lock after repeated failures?"

Good detailed criteria (supported behaviour only):

1. Valid credentials grant access.
2. Invalid credentials are denied access.

The matching ultra-lean statement:

- Users can log in with valid credentials and are prevented from accessing the system with invalid credentials.

Not acceptable: "The account is locked for 30 minutes after five failed attempts." This is a guess until the gap is resolved with exactly that decision.

After the user resolves the gap with "Lock the account after five consecutive failed login attempts for 30 minutes", add one detailed criterion (the lock and its expiry are one rule, so they are not two). The ultra-lean statement stays as it is, because the lock is a detailed condition and not the primary outcome:

- After five consecutive failed login attempts the account is locked, and it unlocks after 30 minutes.
- (lean) Unchanged: "Users can log in with valid credentials and are prevented from accessing the system with invalid credentials."

If detailed criterion 2 already covered failed attempts, a decision that only refines that behaviour is merged into it instead of becoming a near-duplicate.

The example is illustrative; derive real criteria from the recorded decision and the source context.
