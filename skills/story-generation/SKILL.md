---
name: story-generation
description: Turn atomic requirements into coherent development stories - grouping and splitting by business capability, writing the summary and user-story description, deciding coverage, and producing the structured draft the sync script writes into the requirements document. Use when running /sdlc-pipeline:ba-generate-stories or when new requirements need stories.
---

# Story Generation

Follow `rules/story-writing-rules.md` and `rules/acceptance-criteria-rules.md`; design criteria with the `acceptance-criteria-design` skill. This skill is the method.

## Inputs

- `atomic_requirements/atomic_requirements.json` (read only).
- The gap register, if available (read only): used to know which decisions are confirmed and which gaps are open or skipped.
- For a project that already has stories: the `export` output (current stories, their mappings, and which were edited by hand).

## Method

1. **Read everything first.** Read all atomic requirements before drafting any story. List the business capabilities they describe (what a user, administrator or the system can do or must guarantee).
2. **Map requirements to capabilities.** Several requirements often describe one outcome (login, credential rules and failed-attempt handling). One requirement can describe two capabilities. Decide the grouping on meaning, not on order or numbering.
3. **Size each story.** Aim for something one team can build and test as a unit and that delivers a meaningful outcome on its own. Split when parts can be delivered or tested independently; merge when a piece has no outcome of its own.
4. **Handle constraints.** Technical or system requirements (logging, performance, security rules) become technical or system stories ("As the system, I must ...") or criteria of the story they constrain. They are not dropped.
5. **Write the story.**
   - Summary: one line, the capability, not a task.
   - Detailed Description: `As a <actor>, I want <capability>, so that <outcome>.`, plus any further paragraph needed to make the story understandable without the source requirement.
   - Acceptance Criteria: from the `acceptance-criteria-design` skill.
6. **Respect gaps.** For each story look at the gaps whose affected requirements it covers (the script derives the same relation). Open and skipped: write only what the requirements support and leave the undecided behaviour out. Resolved: read the latest decision in `decisions_recorded`; if it changes expected behaviour of this story, include it (and list the gap in `applied_decisions`, and in `decisions_reviewed`).
7. **Account for every requirement.** Each requirement is in some story's `source_requirement_ids`, or in `not_covered_requirements` with a reason (for example "a statement of scope, not a capability to build").
8. **Check for duplicates.** No two stories for the same capability; no two with the same summary.
9. **Validate.** Write the draft file and run `scripts/validate-development-stories.py <draft> --project-root <root>` (add `--no-gaps` only when the user chose to proceed without gap context). Fix every error. Treat warnings as a prompt to improve the wording.

## Draft format

A JSON object, UTF-8, two-space indent (schema: `schemas/development-stories.schema.json`):

```json
{
  "stories": [
    {
      "story_id": null,
      "summary": "User authentication with registered credentials",
      "description": "As a registered user, I want to log in using my registered email address and password, so that I can securely access my account.",
      "acceptance_criteria": [
        "Given a registered user provides valid credentials, when the user submits the login form, then the system authenticates the user and grants access.",
        "Given a user provides invalid credentials, when the user submits the login form, then the system rejects the login attempt."
      ],
      "source_requirement_ids": ["REQ-001"],
      "applied_decisions": []
    }
  ],
  "not_covered_requirements": [],
  "decisions_reviewed": []
}
```

- `story_id: null` for every new story. Never invent an ID: the script assigns the next unused one.
- Only the keys above. No priority, status, owner, tags or gap fields.
- `description` and criteria are plain text. No numbering, no Markdown headings, no `**Label:**` lines.

## Re-running on a project that has stories

Do not start over. Take the exported draft as the starting point and keep every existing story exactly as it is unless a change is required:

- Requirements with no story yet: add new stories (`story_id: null`).
- A requirement that changed: update only the stories built from it, and say what changed.
- A requirement that was removed: do not delete its story yourself. Report it so the user can decide; if the story should also cover other requirements, remove only the removed ID from its sources.
- Stories the user edited by hand: copy them unchanged from the export. Propose changes to them in your report instead of making them.
- Nothing needs to change: leave the draft equal to the export. That is a valid, idempotent result.
