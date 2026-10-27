# `requirements-writer` agent — real implementation — Design

- **Date:** 2026-10-27
- **Status:** Draft — awaiting review
- **Builds on:** `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` (same branch, `feature/pipeline-all`, still unreleased as 3.2.0 — no further version bump)
- **Author:** Muhassin (with Claude)

## 1. Goal

Replace the placeholder body of `agents/requirements-writer.md` with real instructions. The
agent takes a feature idea (text, or Markdown files the client points at), asks the client
only about major gaps, and writes requirements that follow `templates/requirements-template.md`.

New in this design: when a feature is **genuinely** too big for one pipeline run, the agent
proposes splitting it into a shared file plus a few part files. Splitting is conservative —
one file is the default.

## 2. Decisions taken

| # | Decision |
|---|---|
| D1 | Input: plain text in the request and **`.md` / `.txt` files only**. Other file types are out of scope for now (no hook change). |
| D2 | Major gaps (agent stops and asks): purpose, who uses it, in/out of scope, main user flow, **security & compliance**, **other systems it must connect to**. Everything else → Assumptions + Open Questions. Success measure is a minor gap. |
| D3 | Questions: ≤7 per round, ≤2 rounds, relayed by the orchestrator in one batch (a subagent cannot talk to the client). |
| D4 | The agent reads the codebase lightly (targeted `Grep` → `Read` around the hit) before asking, so it does not ask what the code already answers. |
| D5 | `### Technical notes` are filled only with facts actually found in the code or input — never guesses. |
| D6 | Model: Sonnet. Tools: `Read, Grep, Glob, Write, Edit, Skill`. |
| D7 | Skills used as **methods, not processes**: gstack `/office-hours` and `superpowers:brainstorming` to find gaps, gstack `/spec` to make rules and acceptance criteria precise. The agent never follows their interactive or commit steps. |
| D8 | Splitting: one file by default; split only under the rule in §4; the client approves the split **before** any file is written. |
| D9 | Split layout: `docs/features/<slug>/00-shared.requirements.md` + `docs/features/<slug>/NN-<part>.requirements.md`. All files approved together in one step. |
| D10 | After a split, **one part per pipeline run**. The run continues with part 1; the final report gives the exact command for the next part. |
| D11 | In `/pipeline-all`, the planner runs in a new **Approved-requirements mode** that skips `/office-hours` + brainstorming (already done with the client) — avoids paying for that framing twice. |

## 3. Agent flow (`agents/requirements-writer.md`)

```
draft dispatch
  1. Read template, input files (chunks), targeted code reads
  2. Major gap?            ── yes, round < 2 ──► NEEDS_CONTEXT (≤7 questions)
  3. Needs a split (§4)?   ── yes, no approved_split ──► SPLIT_PROPOSAL (no files written)
  4. Write one file, or shared + parts per approved_split
  5. DONE
revision dispatch
  Edit only the sections the feedback touches (any of the written files). Never regenerate.
```

### 3.1 Inputs

| Field | Meaning |
|---|---|
| `mode` | `draft` or `revision` |
| `request` | the client's request, verbatim |
| `input_files` | `.md` / `.txt` paths the client referenced, or `none` (both modes) |
| `template` | path to the template, or `unavailable` |
| `output` | single-file path `docs/features/<slug>.requirements.md` |
| `output_dir` | split folder `docs/features/<slug>/` |
| `repo_root` | repository root |
| `answers` | answers to earlier `NEEDS_CONTEXT` questions, cumulative (both modes) |
| `question_round` | 0, 1 or 2 — starts at 0 for each draft and each revision round; at 2 never return `NEEDS_CONTEXT` |
| `split_feedback` | the client's changes to a split proposal, verbatim (draft only) |
| `approved_split` | the approved parts list verbatim, or `one-file` when the client chose to keep one file (draft only) |
| `feedback` | the client's change requests, verbatim (revision only) |
| `files` | the paths already written (revision only) |

