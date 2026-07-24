# ADR-G0-012: Bind and verify JUnit lane receipts

- **Status:** Accepted for local remediation; does not grant G0 acceptance.
- **Date:** 2026-07-18
- **Scope:** `harness/scripts/g0_runner.py`, `tests/test_harness_g0.py`, and G0 lane evidence.

## Context

An independent cold review identified that the existing full G0 lane summary contained non-empty JUnit paths and parsed metrics but omitted every declared `junit_sha256`. A derived checker simultaneously stated that hash-shaped JUnit/stdout/stderr receipts were required and returned `PASS`. This is an evidence-integrity defect, not proof of a passing G0 phase.

## Decision

1. Each future lane record emitted by `run_lanes` must include the SHA-256 of its raw JUnit XML bytes.
2. `validate_lane_receipts` recomputes every required lane's JUnit digest from an evidence-contained file and fails closed on a missing, malformed, out-of-scope, missing-file, or mismatched digest.
3. The lane summary verdict includes the strict receipt-validation verdict; a parsed metric alone cannot make the lane summary pass.
4. Historical lane summaries without declared JUnit digests are evidence-incomplete. A later backfill may bind their still-present raw JUnit bytes only as a distinct derived receipt; it cannot retroactively make the original summary a formal signed acceptance artifact.

## Consequences

- The next real G0 run must produce digest-bound lane receipts.
- Existing 2026-07-18 full-run evidence remains phase `BLOCKED` and cannot be used for formal acceptance without protected runner trust, a valid formal candidate handoff, and fresh independently verified receipts.
- This local implementation decision does not substitute for external validation, human adjudication, or release qualification.
