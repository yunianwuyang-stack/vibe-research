# ADR-G0-013: Freeze formal-candidate handoff and fail closed on stale locks

- **Status:** Accepted as a blocking control record; no qualification is accepted.
- **Date:** 2026-07-18
- **Scope:** G0 formal candidate handoff, protected runner trust, and frozen phase contract compatibility.

## Context

Independent cold review found that the frozen `phase-contract.lock` names a historical `verify_truth.py` hash while the current implementation differs; actual G0 reports are emitted below `harness/evidence/G0/gate-reports/`, whereas the formal candidate protocol requires a frozen candidate lock, manifest, root-level report set, and protected signed runner receipts. None of those formal candidate artifacts exists for the current mutable worktree. A caller-controlled trust/config directory cannot demonstrate independent protected trust.

## Decision

1. The existing phase lock and every qualification derived from its historical runner binding are **STALE** for formal acceptance. They must not be silently regenerated or edited in the candidate workspace.
2. A future formal candidate must be created only by the authorized protected trust/contract owner after an independent ADR/review, with exact root-contract binding, approved current runner hashes, canonical report paths, candidate lock/manifest/report set, protected signer ACL/revocation/replay controls, and real supervisor receipts.
3. The local G0 runner may continue to produce diagnostic derivations, but these remain non-acceptance artifacts unless the protected handoff is completed.
4. External CLI adapter failure (authentication, quota, or upstream service errors) is recorded as `external_validation: pending`; no mock, skip, or retry masquerades as real E2E success.

## Consequences

- G0 remains `BLOCKED`.
- G1–G11 do not unlock from local evidence alone.
- No credential is packaged or bypassed; official user-managed login and an external trusted runner are required to unblock the relevant paths.
