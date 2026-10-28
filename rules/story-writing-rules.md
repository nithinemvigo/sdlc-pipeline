# Story Writing Rules

## Two representations of every story

Every story is written twice under one stable Story ID:

| Representation | Where | Role |
|---|---|---|
| **Detailed story** | `stories/detailed_stories.md`: one consolidated Markdown file holding every story | The complete, implementation-ready story: functional behaviour, business rules, testable acceptance criteria, scenarios and non-functional requirements. The HTML report is built from it. |
| **Ultra-lean story** | The `# Development Stories` section of the user's requirements document | A high-level, functional-oriented summary that keeps the requirements document short. Always derived from the detailed story. |

The ultra-lean story is a shortening of the detailed story, never a different story. Write the detailed story first, then derive the ultra-lean one. When a detailed story changes, its ultra-lean story is updated from it. Never create a separate Markdown file per story.

## The ultra-lean story (requirements document)

Exactly three things, nothing else:

| Field | Content |
|---|---|
| Story ID | `US-001` style, assigned by `scripts/sync-development-stories.py`; identical in both representations |
| Summary | A concise, meaningful one-line label of the story's core capability, typically 3-7 words (for example "Registered user login"); understandable at a glance, not a full sentence; **identical** in both representations |
| Acceptance criteria | **One** concise statement of the primary expected **functional** outcome, from the user's perspective |

Format (the scripts write it; you supply plain text):

```markdown
## US-001 — Registered user login

**Acceptance Criteria:** Users can log in with valid credentials and are prevented from accessing the system with invalid credentials.
```

Rules:

1. Keep the summary concise but descriptive (typically 3-7 words): a label of the core capability, neither a vague word nor a full explanatory sentence.
2. The criteria are **one statement**, not several bullets, scenarios or **Given/When/Then** (the validator rejects Gherkin and more than one statement). They describe what the system must do, not how it is implemented, and are specific, observable and testable.
3. State only the primary functional outcome in that one short statement and preserve the story's core intent. Detailed conditions, alternate flows, edge cases and exhaustive business rules live only in the detailed story and are not duplicated here. Never invent behaviour.
4. Exclude detailed scenarios, implementation notes, technical design and every non-functional criterion (performance, availability, accessibility, security targets and so on). Those live only in the detailed story. The requirements document holds functional stories only: a story whose summary or statement is a non-functional requirement (for example "Keyboard and accessible form use") is rejected by the validator; it belongs in the Non-Functional Requirements of the functional stories it constrains.
5. No description, no preconditions, no metadata of any kind. Requirement IDs, gap IDs, decisions, priorities and statuses never appear in a story.

## The detailed story (`stories/detailed_stories.md`)

The file holds one section per story, in Story ID order. Every story has the same fields, in this order. The required fields are always present; an optional field with nothing to say is left out of the story (no `Not specified.` lines):

| Field | Content | Required |
|---|---|---|
| Heading | `## US-001 — <the same short summary>` | yes |
| Description | The user need as `As a [user], I want [capability], so that [benefit].` | yes |
| Preconditions | What must be true before the story applies | no |
| Functional Behaviour | The detailed behaviour the system must provide | yes |
| Business Rules | Rules, limits and constraints with their exact values | no |
| Acceptance Criteria | Complete, independently testable criteria in plain text, not Given/When/Then (see `acceptance-criteria-rules.md`) | yes |
| Alternate and Error Scenarios | Alternate or error flow notes that no acceptance criterion already states (normally none) | no |
| Non-Functional Requirements | Applicable quality attributes with measurable targets | no |
| Dependencies | Other stories (always with their Story ID), systems, data, roles or decisions the story depends on | no |

Rules:

