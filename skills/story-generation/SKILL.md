---
name: story-generation
description: Turn atomic requirements into coherent development stories - grouping and splitting by business capability, writing the detailed functional and non-functional story and deriving the ultra-lean story, deciding coverage, and producing the structured draft the sync script writes into the requirements document and stories/detailed_stories.md. Use when running /sdlc-pipeline:ba-generate-stories or when new requirements need stories.
---

# Story Generation

Follow `rules/story-writing-rules.md`, `rules/acceptance-criteria-rules.md` and `rules/security-baseline-rules.md`; design criteria with the `acceptance-criteria-design` skill. This skill is the method.

Every story is written in two representations under one Story ID: the **detailed story** (complete functional and non-functional detail, saved in the single file `stories/detailed_stories.md`) and an **ultra-lean story** (Story ID, a concise summary and one short, high-level acceptance-criteria statement of the primary functional outcome, saved in the requirements document). Write the detailed story first, then derive the ultra-lean one from it.

## Inputs

- `atomic_requirements/atomic_requirements.json` (read only).
- The gap register, if available (read only): used to know which decisions are confirmed and which gaps are open or skipped.
- For a project that already has stories: the `export` output (the detailed stories from `detailed_stories.md` with the lean criteria from the document, their mappings, and which were edited by hand or need their ultra-lean version updated).

## Method

1. **Read everything first.** Read all atomic requirements before drafting any story. List the business capabilities they describe (what a user, administrator or the system can do or must guarantee) and the quality attributes that constrain them (performance, security, availability, accessibility, audit).
2. **Map requirements to capabilities.** Several requirements often describe one outcome (login, credential rules and failed-attempt handling). One requirement can describe two capabilities. Decide the grouping on meaning, not on order or numbering.
3. **Size each story.** Aim for something one team can build and test as a unit and that delivers a meaningful outcome on its own. Split when parts can be delivered or tested independently; merge when a piece has no outcome of its own.
4. **Place non-functional requirements.** Attach each non-functional requirement to the story it constrains (its `non_functional_requirements`). One that applies to several stories is stated in each (accessibility of forms goes in every story with a form), and the requirement's ID goes in those stories' `source_requirement_ids`. **A non-functional requirement is never a story of its own**: no story, summary or lean criterion is created for it, because the requirements document holds functional stories only (the validator rejects it). A system story ("As the system, I must ...") is only for functional system behaviour no user story carries. No non-functional requirement is dropped: the detailed story file holds them all. **Security is always derived, even when no requirement mentions it:** for each story, add the `Security (baseline): ` entries its behaviour calls for, following `rules/security-baseline-rules.md` (no numbers or other invented values; a security rule that a requirement or decision states is written as stated instead). Other quality attributes (performance, availability, accessibility and so on) are included only when a requirement or decision states them; do not add any when the requirements are silent.
5. **Write the detailed story** (the `detailed` object of the draft story).
   - `description`: the user need as `As a <actor>, I want <capability>, so that <benefit>.`
   - `preconditions`: what must be true first (empty list when the requirements state none; an empty optional field is left out of the file).
   - `functional_behaviour`: what the system does, as short separate items. Keep conditions, limits and values exactly. State the checks (alternate and error behaviour) in the acceptance criteria, not here.
   - `business_rules`: the rules and constraints that apply, with their exact values. Say each rule once.
   - `acceptance_criteria`: from the `acceptance-criteria-design` skill: complete, independently testable criteria for every supported rule, validation, alternate and error flow, boundary and security condition, each one plain sentence of condition and expected outcome. No Given/When/Then. No upper limit.
   - `scenarios`: only alternate or error flow notes that no acceptance criterion already states; normally an empty list.
   - `non_functional_requirements`: the baseline security entries (each starting `Security (baseline): `), then the other applicable quality attributes with their measurable targets, only where a requirement or decision states them.
   - `dependencies`: what this story needs, when known. Another story is written `[[Exact summary of that story]]` followed by what is needed from it; the script turns it into `US-001 (Summary)`, so the dependency carries the Story ID. List it once, on the dependent story. Systems, data, roles and decisions are plain text. Never use requirement or gap IDs.
   - Add nothing unsupported. Never invent an answer for an open or skipped gap. Use an empty list for an optional field the requirements say nothing about; the field is then left out of the file. Keep it lean: one short sentence per item, each thing said once in the field it belongs to, and nothing confirmed dropped.
6. **Derive the ultra-lean story** (`summary` and `lean_acceptance_criteria`) from the detailed story.
   - `summary`: a concise, meaningful one-line label of the core capability, typically 3-7 words ("Registered user login"), understandable at a glance and not a full sentence. The same text is the heading of the story in both representations.
   - `lean_acceptance_criteria`: an array holding exactly **one** short, high-level statement of the primary expected functional outcome from the user's perspective, in plain language (for example "Users can log in with valid credentials and are prevented from accessing the system with invalid credentials."). Not several bullets, not Given/When/Then. No detailed conditions, alternate flows, edge cases, exhaustive business rules, implementation detail or non-functional criteria, and do not duplicate the detailed acceptance criteria.
   - Keep the story's core intent and stay clear and meaningful; do not contradict the detailed story or add behaviour it lacks. Detailed rules live only in the detailed story.
