# Acceptance Criteria Rules

Acceptance criteria define observable outcomes that can be validated independently.

## Quality bar

Every criterion is:

1. **Specific and unambiguous.** Two testers would read it the same way. Numbers, limits and durations are stated, not implied.
2. **Testable.** There is an observable result: something the system does, shows, stores, rejects or prevents.
3. **Relevant** to its own story, **consistent** with the source requirements and with confirmed decisions, and **non-duplicative** (no two criteria in a story say the same thing).
4. **Supported.** It follows from a requirement or a resolved gap's latest decision. Do not invent behaviour to make a story look comprehensive.

## Form

1. Use Given / When / Then when it clarifies the behaviour: *Given* the starting condition, *when* the action or event, *then* the observable outcome. One scenario per criterion.
2. Use a direct declarative statement for rules and constraints that need no scenario ("The system must not expose passwords in URLs, logs or error messages.").
3. Write each criterion as plain text. No numbering, bullets or Markdown headings; numbering is added when the story is written.
4. Keep a criterion to one outcome. Split a criterion that tests two unrelated things.

## What to consider (only where the requirements support it)

Successful behaviour, invalid input, failure outcomes, boundary conditions, permissions, business constraints, error handling, security and privacy expectations. If the requirements say nothing about a category, say nothing; do not fill the silence.

## Unresolved and resolved gaps

1. **Open or skipped gap:** do not choose an answer. Do not turn a possible answer into a mandatory criterion. Write criteria only for behaviour the requirements support. If a behaviour cannot be specified without the decision, leave it out.
2. **Resolved gap:** the latest entry in `decisions_recorded` is the confirmed decision. Reflect it when it changes expected behaviour, using the user's numbers and wording, and only in the stories it actually affects.
3. A decision that cannot be turned into an observable criterion (for example a policy statement with nothing testable) is reported, not paraphrased into something testable that the user never decided.

## Changing existing criteria

1. Preserve unrelated criteria exactly.
2. Add or modify a criterion only when a confirmed decision or a requirement change requires it.
3. Remove or revise a criterion only when it conflicts with a confirmed decision or is demonstrably obsolete, and say which and why.
4. Never add a criterion that duplicates an existing one; check meaning, not just wording.
