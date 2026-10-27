# <Feature name> — Business Requirements

<!--
sdlc-pipeline requirements template v1.
- Fill every section marked _Required_.
- Never delete or renumber sections. If an _Optional_ section does not apply, keep its
  heading and write "Not applicable." (Other agents cite sections by number.)
- IDs (BR-, VAL-, AC-, Q-) start at 001 and are never reused.
- Split features: `00-shared.requirements.md` uses IDs 001–099; part N uses N01–N99 (part 1:
  BR-101, part 2: BR-201). A part's sections owned by the shared file say
  "See `00-shared.requirements.md` §N." plus anything specific to the part.
- Technical detail (table names, endpoints, regexes, services) is allowed ONLY under a
  "### Technical notes" heading, and only in sections 10, 11, 18 and 21. Everything else
  stays business-level.
- Delete these HTML comments when filling in the template.
-->

| Field | Value |
|---|---|
| Version | 0.1 |
| Date | YYYY-MM-DD |
| Status | Draft |
| Source | <client request and/or input file paths> |

## 1. Purpose
_Required_

<!-- 2–4 sentences: what this feature is and the business problem it solves. -->

## 2. Business Objective
_Required_

- **Primary objective:** <!-- the single most important outcome -->
- **Expected business outcome:**
- **Success measure:** <!-- measurable: a number, a percentage or a time -->
- **Target users:**
- **Business owner:**

## 3. Background
_Optional_

<!-- How things work today and why the change is needed now. -->

## 4. Scope
_Required_

### In Scope

- <!-- one bullet per capability; each is covered by at least one AC in §19 -->

### Out of Scope

- <!-- at least one entry: something a reader might expect that this feature will not do -->

## 5. Users and Roles
_Required_

| Role | Description | Main Actions |
|---|---|---|
| | | |

## 6. Business Process
_Optional_

### Current Process

1.

### Proposed Process

1.

## 7. User Journeys
_Required_

<!-- One journey per main path. Copy the block for each journey. -->

### Journey 1 — <name>

**Actor:**
**Trigger:**
**Preconditions:**
**Flow:**
1.

**Expected Result:**

## 8. Business Rules
_Required_

| Rule ID | Rule Description | Priority | Notes |
|---|---|---|---|
| BR-001 | | Must Have / Should Have / Could Have / Won't Have | |

## 9. Validation Rules
_Optional — Required when the feature takes user input_

| Validation ID | Field / Condition | Validation | Expected Error Message |
|---|---|---|---|
| VAL-001 | | | |

## 10. Data Requirements
_Optional_

| Data Item | Required | Source | Validation | Notes |
|---|---:|---|---|---|
| | | | | |

### Technical notes
_Optional_

<!-- Storage, schemas, field names. -->

## 11. Statuses and State Changes
_Optional_

| Entity | Current Status | Action | New Status | Conditions |
|---|---|---|---|---|
| | | | | |

### Technical notes
_Optional_

## 12. Notifications and Messages
_Optional_

| Trigger | Recipient | Channel | Message / Template |
|---|---|---|---|
| | | | |

## 13. Error Scenarios
_Required_

| Scenario | Expected Behaviour | User Message |
|---|---|---|
| | | |

## 14. Positive Scenarios
_Optional_

| Scenario | Expected Result |
|---|---|
| | |

## 15. Edge Cases
_Required_

-

## 16. Reporting and Audit Requirements
_Optional_

- **Events to audit:**
- **Reports required:**

## 17. Non-functional Requirements
_Required_

<!-- "None beyond platform defaults" is a valid entry for any row. -->

| Area | Requirement |
|---|---|
| Performance | |
| Availability | |
| Scalability | |
| Accessibility | |
| Browser / device support | |

## 18. Security and Compliance Requirements
_Required — never omit_

<!-- Access control, data protection, secrets, audit, regulatory. If nothing changes, write
"No new security surface" and say why. -->

-

### Technical notes
_Optional_

## 19. Business Acceptance Criteria
_Required_

<!-- Every In-Scope item and every Must Have BR is covered by at least one AC. -->

### AC-001 — <name>

**Covers:** BR-001

**Given**

**When**

**Then**

## 20. Assumptions
_Required_

<!-- May be "None". -->

-

## 21. Dependencies
_Optional_

-

### Technical notes
_Optional_

## 22. Open Questions
_Required_

<!-- The table may be empty. A question that changes scope must be Resolved before approval. -->

| Question ID | Question | Owner | Status | Decision |
|---|---|---|---|---|
| Q-001 | | | Open / Resolved | |

## 23. Business Definition of Done
_Required_

The requirements are ready for planning when:

- [ ] Every Required section is filled (or explicitly "None").
- [ ] Every In-Scope item is covered by at least one AC.
- [ ] Every Must Have BR is referenced by at least one AC.
- [ ] Security (§18) is filled.
- [ ] No Open Question that changes scope remains Open.
