# ADR-G0-006: Exact-hash attribution for pre-existing G0 automation tests

- **Date:** 2026-07-18
- **Status:** Accepted; prior G0 qualification is stale pending rerun and independent review
- **Scope:** `harness/**` and `tests/test_harness_g0.py`

## Context

The fresh G0 ownership ledger identified two untracked tests that predated this execution (created on July 17, 2026) and exercise only the G0 contract: `tests/test_candidate_lock_mode.py` and `tests/test_g0_truth.py`. They were absent from the Day0 baseline and therefore could not be silently treated as user-owned or agent-owned by a path prefix.

## Decision

Record these exact paths and SHA-256 values in `harness/baseline/prior-automation-ownership.json`. The runner admits only declarations with a valid canonical schema, safe relative path, exact current hash, and observed status. Missing, duplicate, malformed, hash-drift, or unseen declarations fail the ownership gate. All other post-baseline paths remain unattributed.

## Consequences

This is provenance attribution, not a broad allowlist and not a gate relaxation. A modified test cannot retain the attribution. G0 must be rerun and independently reviewed.