1. Include only details supported by the atomic requirements and by the latest decision of a resolved gap. Never invent an answer for an unresolved gap, and never add placeholders, "TBD" or open questions.
2. Keep functional and non-functional requirements with the story they belong to. A non-functional requirement that constrains one story goes in that story's Non-Functional Requirements; one that applies to several is stated in each of them.
3. **A non-functional requirement is never a story of its own.** Performance, availability, accessibility (keyboard use, labelled fields, readable errors), usability, compliance, scalability and similar quality attributes are written into the Non-Functional Requirements of every functional story they constrain (a requirement that applies to all forms goes in each story with a form), and the requirement is listed in those stories' sources. They never appear in the requirements document: not as a story, not in a summary and not in a lean criterion. A system story ("As the system, I must ...") is only for functional system behaviour that no user story carries (for example a scheduled job or a notification), never for a quality attribute.
4. Do not copy requirement IDs, gap IDs or decision metadata into the story text. Say what the rule is, not where it came from.
5. Preserve conditions, limits and values exactly as the requirements and decisions state them.

### Dependencies

1. A dependency on another story names that story by **Story ID and summary**, then says what is needed from it ("US-001 (Registered user login): the user must be logged in before a reset can be requested").
2. In the draft, write the other story as `[[Exact summary of that story]]`. The sync script replaces it with `US-001 (Registered user login)` once every story has its ID, so a new story can be referenced before it has one. An existing story in the draft may also be written by its ID. The validator rejects a reference to a story that is not in the draft and a story that depends on itself.
3. List a dependency once, on the story that needs the other (the dependent), not on both.
4. Systems, data, roles and decisions are named in plain text. A decision is described by what was decided, never by a gap ID.
5. Only list a dependency the requirements or a confirmed decision support.

### Keeping the detailed story lean

1. Say each thing once, in the field it belongs to: what the system does in Functional Behaviour, rules and limits in Business Rules, how it is verified (including alternate and error behaviour) in Acceptance Criteria. Do not restate a rule in every field.
2. One short, plain sentence per item. No background narrative, filler or repeated wording.
3. Leave an optional field out when the requirements say nothing for it. Alternate and Error Scenarios is for flow notes no criterion already states.
4. Leaner never means less: every confirmed rule, value, limit, exception, security condition and non-functional target stays in the story.

The draft format that carries both representations is in `schemas/development-stories.schema.json` and `skills/story-generation/SKILL.md`. Supply plain text only: no numbering, no bullets, no headings and no `**Label:**` lines inside a field.

## Decomposition

1. Understand the business capability behind each atomic requirement before writing anything.
2. Group closely related requirements into one story when they describe one cohesive user outcome.
3. Split requirements that are independently deliverable capabilities.
4. Do not generate one story per requirement mechanically. A story is neither too broad to implement and test, nor so small that it has no meaningful outcome of its own.
5. Keep business rules and constraints. Express technical or system constraints as non-functional requirements of the functional stories they constrain, rather than dropping them or making a story of them (see rule 3 of the detailed story).
6. One requirement may appear in several stories when they cover different capabilities; one story may draw on several requirements.
7. Do not write two stories for the same capability.
8. Every atomic requirement ends up in at least one story, or is listed in `not_covered_requirements` with a reason. Silence is not an option.

## Wording

1. Actor: use the actor named in the requirements; an administrator or the system where that is what the requirement describes. Do not invent a persona.
2. Value ("so that ..."): use only a value the requirements support. If the actor or value is unclear, use a neutral, accurate formulation instead of guessing.
3. Be precise. Avoid "handle appropriately", "as expected", "user-friendly", "as appropriate", "TBD" unless the requirements make the term measurable.
4. No implementation detail the requirements do not state (technologies, screens, tables, endpoints).
5. A story must be understandable without opening the source requirement.

## Unresolved gaps

1. An open or skipped gap is not a decision and never changes a story's text. (Whether story generation may start at all is decided by the story-generation gate in `story-management-rules.md`.)
2. Write only what the requirements and resolved decisions support. Do not choose an answer, and do not turn a plausible answer into a rule.
3. If an unresolved decision prevents one behaviour from being specified, leave that behaviour out. Do not add a placeholder criterion, a "TBD" or a question to the story.
4. If an unresolved gap stops the whole story from being meaningfully defined, keep the known capability, say plainly in the detailed description what is not yet defined, and write no invented criteria.
5. Only a resolved gap's latest recorded decision is a confirmed business decision. A skipped gap is never a decision.
