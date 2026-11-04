# Security Baseline Rules

Security is always considered, whether or not the requirements mention it. Story generation derives a **baseline** of security controls from what each story's functional behaviour does and states them in that story's Non-Functional Requirements in `stories/detailed_stories.md`. Gap analysis raises a gap only for a security decision that needs a business value (see "Where gaps come in").

## What the baseline is

1. A baseline entry is a **control that must exist**, stated without any business value: "Passwords are never exposed in URLs, logs or error messages." It is derived from the story's observed behaviour, not from keywords alone.
2. Every baseline entry starts with the exact prefix `Security (baseline): ` so a reader can tell it from a security requirement the business stated. Example: `Security (baseline): Passwords are never exposed in URLs, logs or error messages.`
3. It is a non-functional requirement: it goes in the detailed story's `non_functional_requirements` only. It is never a story of its own, never a summary and never in the ultra-lean criteria of the requirements document (`story-writing-rules.md`, detailed story rule 3).
4. It is not a business decision, so it does not wait for gap triage and it is not blocked by an open or skipped gap.

## What a baseline entry must never contain

1. **No invented values.** No numbers, durations, counts, thresholds, algorithm or product names, standards or regulations. "The account is locked after repeated failed attempts" is a control; "after five attempts for 30 minutes" is a business decision and belongs to a gap or a resolved decision. The validator warns when a baseline entry contains a digit.
2. **No contradiction.** If a requirement or a resolved gap's latest decision states a security rule for the same control, state that rule instead (without the `Security (baseline):` prefix, with its exact values) and do not add a baseline entry for the same control.
3. **No duplication.** One short sentence per entry. Say each control once per story. Do not restate it in the acceptance criteria unless a requirement or decision states it there.
4. **No implementation detail.** Say what is protected, not which technology protects it.

## Deriving the entries

Read each story's functional behaviour and add the entries for every row that applies. A story can match several rows. Group closely related controls into one sentence rather than listing many.

| The story... | Baseline entries (wording is a model, adapt it to the story) |
|---|---|
| Authenticates users or handles credentials | `Security (baseline): Passwords and other credentials are never exposed in URLs, logs or error messages.` `Security (baseline): A failed authentication gives a generic error that does not reveal which value was wrong.` `Security (baseline): Failed and successful authentication attempts are recorded in the audit log.` |
| Limits what an actor may see or do (roles, ownership, administration) | `Security (baseline): Every request is authorised on the server against the actor's role and ownership, and an unauthorised request is denied and recorded.` |
| Accepts input (forms, uploads, parameters, imported data) | `Security (baseline): All input is validated on the server and invalid input is rejected without being processed.` For uploads add: `Security (baseline): Uploaded files are checked for allowed type and size before they are accepted.` |
| Stores, shows or sends personal, financial or otherwise sensitive data | `Security (baseline): Sensitive data is protected when stored and when transmitted, is not written to logs, and is shown only to actors allowed to see it.` |
| Uses sessions, tokens or links that grant access (login session, password reset, invitation) | `Security (baseline): Sessions and access tokens are tied to the authenticated user, are ended on logout, and are not exposed in URLs.` For one-time links add: `Security (baseline): A one-time link or token can be used only for its purpose, cannot be guessed, and expires.` (the validity period is a business value: see below) |
| Creates, changes, deletes, approves, exports or configures anything | `Security (baseline): Each such action is recorded in the audit log with who performed it, what changed and when, and audit entries cannot be altered by the actor.` |
| Calls or is called by another system | `Security (baseline): Communication with the other system is authenticated and protected in transit.` |
| Shows errors or messages to the actor | `Security (baseline): Error messages do not disclose internal details such as system paths, queries or stack traces.` |

If a story matches none of the rows (for example it only displays fixed public content), it gets no baseline entry. Say so in the agent report instead of adding a filler line.

## Where gaps come in

A control that needs a business value is a gap, not a baseline guess. Gap analysis raises one gap per undecided parameter when a requirement involves the behaviour and no requirement states the value. Examples: the failed-login lock-out limit and duration, the session inactivity limit, password composition and expiry rules, the validity period of a reset link, who may read the audit log and how long it is kept, whether multi-factor authentication is required, which fields count as sensitive. The baseline entry for the same control stays valueless ("expires") until a decision supplies the value; then the decision is applied like any other (`acceptance-criteria-rules.md`, resolved gap).

Gap analysis does not raise a gap merely because security is not mentioned; the baseline already covers it. It raises a gap only for a decision the business must make.

## Other quality attributes

Performance, availability, accessibility, usability, compliance and similar attributes are not derived. They appear in a story's Non-Functional Requirements only when a requirement or a resolved decision states them, and nothing is added when the requirements are silent.

## Existing stories

1. On `generate`, every new story gets its baseline entries.
2. On `reconcile` and `enrich`, add baseline entries only to a story that is already being changed in this run, or to a new story. Do not touch any other existing story, and never change a story edited by hand.
3. List every existing story that has no baseline although its behaviour matches a row under `STORIES NEEDING THE USER'S ATTENTION`, so the user can ask for it to be added.
