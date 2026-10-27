---
name: gap-identification
description: Method for finding genuine gaps in atomic requirements - missing, ambiguous, incomplete or conflicting information that needs a business decision - and writing each as a clear, answerable gap with its affected requirements. Use when analysing requirements for gaps or reconciling a gap register.
---

# Gap Identification

Follow `rules/gap-analysis-rules.md`. This skill is the method. A gap is a missing or unclear decision that a business stakeholder must supply. It is not a design choice that engineering can reasonably make, and it is not a prompt to improve the requirement.

## Dimensions to consider

Apply the ones that fit each requirement; most requirements need only a few.

| Dimension | Question |
|---|---|
| Completeness | Is there enough information to understand and implement the requirement? |
| Clarity | Is the wording precise, with only one reasonable interpretation? |
| Business rules | Are the rules, conditions and decision criteria defined? |
| Expected behaviour | Are triggers, inputs, processing and outcomes clear? |
| Exceptions | Are relevant failure paths and exceptional scenarios defined? |
| Constraints | Are thresholds, limits, timing and restrictions defined where they matter? |
| Dependencies | Does it depend on another requirement whose meaning is unclear? |
| Conflicts | Does it contradict another requirement or an explicit business rule? |

Do not detect gaps by keyword. "Timeout", "limit" or "should" in a requirement is not a gap by itself, and a requirement that omits a detail is not a gap unless the detail is a business decision that matters.

## Method

1. **Understand the whole set first.** Read every requirement before writing any gap, so you know what is already stated elsewhere.
2. **Walk each requirement.** For each, note what a builder and a tester would still have to ask the business. Check the related requirements before concluding that something is missing; drop questions that another requirement already answers.
3. **Separate decisions from design.** Keep a question only if the answer changes business behaviour, risk, compliance, cost, user outcome or the ability to verify the requirement. Leave technology, layout and internal structure to engineering.
4. **Consolidate.** Several symptoms of one missing decision are one gap (for example three requirements that all depend on an undefined lock-out policy). Unrelated decisions are separate gaps, even when they touch the same requirement.
5. **Write the definition.** State the missing decision so a stakeholder can answer it without reading the requirements. Ask every part of the decision (whether, how many, how long, who, what happens otherwise). Name the subject and the context; do not say "the above".
   - Weak: "What should happen with accounts?"
   - Better: "Should the system lock an account after repeated failed login attempts? If so, what is the maximum number of failed attempts and how long should the account remain locked?"
6. **Map the affected requirements.** List every requirement that is materially affected, not only the one that revealed the gap. Copy `requirement_id` and `description` exactly from the atomic requirements file. Do not list a requirement that is merely nearby.
7. **Prioritise** with the `gap-prioritisation` skill.
8. **Check for duplicates** across your finished list: same missing decision, same context, overlapping requirements. Merge them.

## What a gap definition must never do

- Choose the answer ("The lock-out should be five attempts. Is that right?").
- Imply a default taken from industry practice.
- Bundle several unrelated decisions into one gap.
- Merely say a requirement is incomplete, vague or "needs more detail".
- Contain acceptance criteria, user stories or implementation advice.

## Conflicts

For a conflict, name both statements and the decision needed to reconcile them ("REQ-007 says exports are available to all users; REQ-012 restricts exports to managers. Which applies?"). List both requirements as affected.

## Example

Requirements: REQ-001 "The system shall authenticate users using their registered email address and password." REQ-004 "The system shall prevent unauthorised access to user accounts."

One gap: the lock-out policy. Affected: REQ-001, REQ-004. Not three gaps (attempt limit, lock duration, unlock method) unless the stakeholder genuinely decides them independently; here they form one policy decision, so the definition asks for all of it.
