# ADR-P2-001: Canonical Research Run authority

- Status: accepted
- Canonical aggregate: `backend/domain/research_run.py`
- Canonical mutation entry: `backend/application/research_run_engine.py::ResearchRunEngine`
- Persistence port: `backend/application/ports.py::ResearchRunRepository`
- SQLite adapter and forward migrations: `backend/infrastructure/persistence/research_run_repository.py`

## Legacy mapping and deletion order

| Legacy object/path | Canonical mapping | Production mutation | Deletion condition |
|---|---|---:|---|
| `workflows` / `workflow_steps` | migration input and historical execution record | forbidden for new research runs | remove create/run routes after persisted records export through the adapter |
| `services/research_orchestrator.py` | `ResearchRunEngine` delivery adapter | forbidden | delete after router and compatibility tests use the engine |
| `services/workflow_engine.py` | no canonical run authority; execution compatibility only | forbidden for new research runs | delete when all templates are expressed as canonical task specifications |
| `research_runs` / `research_run_steps` | `research_run_aggregates` plus append-only `research_run_events` | read/migrate only | remove after semantic export hash parity and backup/restore receipt |

New run creation and lifecycle transitions must enter through `ResearchRunEngine`. Retry creates a new `TaskAttempt`; aggregate version and event version are monotonic. Domain code cannot import FastAPI, SQLite, Electron, filesystem implementations, or model SDKs.

P2 exceptions are permitted only in this ADR and expire when their deletion condition is met. The P2 architecture checker treats listed legacy modules as non-production migration/compatibility surfaces and fails if an exception has no ADR or deletion condition.
