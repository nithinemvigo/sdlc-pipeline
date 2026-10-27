# Independent requirement parts + hook fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each requirements part a self-contained, independently deployable deliverable (no shared file), fix the context-budget hook's loose contract matching, and apply the final review's remaining fixes.

**Architecture:** Drop `00-shared.requirements.md` and every "shared" clause; parts carry their own full context and may only build on earlier, already-deployed parts. `/pipeline-all` builds one part per run, commits all approved part files on the first branch, warns if an earlier part is unmerged, and ends every run that leaves parts with the merge-then-next command. The hook's loose match ignores the common `.requirements` suffix and needs both stems ≥12 characters.

**Tech Stack:** Markdown prompts; Python 3 (`hooks/guard_context_budget.py`, `unittest`).

**Spec:** `docs/superpowers/specs/2026-10-27-requirements-writer-design.md` §11 (supersedes §2–§8 where they conflict).

## Global Constraints

- Branch `feature/pipeline-all`. No version bump. Never commit to `master`. Do not push.
- Do NOT modify `commands/pipeline.md`, `commands/pipeline-parallel.md`, `scripts/*`, `agents/distiller.md`, `agents/qa-placeholder.md`, manifests. `hooks/guard_context_budget.py` changes are limited to Task 1.
- No `00-shared` anywhere in `agents/`, `templates/`, `commands/pipeline-all.md` or `README.md` after this plan.
- Split threshold guide: more than ~40 acceptance criteria or more than ~10 user journeys (both split conditions still required); minimum part ~8 acceptance criteria.
- Part files: `docs/features/<slug>/NN-<part>.requirements.md`; NN = deploy order; part N uses IDs N01–N99.
- Next-part line, exactly: `Once this PR is merged and deployed, run /sdlc-pipeline:pipeline-all <next part path>.`
- Context-budget hook: files over 250 lines / 20,000 bytes are Read in chunks (offset/limit ≤200); never `cat`/`wc` them in Bash from a subagent. Never bypass the hook.
- Working copies use CRLF; Edit handles it.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` — exactly, whatever model you are.
- Validator: `claude plugin validate . 2>&1 | grep -c Found` → `14`; last line `✔ Validation passed with warnings`.

---

### Task 1: Hook loose-match fix (TDD)

**Files:**
- Create: `hooks/tests/test_contract_beside.py`
- Modify: `hooks/guard_context_budget.py` (inside `contract_beside`, ~lines 239–253, plus one helper above it)

- [ ] **Step 1: Write the failing test** — create `hooks/tests/test_contract_beside.py`:

```python
"""Loose contract matching in guard_context_budget.contract_beside.

Run from the repo root:  python -m unittest discover -s hooks/tests -v
"""
import importlib.util
import os
import tempfile
import unittest