### 3.2 Returns

```
status: DONE | NEEDS_CONTEXT | SPLIT_PROPOSAL | BLOCKED
reason: one line — e.g. template not found                      (BLOCKED)
paths: <one path, or shared first then parts in build order>   (DONE)
counts: per file — BR n · VAL n · AC n · Open Q n               (DONE)
summary: ≤5 lines                                              (DONE)
open_questions: numbered, one line each, with file              (DONE)
questions: numbered list                                       (NEEDS_CONTEXT)
parts: numbered — NN · name · what it delivers · ~N AC · why it cannot merge   (SPLIT_PROPOSAL)
order: build order + one-line reason                           (SPLIT_PROPOSAL)
shared: one line — what goes into 00-shared                    (SPLIT_PROPOSAL)
turns: <n>
```

The contract keeps `answers`, `question_round`, `input_files` and the `DONE` / `NEEDS_CONTEXT`
fields from the placeholder release unchanged; `path` becomes `paths` (a one-item list for a
single file).

## 4. Splitting rule

**One file is the default.** Split only when **both** hold:

1. The parts are truly independent — each can be released and used on its own and gives users
   value without the others.
2. One file would be too big for one pipeline run — as a guide, more than ~25 acceptance
   criteria or more than ~8 user journeys in total.

**Never** split by technical layer (frontend / backend / database), by screen, by create /
edit / delete of the same thing, or into steps of one user flow. Never create a part with fewer
than ~8 acceptance criteria — merge it into its closest neighbour. Propose the **fewest** parts
possible, each with a one-line reason it cannot merge. When in doubt, one file.

Example: the EMV Email Automation sample (9 modules) gives about 4 parts, not 9.

## 5. Split file layout

- `docs/features/<slug>/00-shared.requirements.md` — same template. Holds what every part
  needs: §1 Purpose, §2 Business Objective, §3 Background, §4 Scope (lists the parts), §5 Users
  and Roles, rules that apply to all parts (§8), §17 Non-functional, §18 Security, §20
  Assumptions, §21 Dependencies, §22 Open Questions. Part-only sections say
  "See the part files."
- `docs/features/<slug>/NN-<part>.requirements.md` — same template, all 23 sections. Sections
  owned by the shared file say "See `00-shared.requirements.md` §N." plus anything specific to
  the part.
- IDs are unique across the feature: the shared file uses 001–099; part N uses N01–N99
  (part 1: `BR-101`, part 2: `BR-201`).
- The name is `00-shared`, never `00-overview.md`: that name is reserved by the context-budget
  hook for plan overviews (allow-listed and treated as a derived artifact).

## 6. `/pipeline-all` changes

| Stage | Change |
|---|---|
| R step 1 | If the request is a path to an existing `*.requirements.md` (e.g. the next part), skip the writer: show the path and go to the approval question; if `00-shared.requirements.md` sits beside it, record it as `REQUIREMENTS_SHARED`. Otherwise check for both `docs/features/<slug>.requirements.md` and `docs/features/<slug>/` (Use existing / Regenerate). Stale-contract removal covers `<dir>/<stem>.contract.md` for the file(s) in play. |
| R step 2 | Also pass `output_dir`. |
| R new step | **`SPLIT_PROPOSAL`** → in one turn show parts, order and shared line; ask **Approve split** \| **Keep as one file** \| **Change the split**. Approve → re-dispatch draft with `approved_split` = parts verbatim. Keep → `approved_split: one-file`. Change → `split_feedback`, re-dispatch; after 2 change rounds offer only Approve / Keep. |
| R step 4 | `DONE` with several paths → list each file with its counts; one **Approve all** \| **Request changes** question; on approve, `sed` the Status line of every file; on changes, `revision` with `files`. |
| R step 5 | **`BLOCKED`** (e.g. template not found) → handled like `PLACEHOLDER`, with the reason shown: continue with the raw request, `REQUIREMENTS: none`. |
| R ledger | Split → `REQUIREMENTS: <part 1> (approved, part 1 of N)`, `REQUIREMENTS_SHARED: <shared>`, `REMAINING_PARTS: <paths>`. |
| Q | Also pass `REQUIREMENTS_SHARED` when set. |
| 0.8 | With a shared file: size = shared + part; copy = `cat <shared> <part> > <part dir>/<part stem>.contract.md`; distil = distiller gets the part as `<source>` and the shared file as an extra input to read. Contracts always sit beside their requirements file. |
| 1 | When requirements exist, dispatch the planner in **Approved-requirements mode**. When distilled, also pass the shared file as an original it may read. |
| 6 | If `REMAINING_PARTS` is not empty, the final report ends with the next command: `/sdlc-pipeline:pipeline-all <next part path>`. |
| Ledger | Add `requirements_shared`, `remaining_parts`, `split_rounds: N / 2`. |
| Hard rules | One part per run. |

