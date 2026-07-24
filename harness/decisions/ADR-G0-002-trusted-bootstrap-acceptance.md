# ADR-G0-002: Trusted bootstrap acceptance and protected recovery boundary

Status: approved for implementation, pending independent review

## Context

The external bootstrap contract currently matches its fixed OS SHA256, contains 207 requirements and 12 tamper vectors, and maps one-to-one to 207 frozen gates. The existing `run_tamper_vectors` implementation does not execute the semantics of TV-011 (`allowed_paths_violation`) or TV-012 (`source_license_receipt_missing_or_incompatible`); it assigns their expected verdicts directly. Existing G0 evidence is not authoritative because it was not accepted through the hash-chained journal, and the original Day 0 snapshot inherited broad Modify access.

The product worktree contains extensive pre-existing tracked, untracked, and ignored content. None of it may be reset, stashed, deleted, broadly staged, or committed as part of this repair.

## Decision

Retain the external bootstrap contract and `harness/phase-contract.lock` unchanged. Do not change `harness/scripts/verify_truth.py`, because its SHA256 is frozen into all 207 gates.

Implement two deterministic checkers outside `verify_truth.py`:

1. An allowed-path checker compares locked pre/post tree records and returns `FAIL` when any changed path is not matched by the task's declared allowlist. TV-011 must create an isolated pre/post pair with one out-of-allowlist mutation and obtain `FAIL` by calling this checker.
2. A source-provenance checker validates each consulted source and its license decision receipt. It returns `BLOCKED` when a receipt is missing, the declared reuse mode conflicts with the license category, or required obligations are unresolved. TV-012 must exercise both a missing receipt and an incompatible license decision and obtain `BLOCKED` from this checker.

The tamper runner must report the checker invocation, input hashes, checker hash, actual verdict, expected verdict, and per-case pass status. No vector may assign its expected verdict as its observed result.

Use the external snapshot `D:\科研软件制作\Vibe-research源码-G0Protected-20260717`, copied from the Day 0 byte snapshot. Its manifest SHA256 is `ebc160605443262f0284e9bdf4132c2a93e71479800858a412f83cb45fba8f5e`. The snapshot ACL grants write access only to its owner, SYSTEM, and Administrators; sandbox/audit identities receive read-only access. A write probe must fail while preserving the probed file hash. Recovery must occur in an isolated directory and prove manifest bytes, deletion markers, HEAD, index, refs, and status are exact. The accepted recovery drill returned PASS for 4,504 manifest entries and 383,368,530 bytes.

Treat all existing G0 JSON files as historical inputs until a trusted runner derives a non-empty gate report from fresh supervisor receipts. The supervisor receipt records argv, cwd, root-contract expected and actual OS hash, tool and checker hashes, input/output hashes, exit code, and attempt identity. Only after independent read-only review accepts the raw diff, receipts, ACL evidence, recovery evidence, JUnit results, and tamper cases may the coordinator append the G0 acceptance event and atomically rebuild `state.json` from `events.jsonl`.

## Allowed implementation scope

- `harness/scripts/bootstrap_contract.py`
- new focused checker modules under `harness/scripts/`
- `harness/scripts/g0_runner.py`
- `tests/test_harness_g0.py`
- G0 evidence, findings, adjudications, and this ADR under `harness/`

No G1 product behavior is changed by this decision. Any overlap with a pre-existing file requires recording its before hash and preserving unrelated content.

## Acceptance

G0 remains blocked unless all of the following are true:

- OS `Get-FileHash` matches the fixed root-contract SHA256 immediately before acceptance.
- All 207 requirement text hashes, the Merkle root, and lock coverage pass.
- All 12 tamper vectors execute real validation paths and return their locked verdicts.
- TV-011 and TV-012 include non-empty checker receipts and reject their mutations.
- The protected snapshot ACL and failed-write receipt pass independent review.
- Isolated recovery proves byte and Git-state equivalence.
- Ownership, ignored-data disposition, secret scan, journal fault matrix, test lanes, and orphan-process checks pass.
- A trusted runner derives the gate report from fresh receipts.
- An independent reviewer accepts the evidence before the journal records G0 as accepted.

A failure produces a finding with its evidence and unblock condition. It does not create a PASS, and it does not unlock G1.

## Consequences

The frozen quality thresholds and root requirements remain unchanged. Existing historical release logs and artifact files remain useful characterization evidence but cannot qualify G0 or any later phase. G1 writers remain disabled until the authoritative journal projects G0 engineering assurance as accepted.
