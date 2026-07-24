from __future__ import annotations

import sqlite3

import pytest

from application.ports import ConcurrencyConflict
from domain import RunStatus, new_run, transition_run
from infrastructure.persistence.research_run_repository import SqliteResearchRunRepository


def _project_schema(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE research_projects (id TEXT PRIMARY KEY, title TEXT NOT NULL, research_question TEXT NOT NULL, inclusion_criteria TEXT NOT NULL)")
    connection.execute("INSERT INTO research_projects VALUES ('project-1', 'Study', 'Why?', '{}')")


def test_sqlite_repository_round_trips_aggregate_and_events(tmp_path):
    database = tmp_path / "runs.sqlite3"
    with sqlite3.connect(database) as connection:
        _project_schema(connection)

    repository = SqliteResearchRunRepository(database)
    repository.migrate()
    run = new_run("project-1", (("analyze", ("evidence",)),), run_id="run-1")
    repository.create_run(run)
    updated = transition_run(run, RunStatus.RUNNING, actor="researcher")
    repository.save_run(updated, expected_version=run.version)

    restored = repository.get_run("run-1")
    assert restored == updated
    assert [event.aggregate_version for event in restored.events] == [1, 2]
    assert repository.list_runs("project-1") == [updated]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM research_run_events WHERE run_id='run-1'").fetchone()[0] == 2


def test_sqlite_repository_rejects_stale_save(tmp_path):
    database = tmp_path / "runs.sqlite3"
    with sqlite3.connect(database) as connection:
        _project_schema(connection)
    repository = SqliteResearchRunRepository(database)
    repository.migrate()
    run = new_run("project-1", (("analyze", ()),), run_id="run-1")
    repository.create_run(run)
    updated = transition_run(run, RunStatus.RUNNING)
    repository.save_run(updated, expected_version=run.version)
    with pytest.raises(ConcurrencyConflict):
        repository.save_run(updated, expected_version=run.version)
