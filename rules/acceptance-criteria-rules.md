# Acceptance Criteria Rules

Acceptance criteria define observable outcomes that can be validated independently. Every story has two sets: the **detailed** criteria in `stories/detailed_stories.md` (complete, testable, authoritative, in plain text) and a single **ultra-lean** statement derived from them for the requirements document. The quality bar applies to both; the form differs.

## Quality bar

Every criterion is:

1. **Specific and unambiguous.** Two testers would read it the same way. Numbers, limits and durations are stated, not implied.
2. **Testable.** There is an observable result: something the system does, shows, stores, rejects or prevents.
3. **Relevant** to its own story, **consistent** with the source requirements and with confirmed decisions, and **non-duplicative** (no two criteria in a story say the same thing).
4. **Supported.** It follows from a requirement or a resolved gap's latest decision. Do not invent behaviour to make a story look comprehensive. The only derived content is the valueless baseline security entries described in `security-baseline-rules.md`; they live in the story's Non-Functional Requirements, not in the criteria.

## Detailed criteria (plain text)

1. The detailed story carries all the criteria the behaviour needs. There is no upper limit: one criterion per business rule, validation, alternate flow, exception flow, boundary and security condition that the requirements or a confirmed decision state. Alternate and error behaviour is written here, as a criterion, and not repeated in another field.
2. Write each criterion as one plain sentence that a business reader and a tester understand the same way: the condition (when there is one) and the observable outcome. Example: "An unknown email address is rejected with a generic error message." Do not use Given / When / Then, step lists or scenario labels.
3. Each criterion is independently testable with a clear expected outcome and covers one behaviour.
4. A standing rule or constraint with no trigger is just as plain ("The system must not expose passwords in URLs, logs or error messages.").
5. State a precondition inside the criteria it affects. Do not hide it in the description alone.
6. Use the exact values from the requirements or the confirmed decision.
7. Non-functional requirements with a measurable target are testable too. State them in the story's Non-Functional Requirements field with the target, and add a criterion when the target can be checked in the same way as other behaviour.
8. Write each criterion as plain text. No numbering, bullets or Markdown headings; numbering is added when the story is written.

## Ultra-lean criteria (requirements document)

These apply to the ultra-lean version only, which is derived from the detailed story.

1. **One short, high-level statement**, not several bullets: it states the primary expected functional outcome from the user's perspective ("Users can log in with valid credentials and are prevented from accessing the system with invalid credentials."). Keep it clear and meaningful and preserve the story's core intent.
2. **Not Gherkin.** No Given / When / Then, no step-by-step scenarios, no bullets, no numbering.
3. Describe what the system must do, not how it is implemented. The statement is specific, observable and testable.
4. Exclude detailed conditions, alternate flows, edge cases and exhaustive business rules, as well as implementation notes, technical design and non-functional criteria (performance, availability, accessibility, security targets). Those stay in the detailed story.
5. Do not duplicate the detailed criteria: the statement summarises the outcome they verify and does not restate their conditions, values or rules.
6. Never contradict the detailed story and never add behaviour it lacks.

## What to consider (only where the requirements support it)

Successful behaviour, invalid input, failure outcomes, boundary conditions, permissions, business constraints, error handling, security and privacy expectations. If the requirements say nothing about a category, say nothing in the criteria; do not fill the silence. Security is the exception: the baseline controls are always derived into the Non-Functional Requirements (`security-baseline-rules.md`), and a criterion is added for one only when a requirement or confirmed decision states it.

## Unresolved and resolved gaps

1. **Open or skipped gap:** do not choose an answer. Do not turn a possible answer into a mandatory criterion. Write criteria only for behaviour the requirements support. If a behaviour cannot be specified without the decision, leave it out.
2. **Resolved gap:** the latest entry in `decisions_recorded` is the confirmed decision. Reflect it when it changes expected behaviour, using the user's numbers and wording, and only in the stories it actually affects.
3. A decision that cannot be turned into an observable criterion (for example a policy statement with nothing testable) is reported, not paraphrased into something testable that the user never decided.

## Changing existing criteria

1. Preserve unrelated criteria exactly.
2. Add or modify a criterion only when a confirmed decision or a requirement change requires it. Change the detailed story first, then bring the ultra-lean story into line.
3. Merge a decision into an existing criterion where it fits (same behaviour, same trigger) instead of adding a verbose duplicate. Add a new criterion only for a genuinely distinct behaviour.
4. Remove or revise a criterion only when it conflicts with a confirmed decision or is demonstrably obsolete, and say which and why.
5. Never add a criterion that duplicates an existing one; check meaning, not just wording. Applying the same decision twice changes nothing.
