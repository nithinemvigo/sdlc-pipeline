# Atomic Requirement Rules

These rules are mandatory for every decomposition. The `requirement-decomposition` skill explains how to apply them.

## Output contract

1. The output is a JSON array of objects. Each object has exactly three properties: `requirement_id`, `title`, `description`.
2. Do not add category, priority, source reference, assumptions, dependencies, status, acceptance criteria, questions or any other property.
3. Do not wrap the array in a metadata object.

## Decomposition standards

1. **One expectation per object.** Each object states one distinct business or system expectation.
2. **Analyse meaning, not syntax.** Never split by sentence, bullet, punctuation or keyword. Split when the source expresses independently verifiable capabilities, rules or outcomes; keep together what is one coherent expectation.
3. **Preserve source conditions and outcomes.** Triggers, conditions, limits, thresholds, exact messages, actors, timings and results stated in the source stay in the description.
4. **No fragmentation.** Do not break a coherent expectation into pieces that cannot be understood alone.
5. **No merging.** Do not combine expectations that have different conditions, actors or outcomes.
6. **No assumptions.** Do not invent requirements, business decisions, values or details. Do not turn an assumption into a confirmed requirement. If the source is ambiguous, state only what it explicitly says.
7. **Independently understandable.** A reader who has not seen the source must understand the title and description. Replace pronouns and references such as "as above" or "this feature" with the concrete subject.
8. **Retain constraints and business rules.** Validations, limits, integrations, external system expectations and non-functional requirements are requirements in their own right and must be captured.
9. **Detect duplicates and overlaps.** Consolidate only when two statements are genuinely equivalent in meaning. When statements overlap but differ, keep both and make the difference explicit.
10. **No knowing omissions.** Every expectation in the source is represented. Content that is not a requirement (headings, narrative background, document history) may be skipped; anything skipped that could be mistaken for a requirement is reported to the user.
11. **Verifiable wording.** Write descriptions as clear statements, normally "The system shall ...", as verifiable as the source supports. Do not add measurable criteria the source does not give.

## Out of scope for this phase

Do not produce gaps, questions, user stories, acceptance criteria, enrichment or edits to the source document.
