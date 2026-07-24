"""Small, explicit SQLite migration framework.

Database changes are declared as ordered forward migrations.  This module has
no import-time side effects and intentionally does not inspect tables to issue
ad-hoc ``ALTER TABLE`` statements during application startup.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3


MigrationOperation = Callable[[sqlite3.Connection], None]


@dataclass(frozen=True)
class Migration:
    """One immutable, forward-only schema change."""

    version: int
    name: str
    apply: MigrationOperation


@dataclass(frozen=True)
class MigrationResult:
    """Observable outcome of a migration invocation."""

    applied_versions: tuple[int, ...]
    backup_path: Path | None


class MigrationRunner:
    """Apply registered SQLite migrations transactionally and exactly once."""

    def __init__(
        self,
        database_path: str | Path,
        migrations: Iterable[Migration],
        backup_directory: str | Path | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.migrations = tuple(sorted(migrations, key=lambda item: item.version))
        self.backup_directory = (
            Path(backup_directory)
            if backup_directory is not None
            else self.database_path.parent / "backups"
        )
        self._validate_migrations()

    def migrate(self) -> MigrationResult:
        """Apply pending migrations; a failed migration leaves no partial DDL."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        existed_before_open = self.database_path.exists()
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            applied = self._applied_versions(connection)
            pending = tuple(
                item for item in self.migrations if item.version not in applied
            )
            backup_path = (
                self._backup_existing_database()
                if pending and existed_before_open
                else None
            )
            self._ensure_version_table(connection)

            completed: list[int] = []
            for migration in pending:
                # Use an explicit transaction: ``sqlite3`` otherwise starts
                # one lazily only for DML, allowing a failing DDL migration to
                # escape rollback in autocommit mode.
                connection.execute("BEGIN IMMEDIATE")
                try:
                    migration.apply(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                        (migration.version, migration.name),
                    )
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
                completed.append(migration.version)
        # The connection context manager commits/rolls back but does not close
        # the handle on all supported Python versions (notably Windows).
        # Closing here keeps migrated database files movable immediately.
        connection.close()
        return MigrationResult(tuple(completed), backup_path)

    # Back-compat alias used by product init paths.
    def apply(self) -> MigrationResult:
        return self.migrate()

    def _applied_versions(self, connection: sqlite3.Connection) -> set[int]:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not exists:
            return set()
        return {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }

    @staticmethod
    def _ensure_version_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )

    def _backup_existing_database(self) -> Path | None:
        if not self.database_path.exists():
            return None
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = (
            self.backup_directory
            / f"{self.database_path.stem}-{timestamp}.sqlite3"
        )
        shutil.copy2(self.database_path, target)
        return target

    def _validate_migrations(self) -> None:
        versions = [item.version for item in self.migrations]
        if any(version < 1 for version in versions) or len(versions) != len(
            set(versions)
        ):
            raise ValueError("migration versions must be unique positive integers")
        if any(not item.name.strip() for item in self.migrations):
            raise ValueError("migration names must not be empty")


def _apply_agent_task_lease_columns(connection: sqlite3.Connection) -> None:
    """Forward-only product migration: lease columns + lease table for agent_tasks."""
    # Table may not exist yet on brand-new empty fixture DBs; schema.sql owns
    # greenfield creation. Only mutate when agent_tasks already exists.
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_tasks'"
    ).fetchone()
    if not exists:
        return
    existing = {
        row[1]
        for row in connection.execute("PRAGMA table_info(agent_tasks)").fetchall()
    }
    for column, ddl in (
        ("lease_owner", "TEXT"),
        ("lease_expires_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
    ):
        if column not in existing:
            connection.execute(f"ALTER TABLE agent_tasks ADD COLUMN {column} {ddl}")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS agent_task_leases ("
        "task_id TEXT PRIMARY KEY REFERENCES agent_tasks(id), "
        "owner TEXT NOT NULL, "
        "acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
        "expires_at TEXT NOT NULL, "
        "released_at TEXT)"
    )


# Product migration registry. New installs get lease columns from schema.sql;
# existing DBs receive them exactly once via this ordered runner.
PRODUCT_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="agent_task_lease_columns",
        apply=_apply_agent_task_lease_columns,
    ),
)