7. **Respect gaps.** For each story look at the gaps whose affected requirements it covers (the script derives the same relation). Open and skipped: write only what the requirements support and leave the undecided behaviour out. Resolved: read the latest decision in `decisions_recorded`; if it changes expected behaviour of this story, include it (and list the gap in `applied_decisions`, and in `decisions_reviewed`).
8. **Account for every requirement.** Each requirement is in some story's `source_requirement_ids`, or in `not_covered_requirements` with a reason (for example "a statement of scope, not a capability to build").
9. **Check for duplicates.** No two stories for the same capability; no two with the same summary.
10. **Check consistency.** Before saving: the detailed story is complete, supported and lean (nothing said twice, no Given/When/Then, every story-to-story dependency names the other story); the lean statement is one short, high-level functional outcome that does not repeat the detailed criteria; the detailed story lost no confirmed functional rule or required exception; the ultra-lean story does not contradict the detailed story or lose its core intent; no non-functional criterion leaked into the lean statement; every new story has the baseline security entries its behaviour calls for, with no number or other invented value; nothing is repeated or unsupported.
11. **Validate.** Write the draft file and run `scripts/validate-development-stories.py <draft> --project-root <root>` (add `--no-gaps` only when the user chose to proceed without gap context). Fix every error. Treat warnings as a prompt to improve the wording.

## Draft format

A JSON object, UTF-8, two-space indent (schema: `schemas/development-stories.schema.json`):

```json
{
  "stories": [
    {
      "story_id": null,
      "summary": "Registered user login",
      "lean_acceptance_criteria": [
        "Users can log in with valid credentials and are prevented from accessing the system with invalid credentials."
      ],
      "detailed": {
        "description": "As a registered user, I want to log in with my registered email address and password so that I can access my account.",
        "preconditions": ["The user has a registered account."],
        "functional_behaviour": [
          "The system authenticates the user against the registered email address and password.",
          "A successful login grants access to the authenticated area."
        ],
        "business_rules": ["A rejected login does not reveal whether the email address or the password was wrong."],
        "acceptance_criteria": [
          "Valid credentials grant access and show the authenticated area.",
          "An unknown email address is denied access with a generic error message.",
          "A wrong password for a registered email address is denied access with the same generic error message."
        ],
        "scenarios": [],
        "non_functional_requirements": [
          "Security (baseline): Passwords are never exposed in URLs, logs or error messages.",
          "Security (baseline): A failed authentication gives a generic error that does not reveal which value was wrong.",
          "Security (baseline): Failed and successful authentication attempts are recorded in the audit log.",
          "Login completes within 2 seconds under normal load."
        ],
        "dependencies": []
      },
      "lean_reviewed": false,
      "source_requirement_ids": ["REQ-001"],
      "applied_decisions": []
    }
  ],
  "not_covered_requirements": [],
  "decisions_reviewed": []
}
```

- `story_id: null` for every new story. Never invent an ID: the script assigns the next unused one.
- Only the keys above. No priority, status, owner, tags or gap fields. The `source_requirement_ids` and `applied_decisions` keys are for the internal state only.
- `summary` is shared; `lean_acceptance_criteria` (one statement) goes into the requirements document; `detailed` goes into `stories/detailed_stories.md`. Always supply all three.
- `lean_reviewed: true` says the ultra-lean story was re-derived from the detailed story in this run, or checked and found still current. Set it on every story the export flags `lean_needs_update` or whose detailed story you changed; leave it out otherwise.
- A dependency on another story in the draft is written with that story's exact summary in double square brackets, for example `"[[Registered user login]]: the user must be logged in before a reset can be requested."` It is saved as `US-001 (Registered user login): the user must be logged in before a reset can be requested.` A summary that is not in the draft, or the story's own summary, fails validation. An existing story may also be named by its ID.
- Every value is plain text. Separate paragraphs of the `description` with a blank line. No numbering, no bullets, no Markdown headings, no `**Label:**` lines inside a value.
- The example is illustrative: the "authenticated area", "generic error message" and "2 seconds" outcomes belong in a real story only when the requirements or a resolved decision state them. The `Security (baseline):` entries are the exception: they are derived for every story whose behaviour calls for them (`rules/security-baseline-rules.md`), and the "2 seconds" line is the kind of entry that appears only because a requirement states it.

## Re-running on a project that has stories

Do not start over. Take the exported draft as the starting point and keep every existing story exactly as it is unless a change is required:

- Requirements with no story yet: add new stories (`story_id: null`).
- A requirement that changed: update only the stories built from it (detailed first, then the ultra-lean story), and say what changed.
- A requirement that was removed: do not delete its story yourself. Report it so the user can decide; if the story should also cover other requirements, remove only the removed ID from its sources.
- Stories the user edited by hand (`lean_edited` or `detailed_edited` in the export context): copy them unchanged from the export. Propose changes to them in your report instead of making them. A hand-edited detailed story is authoritative: the ultra-lean story is brought into line with it once the user agrees (`lean_reviewed: true`); a hand-edited document entry is reflected in the detailed story only with the user's consent.
- A story the export gives `"detailed": null` (`detailed_missing`: added to the document by hand, or `legacy_layout` from an earlier plugin version) needs its detailed story written from the atomic requirements and confirmed decisions; keep its ID and summary, rewrite its lean criteria in the ultra-lean form, and report it.
- Nothing needs to change: leave the draft equal to the export. That is a valid, idempotent result.
