"""Use-case contracts shared by the in-memory and real SQLite adapters."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from application.ports import ConcurrencyConflict, EntityNotFound
from application.research_service import ResearchService
from domain import Claim, ClaimStatus, EvidenceItem, EvidenceRelation, Project, Source, SourcePassage
from domain.entities import Locator
from infrastructure.persistence.research_repository import InMemoryResearchRepository, SqliteResearchRepository


def _exercise(repository) -> None:
    service = ResearchService(repository, actor="tester")
    project = Project("Evidence graph")
    claim = Claim(project.id, "Effect is reproducible", "result claim")
    source = Source("Paper", "https://example.test/paper")
    passage = SourcePassage(source.id, "Reproduced in cohort.", Locator("p. 2"))
    for entity in (project, claim, source, passage):
        assert service.create(entity) == 1
    evidence = EvidenceItem(claim.id, passage.id, EvidenceRelation.SUPPORT, Locator("p. 2"))
    assert service.link_evidence(evidence) == 1
    approval = service.approve(str(claim.id), "supervisor")
    retracted_revision = service.retract_claim(str(claim.id), 1)
    persisted_claim, revision = repository.get(str(claim.id))
    assert revision == retracted_revision == 2
    assert persisted_claim.status is ClaimStatus.RETRACTED
    assert approval.decision == "approved"


def test_in_memory_use_cases_work_without_real_database() -> None:
    _exercise(InMemoryResearchRepository())


def test_sqlite_use_cases_enforce_foreign_keys_and_transactions(tmp_path: Path) -> None:
    repository = SqliteResearchRepository(tmp_path / "research.db")
    repository.migrate()
    _exercise(repository)
    with pytest.raises(EntityNotFound):
        repository.link("missing", "also-missing", "invalid")
    with sqlite3.connect(tmp_path / "research.db") as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0  # connection-local; adapter verifies it itself
        assert connection.execute("SELECT COUNT(*) FROM research_links").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM research_audits").fetchone()[0] >= 6


def test_stale_update_is_rejected_without_overwriting_newer_entity(tmp_path: Path) -> None:
    repository = SqliteResearchRepository(tmp_path / "research.db"); repository.migrate()
    project = Project("Versioned")
    repository.create(project)
    repository.update(replace(project, description="first"), 1)
    with pytest.raises(ConcurrencyConflict):
        repository.update(replace(project, description="stale"), 1)
    restored, revision = repository.get(str(project.id))
    assert restored.description == "first" and revision == 2


def _assert_link_evidence_rolls_back(repository) -> None:
    service = ResearchService(repository)
    project = Project("Atomic links"); claim = Claim(project.id, "Claim", "intent")
    service.create(project); service.create(claim)
    evidence = EvidenceItem(claim.id, "missing-passage", EvidenceRelation.SUPPORT, Locator("p. 1"))
    with pytest.raises(EntityNotFound):
        service.link_evidence(evidence)
    with pytest.raises(EntityNotFound):
        repository.get(str(evidence.id))


def test_in_memory_link_evidence_is_atomic() -> None:
    _assert_link_evidence_rolls_back(InMemoryResearchRepository())


def test_sqlite_link_evidence_is_atomic_and_releases_database_file(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    repository = SqliteResearchRepository(database); repository.migrate()
    _assert_link_evidence_rolls_back(repository)
    database.unlink()
