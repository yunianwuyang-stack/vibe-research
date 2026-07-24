"""SQLite and in-memory adapters for the application-owned research port."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

from application.ports import ConcurrencyConflict, EntityNotFound
from domain import Audit, entity_from_dict, entity_to_dict

from .migrations import Migration, MigrationRunner


def _create_research_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE research_entities (
            id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0)
        );
        CREATE TABLE research_links (
            from_id TEXT NOT NULL REFERENCES research_entities(id),
            to_id TEXT NOT NULL REFERENCES research_entities(id),
            relation TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, relation)
        );
        CREATE TABLE research_audits (
            id TEXT PRIMARY KEY REFERENCES research_entities(id),
            entity_id TEXT NOT NULL REFERENCES research_entities(id),
            payload TEXT NOT NULL
        );
        """
    )


RESEARCH_REPOSITORY_MIGRATIONS = (Migration(1, "research_repository_tables", _create_research_tables),)


class InMemoryResearchRepository:
    """Deterministic port adapter for unit tests and offline use-case testing."""

    def __init__(self) -> None:
        self.entities: dict[str, tuple[object, int]] = {}
        self.links: set[tuple[str, str, str]] = set()
        self.audits: list[Audit] = []

    @contextmanager
    def transaction(self):
        snapshot = (dict(self.entities), set(self.links), list(self.audits))
        try:
            yield
        except Exception:
            self.entities, self.links, self.audits = snapshot
            raise

    def create(self, entity: object) -> int:
        entity_id = str(getattr(entity, "id"))
        if entity_id in self.entities:
            raise ConcurrencyConflict("entity already exists")
        self.entities[entity_id] = (entity, 1)
        return 1

    def get(self, entity_id: str) -> tuple[object, int]:
        try:
            return self.entities[entity_id]
        except KeyError as error:
            raise EntityNotFound(entity_id) from error

    def update(self, entity: object, expected_revision: int) -> int:
        entity_id = str(getattr(entity, "id")); _, revision = self.get(entity_id)
        if revision != expected_revision:
            raise ConcurrencyConflict("stale entity revision")
        self.entities[entity_id] = (entity, revision + 1)
        return revision + 1

    def link(self, from_id: str, to_id: str, relation: str) -> None:
        self.get(from_id); self.get(to_id)
        self.links.add((from_id, to_id, relation))

    def record_audit(self, audit: object) -> int:
        if not isinstance(audit, Audit):
            raise TypeError("audit entity required")
        self.get(str(audit.entity_id)); self.entities[str(audit.id)] = (audit, 1); self.audits.append(audit)
        return 1


class SqliteResearchRepository:
    """Transactional SQLite adapter with FK enforcement and optimistic updates."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self._transaction_connection: sqlite3.Connection | None = None

    def migrate(self) -> None:
        MigrationRunner(self.database_path, RESEARCH_REPOSITORY_MIGRATIONS).migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def transaction(self):
        if self._transaction_connection is not None:
            yield
            return
        connection = self._connect()
        self._transaction_connection = connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._transaction_connection = None
            connection.close()

    @contextmanager
    def _operation(self):
        if self._transaction_connection is not None:
            yield self._transaction_connection
            return
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def create(self, entity: object) -> int:
        data = entity_to_dict(entity); entity_id = str(data["id"])
        with self._operation() as connection:
            try:
                connection.execute("INSERT INTO research_entities (id, entity_type, payload) VALUES (?, ?, ?)", (entity_id, data["type"], json.dumps(data, sort_keys=True)))
            except sqlite3.IntegrityError as error:
                raise ConcurrencyConflict("entity already exists") from error
        return 1

    def get(self, entity_id: str) -> tuple[object, int]:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload, revision FROM research_entities WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            raise EntityNotFound(entity_id)
        return entity_from_dict(json.loads(row[0])), int(row[1])

    def update(self, entity: object, expected_revision: int) -> int:
        data = entity_to_dict(entity); entity_id = str(data["id"])
        with self._operation() as connection:
            changed = connection.execute("UPDATE research_entities SET entity_type=?, payload=?, revision=revision+1 WHERE id=? AND revision=?", (data["type"], json.dumps(data, sort_keys=True), entity_id, expected_revision)).rowcount
            if changed != 1:
                raise ConcurrencyConflict("stale or missing entity revision")
        return expected_revision + 1

    def link(self, from_id: str, to_id: str, relation: str) -> None:
        with self._operation() as connection:
            try:
                connection.execute("INSERT OR IGNORE INTO research_links (from_id, to_id, relation) VALUES (?, ?, ?)", (from_id, to_id, relation))
            except sqlite3.IntegrityError as error:
                raise EntityNotFound("link endpoint") from error

    def record_audit(self, audit: object) -> int:
        if not isinstance(audit, Audit):
            raise TypeError("audit entity required")
        data = entity_to_dict(audit)
        with self._operation() as connection:
            connection.execute("INSERT INTO research_entities (id, entity_type, payload) VALUES (?, ?, ?)", (str(audit.id), data["type"], json.dumps(data, sort_keys=True)))
            connection.execute("INSERT INTO research_audits (id, entity_id, payload) VALUES (?, ?, ?)", (str(audit.id), str(audit.entity_id), json.dumps(data, sort_keys=True)))
        return 1
