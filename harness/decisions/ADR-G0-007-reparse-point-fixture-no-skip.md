# ADR-G0-007: Reparse-point scope test must not skip on Windows

- **Date:** 2026-07-18
- **Status:** accepted for G0 test-fixture repair; all prior qualifications remain `STALE` pending a new trusted run and independent review.

## Context

The trusted G0 run `g0-runner-full-post-isolation-ownership-20260718T0649Z` recorded one skipped unit case: `tests/test_g0_truth.py::test_scope_rejects_symlink_segment` (`symlinks unavailable`). G0 treats every skip as non-passing because it removes the denominator for a required root-contract boundary case.

## Decision

The test still first attempts to create a directory symbolic link. If that fails on Windows, it creates a **test-owned directory junction** with `cmd.exe /d /s /c mklink /J` under pytest's `tmp_path`, asserts the created directory is a Windows reparse point, and preserves the original assertion that the verifier rejects `linked/report.json` with `reports_hash`. If neither mechanism can be created, the test fails with captured command diagnostics; it never skips.

## Consequences

- No production verifier, gate threshold, or assertion was relaxed.
- The exact-hash ownership ledger repins only `tests/test_g0_truth.py` and truthfully records `agent_g0_repair_20260718` as its owner.
- The G0 manifest already allows this exact test and `harness/**`; no phase-contract change is made.
- This does not grant G0 acceptance. It requires focused regression, full unit and desktop lanes, a full trusted runner, and independent review.