The `PLACEHOLDER` handling stays in the orchestrator (harmless; the real agent never returns it).

## 7. Other files

| File | Change |
|---|---|
| `agents/requirements-writer.md` | Real body; frontmatter adds `Skill`; contract per §3. |
| `agents/planner.md` | Additive: new **Approved-requirements mode** (skip `/office-hours` + brainstorming; do not re-open scope — conflicts go to `## Open decisions`; then writing-plans with `/spec` rigor; `NEEDS_CONTEXT` only for implementation facts). `/pipeline` and `/pipeline-parallel` never request it, so they are unaffected. |
| `templates/requirements-template.md` | Header comment: split ID ranges and the "See `00-shared…` §N" convention. |
| `README.md` | Example 4: real requirements agent, splitting, next-part command; QA slot still a placeholder. |
| `docs/superpowers/specs/2026-10-26-pipeline-all-design.md` | §12 item 2 points to this spec. |

**Not changed:** `commands/pipeline.md`, `commands/pipeline-parallel.md`, `hooks/*`,
`scripts/*`, `agents/distiller.md`, `agents/qa-placeholder.md`, manifests.

## 8. Hook fit (checked against `hooks/guard_context_budget.py`)

- Input files over 250 lines / 20,000 bytes must be read in chunks — the agent's instructions say so.
- `00-shared.requirements.md` never matches a part's contract by stem or the ≥12-character
  overlap fallback (`00sharedrequirements` is not a substring of `01…requirements` stems and
  vice versa), so it is never shadowed.
- Part contracts sit beside their part (`<dir>/<part stem>.contract.md`); the hook checks the
  original's own directory first.
- Reviewers may read only slices and `*.contract.md`; a copied part contract contains the shared
  text too, so reviewers see everything.

## 9. Verification

Prompts cannot be unit-tested, so verification is structural plus a manual run:

1. `claude plugin validate .` — 13 warnings (baseline), none on changed files.
2. Greps confirm the wiring: every status the agent returns is handled in Stage R; `Skill` in
   the agent's tools; Approved-requirements mode named in both `planner.md` and Stage 1.
3. Protected files unchanged (`git diff --exit-code`).
4. Reinstall (`claude plugin update sdlc-pipeline@sdlc-pipeline-dev`), new session, then:
   - **Small idea** → questions only if a major gap, one file, approve gate, Status → Approved.
   - **EMV sample** (`requirement (1).md`) → a split proposal of few parts (≈4), approve → shared
     + parts written, run continues with part 1; stop at the Stage 2.5 gate.
   - **Next part** → `/sdlc-pipeline:pipeline-all docs/features/<slug>/02-….requirements.md`
     skips the writer and goes straight to approval.

## 10. Out of scope

PDF / Word input; the QA agent; running several parts in one session; changes to `/pipeline`
or `/pipeline-parallel`.
