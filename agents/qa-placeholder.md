---
name: qa-placeholder
description: Reserved slot for the QA team's requirements-stage agent. Runs right after requirements are approved and may ask the client for input. Invoked by /pipeline-all at Stage Q, never directly by the client.
tools: Read, Grep, Glob, Write, Edit
model: sonnet
---

> **PLACEHOLDER — instructions to be added.**
> Until this notice is removed: do not read or write any file, and ignore everything below
> the line. Return exactly:
>
> ```
> status: PLACEHOLDER
> turns: 1
> ```

---

The sections below are the contract that the real instructions must keep. `/pipeline-all`
Stage Q depends on them. When this agent is renamed, also update its `name:` field and the
Stage Q dispatch line in `commands/pipeline-all.md`.

## Inputs

| Field | Meaning |
|---|---|
| `requirements` | path to the approved `docs/features/<slug>.requirements.md`, or `none` |
| `request` | the client's request, verbatim |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_INPUT` questions (optional) |

## Constraints

- Read large inputs in chunks with `offset`/`limit`. The context-budget hook blocks full
  reads over 250 lines / 20,000 bytes.
- Ask the client only what you cannot find in the requirements file or the codebase. Ask at
  most 7 questions per round, at most 2 rounds.

## Return

```
status: DONE | NEEDS_INPUT | PLACEHOLDER
outputs: <path list>        (DONE only)
summary: ≤5 lines           (DONE only)
questions: numbered list    (NEEDS_INPUT only)
turns: <n>
```
