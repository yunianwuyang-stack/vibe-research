# ADR-G0-014: Canonical lane identity and durable external CLI provenance

- **Status:** Accepted for local integrity remediation; G0 remains blocked.
- **Date:** 2026-07-18

## Context

Independent review found that a valid JUnit digest could previously name a noncanonical file inside the evidence directory, negative coverage for mismatch/outside/missing cases was incomplete, and real external CLI failure evidence was only summarized from a temporary path.

## Decision

1. A lane receipt must place evidence under an explicit workspace root and resolve exactly to `evidence_dir/lane-<lane>.xml`.
2. Missing digest, mismatch, outside-evidence path, noncanonical lane path, missing JUnit, and evidence outside workspace fail closed and receive direct regression coverage.
3. Existing external CLI failure source artifacts are to be copied byte-for-byte into a unique local evidence snapshot only after no-apparent-secret scanning. This does not package credentials or turn a failure into success.

## Consequences

- Desktop external CLI validation remains BLOCKED pending official user-managed Claude login and a non-429 Codex run.
- Formal candidate handoff remains STALE under ADR-G0-013.
- G0 remains BLOCKED.
