# ADR-G0-001: Repair stale non-live characterization contracts

Status: accepted for implementation, pending independent review

## Context

G0 requires the complete non-live suite to pass before G1 can unlock. The
frozen G0 allowed-path list did not include three pre-existing tests or
`backend/services/workflow_options.py`. The first supervised G0 lane run found:

- `one_sentence_project` was incorrectly normalized to `grad_project`, so the
  API completed a different DAG while reporting success.
- the source-layout contract required `APP_ROOT/backend`, although packaged
  backend code is intentionally in `app.asar.unpacked` and is addressed through
  `EXECUTABLE_APP_ROOT/backend`.
- packaged tests assumed the obsolete non-asar `resources/app` directory even
  though `package.json` freezes `asar: true` and `asarUnpack: backend/**`.

Re-enabling fake artifacts, skipping these tests, or weakening the non-live
gate would conflict with the root contract.

## Decision

Permit an exact G0 exception for these files only:

- `backend/services/workflow_options.py`
- `tests/test_r01_production_contract.py`
- `tests/test_dual_clean_packaged_backend_e2e.py`
- `tests/test_dual_clean_packaged_gui_e2e.py`

Remove only the incorrect alias. Strengthen packaged characterization to read
`main.js` from the real asar archive and backend code from
`app.asar.unpacked/backend`. Preserve all functional assertions and rerun the
affected tests plus every supervised non-live lane.

## Consequences

The exception does not change `phase-contract.lock`, the bootstrap contract,
or any quality threshold. It makes the G0 characterization match the shipped
layout and prevents a wrong-template completion from being treated as success.
The ADR remains pending independent review until a separate reviewer receipt
is attached.
