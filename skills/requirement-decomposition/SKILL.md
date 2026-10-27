---
name: requirement-decomposition
description: Break a requirements source into atomic requirements, each with a requirement_id, title and description, without inventing detail or fragmenting coherent expectations. Use when decomposing requirement text.
---

# Requirement Decomposition

Follow `rules/atomic-requirement-rules.md` and `rules/requirement-id-rules.md`. This skill is the method.

## Principles

- One distinct expectation per atomic requirement.
- Each requirement is independently understandable.
- Each description is clear and verifiable to the extent the source supports.
- Preserve business intent, conditions, constraints and outcomes.
- Do not invent missing details.
- Do not split merely because a statement has several sentences.
- Do not merge requirements with distinct conditions or outcomes.
- Avoid duplicates and unnecessary fragmentation.

## Method

1. **Understand first.** Read the complete source set before writing anything. Note the business objective, actors, scope and vocabulary.
2. **Inventory expectations.** Walk the source section by section and list every functional requirement, non-functional requirement, business rule, validation, constraint, integration and external-system expectation. Tables, lists and code blocks can carry requirements, so include them.
3. **Test each candidate for atomicity.** Ask: does this contain more than one thing that could be built, changed or verified independently? Look for:
   - several capabilities joined by "and" or commas (register, log in, reset password, update profile);
   - one capability with different conditions or outcomes (success versus failure, different roles);
   - a rule bundled with the behaviour it governs, when the rule is independently checkable.
4. **Split by meaning.** Create one requirement per independent expectation. Do not split a coherent expectation whose parts make no sense alone, such as a single flow whose steps depend on each other, or a validation with its error message.
5. **Write each requirement.**
   - `title`: a short, meaningful name (for example "Password Reset"), not a sentence.
   - `description`: a self-contained statement, normally "The system shall ...". Carry over the conditions, limits, actors, thresholds and exact messages the source gives. Resolve pronouns and "as above" references to concrete subjects.
   - Do not add priority, category, rationale, source reference, acceptance criteria or open questions.
6. **Handle ambiguity.** If the source is vague, keep the vague statement as written. Do not choose an interpretation, fill in a number, or turn "may", "could" or an assumption into "shall".
7. **Consolidate.** Compare all requirements pairwise for duplicates and overlap. Merge only when two statements mean the same thing; otherwise keep both and make the difference explicit in the descriptions.
8. **Order and number.** Keep source order. Assign `REQ-001`, `REQ-002`, ... sequentially (see the ID rules). IDs never come from titles.
9. **Check coverage.** Re-read the source against the list. Every expectation must map to at least one requirement. Add what is missing; note any non-requirement content you skipped.

## Example

Source: "The system shall allow users to register, log in, reset their password, and update their profile."

Four requirements: User Registration, User Authentication, Password Reset, Profile Update, each with a description that stands alone and adds no detail the source does not state.

A statement such as "Passwords must be at least 8 characters and the system shows 'Password too short' otherwise" stays one requirement: the rule and its message belong together.

## Anti-patterns

- Splitting every sentence or bullet into its own requirement.
- Merging "login succeeds" and "login fails" into one requirement.
- Descriptions like "The system shall support this as described above".
- Adding "reasonable" defaults such as timeouts, formats or limits the source never states.
- Dropping non-functional requirements or constraints because they are not features.
