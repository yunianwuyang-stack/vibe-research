# ADR-G0-010: Signature-bound trusted runner receipts for formal G0 adjudication

- Date: 2026-07-18
- Status: Accepted for local verifier enforcement; G0 remains BLOCKED pending real protected runner trust and external validation
- Scope: verifier, runner, and G0 formal-adjudication tests

## Context

Independent review finding G0-F-003 showed that formal adjudication accepted a reviewer-signed candidate report set even when every report contained only gate_id and verdict PASS. The old candidate-lock check authenticated report bytes but never parsed their semantics, never validated the claimed runner execution, and did not require a trust root distinct from the reviewer.

The executable pre-patch characterization in harness/evidence/G0/g0-p0-prepatch-bare-pass-characterization-20260718T0829Z.json records that defect. Earlier temporary-script attempts are retained as INVALID evidence with raw stderr and correction receipts; they are not used as proof.

## Decision

1. G0 reports now require a non-vacuous canonical schema: requirement, runner and root bindings; nonempty denominator and strata; checks; input/output manifests and hashes; artifact manifests; and explicit pending qualification state.
2. Formal adjudication parses every G0 report in the candidate report set and rejects bare or malformed reports before a reviewer receipt can be consumed.
3. Each report must reference a canonical Ed25519 trusted-runner receipt signed under a separate runner_trust binding. The receipt binds the report hash, candidate runner path/hash/exact command, input/output manifest hashes, root-contract hash, exit code, timeout state, verdict, issuer authorization, validity window, revocation state, and unique receipt ID.
4. Reviewer trust and runner trust are separate. A reviewer signature cannot self-authorize a runner execution.
5. The local G0 runner emits the strengthened report structure but only an unsigned local derivation path. Without a protected external runner signer, formal adjudication blocks it; no local artifact is promoted to acceptance.

## Consequences

All pre-ADR-G0-010 local formal qualifications are STALE. Test-only keys in temporary pytest directories verify cryptographic behavior only; they are not a protected production trust root, external validation, human or expert adjudication, or release qualification. Unblocking requires a protected externally managed runner trust configuration, real signed supervisor receipts from executed commands, fresh independent review, and remaining G0 acceptance evidence.
