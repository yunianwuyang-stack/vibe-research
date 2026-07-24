"""Contract fixtures for the forward-only SQLite migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from infrastructure.persistence.migrations import Migration, MigrationRunner


def _create_items(connection: sqlite3.Connection) -> None:
    connection.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT NOT NULL)")


def _add_status(connection: sqlite3.Connection) -> None:
    connection.execute("ALTER TABLE items ADD COLUMN status TEXT NOT NULL DEFAULT 'new'")


MIGRATIONS = (
    Migration(1, "create_items", _create_items),
    Migration(2, "add_status", _add_status),
)


def test_empty_database_applies_forward_migrations_and_records_versions(tmp_path: Path) -> None:
    database = tmp_path / "research.db"

    result = MigrationRunner(database, MIGRATIONS).migrate()

    assert result.applied_versions == (1, 2)
    assert result.backup_path is None
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall() == [(1,), (2,)]
        assert connection.execute("PRAGMA table_info(items)").fetchall()[-1][1] == "status"


def test_old_schema_is_backed_up_before_forward_migration(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    with sqlite3.connect(database) as connection:
        _create_items(connection)
        connection.execute("INSERT INTO items(title) VALUES ('old evidence')")

    result = MigrationRunner(database, (Migration(2, "add_status", _add_status),), tmp_path / "backups").migrate()

    assert result.applied_versions == (2,)
    assert result.backup_path is not None and result.backup_path.exists()
    with sqlite3.connect(result.backup_path) as backup:
        assert backup.execute("PRAGMA table_info(items)").fetchall()[-1][1] == "title"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT title, status FROM items").fetchall() == [("old evidence", "new")]


def test_repeated_migration_is_idempotent_and_does_not_make_a_second_backup(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    runner = MigrationRunner(database, MIGRATIONS, tmp_path / "backups")
    first = runner.migrate()
    second = runner.migrate()

    assert first.applied_versions == (1, 2)
    assert second.applied_versions == ()
    assert second.backup_path is None
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 0


def test_failed_migration_rolls_back_schema_and_version_record(tmp_path: Path) -> None:
    database = tmp_path / "research.db"

    def broken(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE should_not_survive (id INTEGER PRIMARY KEY)")
        raise RuntimeError("fixture failure")

    with pytest.raises(RuntimeError, match="fixture failure"):
        MigrationRunner(database, (Migration(1, "broken", broken),), tmp_path / "backups").migrate()

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='should_not_survive'").fetchone() is None
        assert connection.execute("SELECT version FROM schema_migrations").fetchall() == []
