"""SQLite adapter for the canonical ResearchRun aggregate."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from application.ports import ConcurrencyConflict
from domain.research_run import ResearchRun, run_from_dict, run_to_dict
from .migrations import Migration, MigrationRunner


def _create_run_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE research_run_aggregates (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version > 0),
            payload TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE research_run_events (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES research_run_aggregates(id),
            aggregate_version INTEGER NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
            occurred_at TEXT NOT NULL, UNIQUE(run_id, aggregate_version)
        );
        CREATE INDEX idx_research_run_aggregates_project ON research_run_aggregates(project_id, updated_at DESC);
        """
    )


RESEARCH_RUN_MIGRATIONS = (Migration(1, "canonical_research_run_aggregate", _create_run_tables),)


class SqliteResearchRunRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._transaction_connection: sqlite3.Connection | None = None

    def migrate(self) -> None:
        MigrationRunner(self.database_path, RESEARCH_RUN_MIGRATIONS).migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def transaction(self):
        from contextlib import contextmanager
        @contextmanager
        def scope():
            connection = self._connect()
            self._transaction_connection = connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                self._transaction_connection = None
                connection.close()
        return scope()

    def _operation(self):
        from contextlib import contextmanager
        @contextmanager
        def scope():
            if self._transaction_connection is not None:
                yield self._transaction_connection
                return
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        return scope()

    def project_exists(self, project_id: str) -> bool:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,)).fetchone() is not None

    def create_run(self, run: ResearchRun) -> None:
        payload = run_to_dict(run)
        with self._operation() as connection:
            connection.execute("INSERT INTO research_run_aggregates VALUES (?,?,?,?,?)", (run.id, run.project_id, run.version, json.dumps(payload, sort_keys=True), run.updated_at))
            self._insert_events(connection, run)

    def get_run(self, run_id: str) -> ResearchRun:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload FROM research_run_aggregates WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"research run not found: {run_id}")
        return run_from_dict(json.loads(row["payload"]))

    def save_run(self, run: ResearchRun, expected_version: int) -> None:
        with self._operation() as connection:
            changed = connection.execute("UPDATE research_run_aggregates SET version=?,payload=?,updated_at=? WHERE id=? AND version=?", (run.version, json.dumps(run_to_dict(run), sort_keys=True), run.updated_at, run.id, expected_version)).rowcount
            if changed != 1:
                raise ConcurrencyConflict("research run version changed")
            self._insert_events(connection, run, after_version=expected_version)

    def _insert_events(self, connection: sqlite3.Connection, run: ResearchRun, after_version: int = 0) -> None:
        for event in run.events:
            if event.aggregate_version <= after_version:
                continue
            connection.execute("INSERT INTO research_run_events VALUES (?,?,?,?,?,?)", (event.id, run.id, event.aggregate_version, event.event_type, json.dumps(dict(event.payload), sort_keys=True), event.occurred_at))

    def list_runs(self, project_id: str) -> list[ResearchRun]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT payload FROM research_run_aggregates WHERE project_id=? ORDER BY updated_at DESC, id DESC", (project_id,)).fetchall()
        return [run_from_dict(json.loads(row["payload"])) for row in rows]

    def verified_artifacts(self, project_id: str, artifact_ids: list[str]) -> list[dict[str, object]]:
        if not artifact_ids:
            return []
        placeholders = ",".join("?" for _ in artifact_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT id, kind, provenance, sha256 FROM research_artifacts "
                f"WHERE project_id=? AND status='verified' AND id IN ({placeholders})",
                (project_id, *artifact_ids),
            ).fetchall()
        return [dict(row) for row in rows]
