# Requirements: Password reset

## 19. Business Acceptance Criteria
_Required_

<!-- Every In-Scope item is covered by at least one AC. -->

### AC-001 — Reset by email

**Covers:** BR-001

**Given** a registered user
who forgot the password

**When** they request a reset

**Then** they receive a link | valid for 30 minutes

### AC-002 — Unknown email

**Covers:** BR-002, BR-003

**Given**
an address that is not registered

**When**
a reset is requested

**Then**
the response is identical to the success response

## 20. Assumptions
_Required_
