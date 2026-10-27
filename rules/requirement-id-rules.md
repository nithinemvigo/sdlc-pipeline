# Requirement ID Rules

## Format

```text
REQ-001
REQ-002
REQ-003
```

1. IDs must match `^REQ-[0-9]{3,}$`.
2. IDs are unique within the output.
3. Initial generation numbers requirements sequentially from `REQ-001` with no gaps, in the order the requirements appear in the source (source files in the confirmed order). Use at least three digits; after `REQ-999` continue with `REQ-1000`.
4. Never derive an ID from a title or description.

## Existing analyses

1. If `atomic_requirements/atomic_requirements.json` already exists, do not claim the new IDs match the old ones. IDs are stable across runs only if the new decomposition is actually compared with the previous output, which this phase does not do.
2. Never silently renumber an existing analysis. When an output exists, explain that a fresh ID assignment will be performed, that IDs may differ from the previous file, and obtain the user's confirmation before replacing it.
3. Do not alter the IDs of an existing file as a side effect of any other step.
