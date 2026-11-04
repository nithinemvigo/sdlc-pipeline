---
name: gap-prioritisation
description: Assign exactly one priority (Critical, High, Medium, Low) to each requirement gap based on the impact of the missing decision. Use when classifying gaps during gap analysis or reconciliation.
---

# Gap Prioritisation

Every gap gets exactly one of `Critical`, `High`, `Medium`, `Low`. Priority measures the impact of the missing decision, not the length or complexity of the gap.

## Definitions

| Priority | Definition | Typical impact |
|---|---|---|
| Critical | Missing information creates a major security, regulatory, financial, safety or business-continuity risk, or leaves a critical business capability unsafe or fundamentally undefined. | Severe risk or unacceptable exposure. |
| High | Missing information materially affects core functionality, important business rules, or the ability to define a reliable implementation. | Significant functional impact or substantial blocker. |
| Medium | Missing information affects secondary behaviour, usability, operational handling or important edge cases, but the core capability can still be understood. | Moderate impact or partial uncertainty. |
| Low | Minor clarification or refinement with limited impact on core functionality or business outcomes. | Low impact; can usually be addressed later. |

## Method

1. Ask what happens if the decision is never made or is made wrongly. Consider security, privacy, compliance, financial, operational and customer impact where they apply.
2. Consider breadth: how many requirements and business capabilities depend on the answer.
3. Consider whether the gap blocks meaningful implementation or verification, or only a corner of it.
4. Pick the lowest priority whose definition fully fits the impact. Move up only for a stated reason.
5. Do not assign Critical or High merely because the requirement is in a familiar high-risk domain (authentication, payments, personal data). A cosmetic question about a login page is not Critical.
   - Exception by impact, not by domain: a missing security parameter (a limit, duration, policy, role or retention period) that the protection of credentials, access control, sessions or sensitive data depends on is at least High. It is Critical when its absence leaves the capability open to account takeover, unauthorised access or exposure of sensitive data.
6. Be consistent: two gaps with the same kind of impact get the same priority.
7. Be ready to explain the choice in one sentence. Give the rationale in your analysis response or execution summary. Do not store it: the persisted gap object has no rationale field.

## Examples

| Missing decision | Priority | Why |
|---|---|---|
| Lock-out policy after failed logins | Critical | Open to credential attacks; security exposure across authentication. |
| Maximum payment amount per transaction | Critical | Financial risk; the capability is unsafe without a limit. |
| Which roles may approve a request | High | Core business rule; the workflow cannot be built reliably without it. |
| Inactivity limit after which a session ends | High | Security parameter; the protection of logged-in accounts depends on it. |
| Behaviour when an export exceeds the size limit | Medium | Important edge case; the core export is understood. |
| Whether the confirmation page shows the order date | Low | Minor refinement. |

## Anti-patterns

- Rating by word count or by how many questions the gap asks.
- Rating everything High "to be safe".
- Rating by the domain of the requirement instead of the impact of the gap.
- Letting the likely answer reduce the priority. Priority describes the missing decision, not your guess about it.
