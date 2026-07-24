"""Contracts for the framework-free research domain."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from domain import (
    Approval, Artifact, Audit, Claim, ClaimStatus, Decision, EvidenceItem, EvidenceRelation,
    Experiment, ExperimentRun, Hypothesis, HypothesisStatus, Project, ResearchQuestion,
    Result, Source, SourcePassage, entity_from_dict, entity_to_dict,
)
from domain.entities import Locator


HASH = "a" * 64


def test_complete_research_entity_graph_round_trips_through_mapper() -> None:
    project = Project("Mechanism study")
    question = ResearchQuestion(project.id, "Why does effect X occur?")
    hypothesis = Hypothesis(question.id, "X has mechanism Y", "Y transfers energy", "X rises", "X does not rise", "Only at low temperature", HypothesisStatus.ACTIVE)
    claim = Claim(project.id, "X rises under condition C", "causal explanation", ClaimStatus.SUPPORTED)
    source = Source("Source", "https://example.test/source")
    passage = SourcePassage(source.id, "Observed X rising.", Locator("p. 4, Fig. 2"))
    evidence = EvidenceItem(claim.id, passage.id, EvidenceRelation.SUPPORT, Locator("p. 4, Fig. 2"))
    experiment = Experiment(project.id, "Run the preregistered protocol")
    run = ExperimentRun(experiment.id, HASH)
    result = Result(run.id, "Effect reproduced", True)
    artifact = Artifact(run.id, "artifact://run/output", HASH, "1.0", "analysis", (HASH,))
    decision = Decision(project.id, "scope", "Keep the boundary explicit")
    audit = Audit(claim.id, "created", "researcher")
    approval = Approval(claim.id, "supervisor", "approved")

    for entity in (project, question, hypothesis, claim, source, passage, evidence, experiment, run, result, artifact, decision, audit, approval):
        assert entity_from_dict(entity_to_dict(entity)) == entity


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: Project(" "), "title"),
        (lambda: Hypothesis("q", "s", "", "p", "f", "b"), "mechanism"),
        (lambda: Claim("p", "claim", "intent", "invented"), "status"),
        (lambda: EvidenceItem("c", "p", "positive", Locator("p. 1")), "relation"),
        (lambda: EvidenceItem("c", "p", EvidenceRelation.SUPPORT, Locator(" ")), "locator"),
        (lambda: ExperimentRun("e", "bad"), "SHA-256"),
        (lambda: Approval("e", "person", "maybe"), "approval"),
    ],
)
def test_invalid_domain_states_cannot_be_constructed(factory, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_domain_does_not_import_delivery_or_persistence_frameworks() -> None:
    root = Path(__file__).resolve().parents[1] / "backend" / "domain"
    forbidden = ("fastapi", "pydantic", "sqlite", "aiosqlite", "sqlalchemy")
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert not any(f"import {name}" in text or f"from {name}" in text for name in forbidden)


def test_claim_states_are_closed_and_entities_are_plain_dataclasses() -> None:
    assert {item.value for item in ClaimStatus} == {"proposed", "supported", "contradicted", "mixed", "unresolved", "retracted"}
    assert {item.value for item in EvidenceRelation} == {"support", "contradict", "qualify"}
    assert {field.name for field in fields(Hypothesis)} >= {"mechanism", "prediction", "falsifier", "boundary", "status"}
