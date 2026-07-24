# ADR-G0-009: Fail closed on mutable prior-automation ownership claims

- **Date:** 2026-07-18
- **Status:** Accepted for local control enforcement; G0 remains BLOCKED pending external provenance validation
- **Supersedes:** ADR-G0-006’s local admission mechanism
- **Scope:** `harness/scripts/g0_runner.py`, `tests/test_harness_g0.py`, and the legacy audit file `harness/baseline/prior-automation-ownership.json`

## Context

The independent cold review `G0-IR-20260718T0747Z` found that the G0 runner accepted a writable, untracked workspace file as proof that selected post-Day0 files belonged to prior automation. Exact hashes only showed that the claimant had not changed the file after writing its own ledger; they did not establish who authored the ledger or bind it to the Day0 baseline. The same runner also gave every file under `harness/` automatic agent ownership solely from its path.

The red characterization `harness/evidence/G0/g0-p1-red-characterization-20260718T0811Z.json` demonstrates the old behavior: a newly created, self-attested, hash-correct ledger was returned as trusted ownership data.

## Decision

1. The legacy workspace ledger is retained only as an auditable observation. The loader returns no ownership records from it, including when its schema and hashes appear valid.
2. When the legacy file is present, G0 emits `prior_automation_ownership_external_attestation_required`, sets `external_validation: pending`, and reports concrete unblock conditions. The ownership check and aggregate G0 verdict become `BLOCKED`, not a false `PASS` or ambiguous successful qualification.
3. The broad `harness/` and test-path prefix auto-attribution is removed. Post-baseline paths without an independently anchored source remain unattributed.
4. A future unblocking design must use a separate protected trust configuration and an independently signed Day0 attestation bound to the root contract, baseline manifest, exact paths/hashes, issuer authorization, validity window, and revocation state. No artifact created in this mutable workspace can substitute for that attestation.

## Consequences

All prior local G0 qualifications that relied on ADR-G0-006’s admission are **STALE**. Local tests may verify the fail-closed enforcement, but they do not supply the external signer, protected trust configuration, real pilot adjudication, sealed evaluator, or release qualification required for G0 acceptance. G0 may continue only through nodes that do not depend on accepted ownership provenance; dependent phases remain blocked.
