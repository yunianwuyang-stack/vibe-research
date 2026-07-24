# ADR-G0-004: Standalone harness scripts resolve sibling imports from their own location

- **Date:** 2026-07-18
- **Status:** Accepted for G0 repair; verification pending
- **Scope:** `harness/scripts/` only

## Context

The read-only baseline characterization showed that invoking the standalone G0 scripts directly (`--help`) failed before argument parsing with `ModuleNotFoundError` for sibling harness modules. This defeated the required independently runnable command contracts.

## Decision

Each affected standalone script prepends its resolved `harness/scripts` directory to `sys.path` only when it is absent, before importing its sibling modules. The change does not alter root-contract rules, gate thresholds, output semantics, or trust boundaries.

## Consequences

The scripts can be invoked by absolute path from an arbitrary working directory. Focused CLI and G0 regression lanes must verify both direct invocation and prior import-based contracts. The change is confined to the authorized `harness/` boundary.
