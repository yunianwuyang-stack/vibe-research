# ADR-G0-005: G0 tests must confine fixture and evidence writes to owned temporary roots

- **Date:** 2026-07-18
- **Status:** Accepted; prior G0 qualification is stale pending rerun and independent review
- **Scope correction:** Five named G0 lane test files plus `harness/manifest.yaml`

## Context

The protected baseline G0 run exposed tests that attempted to modify repository-owned `skills/` and `verification-logs/` paths. Such writes are not test isolation, can mutate user artifacts, and fail under the required protected worktree.

## Decision

Keep each test's existing behavioral assertion and move its setup/evidence writes to its pytest-owned temporary root or the already explicit `VIBE_GUI_E2E_EVIDENCE` root. The relative-workspace test remains relative, but changes its current directory to the temporary root and restores global state. The manifest scope is extended only for these corrective test files; no gate, oracle, threshold, or root-contract rule changes.

## Consequences

A new full G0 rerun is required. Earlier G0 reports are stale. The repair prohibits production skill and repository evidence-log mutation by the affected tests while preserving evidence round-trip checks.
