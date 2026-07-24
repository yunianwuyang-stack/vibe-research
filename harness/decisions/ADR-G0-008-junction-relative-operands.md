# ADR-G0-008: Windows junction fallback uses fixed relative operands

- **Date:** 2026-07-18
- **Status:** accepted repair of ADR-G0-007 implementation; G0 remains `STALE` and not accepted.

## Context

The first no-skip fixture repair was intentionally red-verified by `g0-reparse-point-focused-verify-20260718T0720Z`. Directory symlink creation correctly failed with Windows error 1314, but `cmd.exe` returned exit 1 for the quoted absolute `mklink /J` operands. The controlled characterization `g0-junction-command-characterization-20260718T0723Z` established that unquoted operands succeed and produce a reparse point; its stdout write itself failed only due the diagnostic console's GBK encoding, while its on-disk JSON record is complete.

## Decision

Execute the junction command from pytest's `tmp_path` with the fixed relative operands `linked` and `real`: `cmd.exe /d /c mklink /J linked real`. No user-controlled value is interpolated into the command. The test still asserts that the created object is a reparse point and that the verifier returns `reports_hash`.

## Consequences

- The fallback remains confined to the test-owned temporary directory.
- The failed first repair remains preserved as evidence; it is not rewritten into a pass.
- No gate condition, verifier behavior, or expected failure oracle changed.
