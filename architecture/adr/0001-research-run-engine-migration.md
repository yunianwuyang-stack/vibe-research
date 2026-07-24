# ADR-0001: Migrate WorkflowEngine to ResearchRunEngine

- Status: Accepted
- Date: 2026-07-19
- Phase: P2
- Owners: backend runtime / domain
- Location note: `docs/` is ACL-locked (DENY write) on this workspace; canonical ADR lives under `architecture/adr/`.

## Context

The product still creates and advances research work primarily through
`WorkflowEngine` + SQLite `workflows` / `workflow_steps` tables, with ad-hoc
`ALTER TABLE` recovery in `state_store` and host scaffold execution paths.

P1 closed agent/host pseudo-success and security gates. P2 must make the
**ResearchRun** aggregate the single source of truth for scientific execution
state, without leaking FastAPI / SQLite / Electron / provider SDKs into the
domain package.

## Decision

1. **Canonical aggregate** is `backend/domain/research_run.py` (`ResearchRun`,
   `Task`, `TaskAttempt`, `Gate`, `ArtifactRef`, `RunEvent`).
2. **Application service** `ResearchRunEngine` (to be introduced under
   `backend/services/`) is the only write path for new research runs after the
   dual-write freeze window.
3. **Ports** isolate infrastructure:
   - `RunRepository` (SQLite / later remote)
   - `ArtifactStore` (content-addressed files)
   - `Clock` / `IdFactory` (testable)
   - `EventLog` (append-only projection)
4. **Old mapping** (freeze dual-write, then delete old write paths):

| Legacy surface | New surface |
| --- | --- |
| `workflows` row | `ResearchRun` |
| `workflow_steps` | `Task` |
| step attempt / retry | `TaskAttempt` |
| step gates / quality checks | `Gate` |
| `workflow_artifact_lineage` / output files | `ArtifactRef` (+ store) |
| `workflow_logs` / operation events | `RunEvent` stream |
| `POST /api/workflows` create | `ResearchRunEngine.create_run` |
| `run_workflow` / step runner | `ResearchRunEngine.start_task` / `finish_task` / `retry_task` |
| ad-hoc `ALTER TABLE` in runtime | versioned migration chain only |

5. **Dual-write freeze rule**
   - While migrating: create path may dual-write legacy workflow rows **and**
     ResearchRun rows, but **reads for new UIs and gates must prefer ResearchRun**.
   - After clone dry-run + backfill verification: set
     `research_run_engine_primary=true` and make legacy create path raise
     `LegacyWriteFrozen`.
   - Delete order is fixed (see Consequences). Do not delete before dry-run
     evidence exists.

6. **Domain purity**
   - `backend/domain/**` must not import `fastapi`, `sqlite3`/`aiosqlite`,
     Electron bridges, or model provider SDKs.
   - Characterization tests assert transition legality, event monotonicity,
     artifact hash fail-closed behavior, and retry attempt identity.

## Consequences

### Positive

- Single aggregate for status/gates/artifacts/events.
- Testable pure domain transitions without DB.
- Clear freeze/delete sequence for dual state.

### Negative / costs

- Temporary dual-write complexity.
- Need migration of historical workflows into research-run tables.
- Frontend/API must learn new IDs and event projections.

### Deletion order (mandatory)

1. Ship engine create/advance with dual-write flag on.
2. Backfill historical workflows -> research runs (dry-run + apply).
3. Switch reads to ResearchRun; keep legacy write only for recovery.
4. Freeze legacy create/update write APIs (`LegacyWriteFrozen`).
5. Remove host dual state writes and runtime ad-hoc schema ALTER for this path.
6. Delete unreachable legacy create/run write paths after clone/arch gates pass.

### Non-goals for this ADR

- Replacing Claude/host skill execution transport (P1 already constrained it).
- Full SQL schema freeze (owned by P2.3 migration chain task).

## Validation

- Characterization tests: `tests/test_research_run_engine.py`
- Domain import boundary static check in P2 qualification / suite
- Later: migration dry-run evidence under `harness/v2/evidence/P2/`
