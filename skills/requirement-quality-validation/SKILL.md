---
name: requirement-quality-validation
description: Validate a drafted atomic requirements JSON array for structure, ID rules, duplicates, atomicity, independent understandability and source coverage. Use before saving requirement output.
---

# Requirement Quality Validation

Validation has two parts. The script proves the structure; you prove the meaning.

## Part 1: Structural validation (script)

Run the validator on the draft:

```text
python <plugin-root>/scripts/validate-atomic-requirements.py <draft.json>
```

(Use `python3` or `py` if `python` is not available.) It checks:

- valid JSON syntax; the root is an array of objects;
- exactly the properties `requirement_id`, `title`, `description` on each object;
- all values are non-empty strings;
- IDs match `^REQ-[0-9]{3,}$`, are unique, and run sequentially from `REQ-001` for initial generation.

It exits non-zero and prints actionable messages on failure. Fix every error in the draft and run it again until it passes. If Python is missing, stop and ask the user before installing anything.

`schemas/atomic-requirement.schema.json` is the same contract in JSON Schema form. The script uses only the standard library, so no extra dependency is needed.

## Part 2: Semantic validation (you)

The script cannot judge these. Check each one against the source and fix the draft until all pass.

1. **Atomicity.** Each requirement holds one independently verifiable expectation. Descriptions with "and"/"or" joining different capabilities, or with several conditions leading to different outcomes, are suspect.
2. **No fragmentation.** No requirement is a fragment that only makes sense next to another.
3. **Independent understanding.** Each title and description is clear without the source or neighbouring items. No dangling references ("as above", "it", "this").
4. **Duplicates and near-duplicates.** Compare all pairs, including titles. Merge only if the meaning is genuinely equivalent; otherwise make the difference explicit.
5. **Meaning preserved.** Conditions, constraints, limits, actors, exact messages and outcomes match the source. No requirement says more than the source does.
6. **No invention.** Nothing in the output is an assumption, a default or a decision the source does not state. "May"/"could" in the source did not become "shall".
7. **Coverage.** Walk the source again, section by section, tables and lists included. Every expectation maps to a requirement. Anything skipped is non-requirement content, and you can say which.
8. **Contract.** No extra metadata, no wrapper object, no acceptance criteria, gaps or questions.

## Reporting

Summarise the result: validator status, number of requirements, duplicates merged, ambiguities preserved as written, content deliberately skipped, and any limitation (for example a file only partly read). Never report coverage you did not check.
