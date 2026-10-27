# Story Writing Rules

## Four fields, nothing else

Every story in the `# Development Stories` section has exactly:

| Field | Content |
|---|---|
| Story ID | `US-001` style, assigned by `scripts/sync-development-stories.py` |
| Summary | One concise line naming the capability or outcome |
| Detailed Description | The user need and expected capability, in the user-story form where it fits |
| Acceptance Criteria | Observable, testable conditions (see `acceptance-criteria-rules.md`) |

Never add source requirement IDs, gap IDs or statuses, priority, decisions, story status, owner, tags or any other metadata to a story. Requirement-to-story and gap-to-story mappings live only in `stories/story-generation-state.json`; gaps and decisions are shown in the HTML report, in their own sections.

## Format

```markdown
## US-001

**Summary:** <one line>

**Detailed Description:**
As a <actor>, I want <capability> so that <outcome>.

**Acceptance Criteria:**

1. <criterion>

2. <criterion>
```

The scripts write this layout. You supply plain text only: no numbering, no headings, no `**Label:**` lines, and no leading `#` inside a field.

## Decomposition

1. Understand the business capability behind each atomic requirement before writing anything.
2. Group closely related requirements into one story when they describe one cohesive user outcome.
3. Split requirements that are independently deliverable capabilities.
4. Do not generate one story per requirement mechanically. A story is neither too broad to implement and test, nor so small that it has no meaningful outcome of its own.
5. Keep business rules and constraints. Express technical or system constraints as a technical or system story (for example "As the system, I must ...") rather than dropping them.
6. One requirement may appear in several stories when they cover different capabilities; one story may draw on several requirements.
7. Do not write two stories for the same capability.
8. Every atomic requirement ends up in at least one story, or is listed in `not_covered_requirements` with a reason. Silence is not an option.

## Wording

1. Actor: use the actor named in the requirements; an administrator or the system where that is what the requirement describes. Do not invent a persona.
2. Value ("so that ..."): use only a value the requirements support. If the actor or value is unclear, use a neutral, accurate formulation instead of guessing.
3. Preserve conditions, limits and constraints exactly as the requirement states them.
4. Be precise. Avoid "handle appropriately", "as expected", "user-friendly", "as appropriate", "TBD" unless the requirements make the term measurable.
5. No implementation detail the requirements do not state (technologies, screens, tables, endpoints).
6. A story must be understandable without opening the source requirement.

## Unresolved gaps

1. Open and skipped gaps never block a story.
2. Write only what the requirements and resolved decisions support. Do not choose an answer, and do not turn a plausible answer into a rule.
3. If an unresolved decision prevents one behaviour from being specified, leave that behaviour out. Do not add a placeholder criterion, a "TBD" or a question to the story.
4. If an unresolved gap stops the whole story from being meaningfully defined, keep the known capability, say plainly in the description what is not yet defined, and write no invented criteria.
5. Only a resolved gap's latest recorded decision is a confirmed business decision. A skipped gap is never a decision.