HOOK = os.path.join(os.path.dirname(__file__), "..", "guard_context_budget.py")
spec = importlib.util.spec_from_file_location("guard_context_budget", HOOK)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ContractBesideTest(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        os.makedirs("docs/features/emv", exist_ok=True)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def touch(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x\n")

    def test_short_name_inside_longer_requirements_name_is_not_shadowed(self):
        self.touch("docs/features/export.requirements.contract.md")
        self.touch("docs/features/csv-export.requirements.md")
        self.assertIsNone(guard.contract_beside("docs/features/csv-export.requirements.md"))

    def test_unrelated_doc_is_not_shadowed_by_requirements_contract(self):
        self.touch("docs/features/user-auth.requirements.contract.md")
        self.touch("docs/auth.md")
        self.assertIsNone(guard.contract_beside("docs/auth.md"))

    def test_generic_requirements_doc_is_not_shadowed(self):
        self.touch("docs/features/billing.requirements.contract.md")
        self.touch("docs/requirements.md")
        self.assertIsNone(guard.contract_beside("docs/requirements.md"))

    def test_part_file_is_not_shadowed_by_other_feature(self):
        self.touch("docs/features/campaigns.requirements.contract.md")
        self.touch("docs/features/emv/02-campaigns.requirements.md")
        self.assertIsNone(guard.contract_beside("docs/features/emv/02-campaigns.requirements.md"))

    def test_exact_stem_contract_still_matches(self):
        self.touch("docs/features/export.requirements.contract.md")
        self.touch("docs/features/export.requirements.md")
        self.assertEqual(
            os.path.normpath(guard.contract_beside("docs/features/export.requirements.md")),
            os.path.normpath("docs/features/export.requirements.contract.md"),
        )

    def test_long_renamed_contract_still_matches(self):
        self.touch("docs/features/user-authentication-flow.contract.md")
        self.touch("docs/features/user-authentication-flow-spec.md")
        self.assertEqual(
            os.path.normpath(guard.contract_beside("docs/features/user-authentication-flow-spec.md")),
            os.path.normpath("docs/features/user-authentication-flow.contract.md"),
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and confirm the four "not shadowed" tests fail**

Run: `python -m unittest discover -s hooks/tests -v`
Expected: 4 failures (`test_short_name…`, `test_unrelated_doc…`, `test_generic_requirements…`, `test_part_file…`), 2 passes.

- [ ] **Step 3: Implement** — in `hooks/guard_context_budget.py`, add this helper directly above `def contract_beside`:

```python
def _loose_key(stem: str) -> str:
    """Normalised stem for the loose contract match.

    Strips a trailing `.requirements`: every requirements document shares it, and on its own
    it is 12 characters - enough to pass the length guard and match unrelated short names.
    """
    stem = re.sub(r"\.requirements$", "", stem, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", stem.lower())
```

Then in `contract_beside`, replace

```python
    norm = re.sub(r"[^a-z0-9]+", "", stem.lower())
```

with

```python
    norm = _loose_key(stem)
```

and replace

```python
            other = re.sub(r"[^a-z0-9]+", "", e[: -len(CONTRACT_SUFFIX)].lower())
            if len(other) >= 12 and (other in norm or norm in other):
```

with

```python
            other = _loose_key(e[: -len(CONTRACT_SUFFIX)])
            if len(other) >= 12 and len(norm) >= 12 and (other in norm or norm in other):
```

Read the function in a window first (Grep `def contract_beside`, Read ~50 lines) — the file is over 250 lines.

- [ ] **Step 4: Run tests — all 6 pass**

Run: `python -m unittest discover -s hooks/tests -v` → `OK` (6 tests).
Also: `python -c "import ast,sys; ast.parse(open('hooks/guard_context_budget.py',encoding='utf-8').read()); print('SYNTAX_OK')"` → `SYNTAX_OK`.

- [ ] **Step 5: Commit**

```bash
git add hooks/guard_context_budget.py hooks/tests/test_contract_beside.py
git commit -m "fix(hook): loose contract match ignores the .requirements suffix

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Agent, template and planner — independent parts

**Files:**
- Modify: `agents/requirements-writer.md`, `templates/requirements-template.md`, `agents/planner.md`

**Interfaces:**
- Produces: input `previous_proposal` (verbatim `parts` / `order` lines of the last proposal); `split_feedback` cumulative; return block without `shared`; `order` = deploy order + what each part uses from earlier parts. Task 3 relies on these names.

Read each file in windows; make these changes, keeping the file's voice:

- [ ] **Step 1: `agents/requirements-writer.md`**
  1. Frontmatter `description`: replace "one file, or a shared file plus a few parts when the feature is genuinely too big for one pipeline run" with "one file, or a few independently deployable parts when the feature is genuinely too big for one pipeline run".
  2. Inputs table: change `split_feedback` meaning to "the client's changes to your split proposal, verbatim and cumulative across rounds (draft only)"; add a row after it: `| previous_proposal | your last `parts` and `order` lines, verbatim — given with `split_feedback` (draft only) |`.
  3. Draft step 1 fallback Glob: replace "run one Glob for `**/templates/requirements-template.md` under `~/.claude/plugins`" with "run one Glob for `**/templates/requirements-template.md` with its path set to the absolute `.claude/plugins` folder in the user's home directory (Glob does not expand `~`)".
  4. Draft step 3, the `split_feedback` bullet → "`split_feedback` given → start from `previous_proposal`, apply every point of the feedback, and return `SPLIT_PROPOSAL` again."
  5. Draft step 4, the approved-split bullet → "Approved split → in `output_dir`: one `NN-<part-name>.requirements.md` per approved part (NN = 01, 02, … in deploy order; part name in kebab-case). There is no shared file."
  6. Replace the whole **Splitting rule** section body with:

```
One file is the default. Split only when **both** hold:

1. Each part can be **built, pushed and deployed on its own** and gives users value once
   deployed. A part may use what an **earlier, already-deployed** part shipped (for example
   part 2 uses the login part 1 delivered) — say so in its §21 Dependencies. A part never
   depends on a later part, and no two parts are needed together for anything to work.
2. One file would be too big for one pipeline run: as a guide, more than ~40 acceptance
   criteria or more than ~10 user journeys in total.

Never split by technical layer (frontend / backend / database), by screen, by create / edit /
delete of the same thing, or into steps of one user flow. Never create a part with fewer than
~8 acceptance criteria — merge it into its closest neighbour. Propose the fewest parts
possible, each with a one-line reason it cannot merge with another. If the feature cannot be
cut into independently deployable parts, or when in doubt, one file.
```

  7. Output rules, the "Split features" bullet and its sub-bullets → replace with:

```
- Split features: every part file is complete on its own — all 23 sections, with its own
  purpose, users and roles, rules, security, non-functional needs and acceptance criteria.
  Repeat what a part needs; never write "see another file". IDs are unique across the
  feature: part N uses N01–N99 (part 1: `BR-101`, part 2: `BR-201`). The coverage rules apply
  within each part.
```

  8. Return block: delete the `shared:` line; change the `order:` line to `order: deploy order + what each part uses from earlier parts   (SPLIT_PROPOSAL)`.

- [ ] **Step 2: `templates/requirements-template.md`** — replace the split-features comment bullet (the one mentioning `00-shared.requirements.md`) with:

```
- Split features: each part file is complete on its own; part N uses IDs N01–N99 (part 1:
  BR-101, part 2: BR-201). If a part uses what an earlier, already-deployed part shipped,
  say so in §21 Dependencies.
```

- [ ] **Step 3: `agents/planner.md`** — in Approved-requirements mode step 1, replace "(including a shared\n   `00-shared.requirements.md`)" so the sentence reads "when the orchestrator passes requirements originals, read them."

- [ ] **Step 4: Verify**

```bash
grep -c '00-shared' agents/requirements-writer.md templates/requirements-template.md agents/planner.md
grep -c 'previous_proposal' agents/requirements-writer.md
grep -c '~40 acceptance' agents/requirements-writer.md
grep -c '^## [0-9]\+\. ' templates/requirements-template.md
claude plugin validate . 2>&1 | grep -c Found
```

Expected: `0` for each file; `≥2`; `1`; `23`; `14`. (If the hook blocks a grep on a file you just edited, use the Grep tool.)

- [ ] **Step 5: Commit**

```bash
git add agents/requirements-writer.md templates/requirements-template.md agents/planner.md
git commit -m "feat: requirements parts are independent deliverables (no shared file)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `/pipeline-all` — independent parts and review fixes

**Files:**
- Modify: `commands/pipeline-all.md` (~650 lines — read in windows; Grep the anchors given)

Make each change minimal and in the file's voice; the 23 `## ` headings stay unchanged.

- [ ] **Step 1: Remove the shared file everywhere.** Grep `shared` and `SHARED`. Remove: `00-shared.requirements.md` from the part-path `ls`; recording `REQUIREMENTS_SHARED`; the "ignore `00-shared…`" clause in `part K of P`; "including `REQUIREMENTS_SHARED`" in the Request-changes `files`; the `shared` line in the `SPLIT_PROPOSAL` display; `REQUIREMENTS_SHARED` in step 6 ledger and the TOKEN LEDGER line; `shared` in the Stage Q dispatch; in Stage 0.8 the `<shared>` definition, "(with `<shared>` when set)", the whole "With `<shared>` …" paragraph and its bash block, and the distiller "When `<shared>` is set …" sentence; in Stage 1 "— and `<shared>` when set —" (make "originals" singular: "the original the planner may read"). After this, `grep -ci shared commands/pipeline-all.md` must be `0`.
- [ ] **Step 2: Earlier-part check (part-path branch of Stage R step 1).** Extend the same one Bash call with `git branch --list 'feature/<feature folder>-*' --no-merged <base branch>` (base = `main` or `master`, whichever exists). If a branch for a lower-NN part is listed, ask **Continue anyway** | **Stop** — "Part NN is not merged into <base> yet; this part may use what it ships." Also add `grep -c '^| Status | Approved |' <path>` to the same call: when it prints `1`, the part was approved earlier — record `(approved earlier)` and skip the step-4 question.
- [ ] **Step 3: `part K of P` scope.** Say it applies only to part files (`NN-*.requirements.md` in a feature folder); a top-level `docs/features/<name>.requirements.md` gets no part fields.
- [ ] **Step 4: Change the split.** In the `SPLIT_PROPOSAL` handling, "Change the split" re-dispatches with `previous_proposal` (the agent's last `parts` and `order` lines, verbatim), the cumulative `split_feedback`, and `question_round: 2`; "Approve split" and "Keep as one file" also pass `question_round: 2`. Capture the client's words for **Change the split** and **Request changes** from the free-text answer of the same `AskUserQuestion`, or one plain follow-up message if they gave none.
- [ ] **Step 5: Count dispatches.** In Stage R, add one line: "Increment `requirements_dispatches` on every `requirements-writer` dispatch."
- [ ] **Step 6: Commit requirements on the branch.** In Stage 3 step 1 (Grep `From latest main create`), add: "On a `/pipeline-all` run that wrote or approved requirements in Stage R, commit them as the branch's first commit: `git add <every requirements path from Stage R> && git commit -m \"docs: requirements for <slug>\"`. After a split this includes all parts, so later parts reach the base branch with this PR."
- [ ] **Step 7: Next-part line everywhere a run ends.** Replace the Stage 6 next-part sentence with: "If `REMAINING_PARTS` is not empty, end with: `Once this PR is merged and deployed, run /sdlc-pipeline:pipeline-all <next part path>.`" Change the hard rule about parts to: "One requirements part per run. Whenever a run ends — Stage 6 or any **Stop here** — and `REMAINING_PARTS` is not empty, end with the next-part line from Stage 6."
- [ ] **Step 8: Stage 2.5 wording.** Where Stage 2.5 writes "none reported" for requirements Open Questions, write "not available (existing file)" when Stage R returned no agent output (existing file or part path), and "none reported" only when the agent returned an empty list.
- [ ] **Step 9: Verify**

```bash
grep -n '^## ' commands/pipeline-all.md
grep -ci 'shared' commands/pipeline-all.md
grep -c 'previous_proposal' commands/pipeline-all.md
grep -c 'Once this PR is merged and deployed' commands/pipeline-all.md
grep -c 'no-merged' commands/pipeline-all.md
git diff --exit-code commands/pipeline.md commands/pipeline-parallel.md scripts agents/distiller.md agents/qa-placeholder.md .claude-plugin .cursor-plugin && echo PROTECTED_UNCHANGED
claude plugin validate . 2>&1 | grep -c Found
```

Expected: the same 23 headings; `0`; `≥1`; `≥1`; `1`; `PROTECTED_UNCHANGED`; `14`. Write `git diff -U3 HEAD -- commands/pipeline-all.md > "$TEMP/ip-t3.diff"` and read it in windows: every hunk maps to Steps 1–8.

- [ ] **Step 10: Commit**

```bash
git add commands/pipeline-all.md
git commit -m "feat: independent requirement parts in /pipeline-all

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: README

**Files:** Modify `README.md` (Example 4 paragraph beginning "The requirements agent asks you only about major gaps")

- [ ] **Step 1:** Replace "into a shared file plus a few parts in `docs/features/<slug>/`; each run builds one part and ends with the command for the next." with "into a few independent parts in `docs/features/<slug>/`, each complete on its own; each run builds one part, and once that PR is merged and deployed you run the next part with the command the run gives you."
- [ ] **Step 2:** `grep -c 'shared file' README.md` → `0`; commit:

```bash
git add README.md
git commit -m "docs: README describes independent requirement parts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Reinstall and manual run (user)

- [ ] `claude plugin update sdlc-pipeline@sdlc-pipeline-dev`, then a **new** session in a scratch git repo.
- [ ] Small idea → one file, approve, Status → Approved.
- [ ] EMV sample (`requirement (1).md`) → a split proposal of few independent parts (or one file if it cannot be cut that way); **Change the split** once ("merge parts 2 and 3") → the new proposal reflects it; approve → part files only (no `00-shared`); run builds part 1; stop at Stage 2.5.
- [ ] Next part path → unmerged-earlier-part warning appears (part 1 not merged), approved-earlier part skips approval.

## Spec coverage

| Spec §11 | Task |
|---|---|
| 11.1 no shared file, splitting rule, threshold, files | Task 2, Task 3 Step 1, Task 4 |
| 11.2 flow: next-part line, earlier-part check, skip re-approval, commit on branch, change the split | Task 3 Steps 2, 4, 6, 7 |
| 11.3 contract changes | Task 2 Step 1, Task 3 Steps 1, 3, 5, 8 |
| 11.4 hook fix | Task 1 |
