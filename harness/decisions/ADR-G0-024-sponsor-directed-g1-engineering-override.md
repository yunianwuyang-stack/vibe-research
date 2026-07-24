# ADR-G0-024: Sponsor-directed G1 engineering override

- **Status:** accepted as a non-qualifying execution override
- **Observed:** 2026-07-18T13:57:16Z
- **Scope:** G1 writer authorization only
- **Sponsor input:** `强制解锁G1`
- **Bound authorization:** `harness/adjudications/G0-UA-20260718T134723Z-workspace-owner-resumption.json` (`4d174a67570c7780bf7be6972553c5365d530680716fba7a63bddb954d350ece`)

## Context

The authoritative G0 state remains `BLOCKED`. The latest complete G0 runner evidence has not established accepted engineering assurance, and protected ownership/candidate handoff evidence remains absent. The sponsor nevertheless directed the implementation session to start G1 work.

## Decision

Authorize G1 writers as `in_progress_unqualified_override` without changing the frozen root contract, `phase-contract.lock`, `manifest.yaml` dependencies, gate thresholds, or any existing verdict. This is an execution authorization, not a gate acceptance.

All G1 artifacts produced under this override must:

1. retain provenance to this ADR and the user adjudication;
2. remain ineligible for promotion, release, readiness claims, or Goal completion until the ordinary G0 dependency is genuinely accepted;
3. record `engineering_assurance: STALE` or `NEEDS_REVIEW` rather than `accepted` until trusted receipts prove the locked gates;
4. keep G0 external validation, release qualification, sealed evaluation, and pilot states unchanged;
5. use the normal G1 `allowed_paths` boundary and task-level red/verify/review workflow.

## Consequences

G1 implementation can proceed, but no downstream system may interpret the override state as `PASS` or `accepted`. Any qualification report that treats this ADR as gate evidence is invalid. Removing this restriction requires a fresh root-contract receipt and ordinary trusted G0 acceptance.
