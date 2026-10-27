---
name: acceptance-criteria-design
description: Design testable acceptance criteria for a development story - Given/When/Then and declarative forms, coverage of success, failure, boundary and security behaviour, and how to treat open, skipped and resolved gaps without inventing decisions. Use whenever acceptance criteria are written or revised.
---

# Acceptance Criteria Design

Follow `rules/acceptance-criteria-rules.md`. This skill is the working method.

## Steps

1. **List what the requirements state** for the story: actions, conditions, limits, rules, constraints, who may do what.
2. **Turn each statement into an observable outcome.** Ask: what would a tester see, measure or be unable to do? If nothing is observable, the statement is a constraint to phrase declaratively or it is too vague to test (report that; do not make it up).
3. **Choose the form.**
   - Scenario with a trigger: *Given* the situation, *when* the action, *then* the observable result.
   - Rule or constraint: a direct statement ("The system must not expose passwords in URLs, logs or error messages.").
4. **Cover only what is supported.** Where the requirements address them, include: the normal outcome, invalid input, failure and error outcomes, boundaries (limits, empty, maximum), permissions, security and privacy expectations. If the requirements are silent on a category, leave it out.
5. **Use exact values.** Copy numbers, durations, limits and names from the requirements or from the confirmed decision. Do not round, soften or extend them.
6. **Keep each criterion to one outcome.** Split "validates input and sends the email" into two.
7. **Check for duplicates and conflicts** within the story and against the other criteria already present.

## Gap handling

| Gap status | What you do |
|---|---|
| Open | Write criteria for supported behaviour only. Leave the undecided behaviour out. Do not add "TBD". |
| Skipped | Same as open. A skipped gap is not a decision. |
| Resolved | The latest entry of `decisions_recorded` is confirmed. Add or adjust the criteria it implies, with the user's values, in the stories it materially affects. |

If an unresolved gap prevents the whole story from being defined, keep the known capability, state the limitation in the description, and write no invented criteria.

## Example

Requirement: "The system shall authenticate users using their registered email address and password."
Open gap: "Should the account lock after repeated failures?"

Good (supported behaviour only):

1. Given a registered user provides valid credentials, when the user submits the login form, then the system authenticates the user and grants access.
2. Given a user provides invalid credentials, when the user submits the login form, then the system rejects the login attempt.
3. The system must not expose passwords in URLs, logs or error messages. *(only if the requirements or a decision say so)*

Not acceptable: "Given five failed attempts, then the account is locked for 30 minutes." This is a guess until the gap is resolved with exactly that decision.

After the user resolves the gap with "Lock the account after five consecutive failed login attempts for 30 minutes", add:

3. Given a user has made five consecutive failed login attempts, when another login attempt is made, then the system locks the account.
4. Given an account is locked, when 30 minutes have passed, then the account is no longer locked.

The example is illustrative; derive real criteria from the recorded decision and the source context.
