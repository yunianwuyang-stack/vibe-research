"""Framework-free entities and value objects for the research evidence graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import NewType
from uuid import uuid4


EntityId = NewType("EntityId", str)


def new_entity_id() -> EntityId:
    return EntityId(str(uuid4()))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ClaimStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    MIXED = "mixed"
    UNRESOLVED = "unresolved"
    RETRACTED = "retracted"


class HypothesisStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPPORTED = "supported"
    FALSIFIED = "falsified"
    RETIRED = "retired"


class EvidenceRelation(str, Enum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    QUALIFY = "qualify"


@dataclass(frozen=True)
class Locator:
    """A stable pointer to the precise place supporting an evidence assertion."""

    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("evidence locator must not be empty")


@dataclass(frozen=True)
class Project:
    title: str
    description: str = ""
    id: EntityId = field(default_factory=new_entity_id)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("project title must not be empty")


@dataclass(frozen=True)
class ResearchQuestion:
    project_id: EntityId
    text: str
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("research question text must not be empty")


@dataclass(frozen=True)
class Hypothesis:
    question_id: EntityId
    statement: str
    mechanism: str
    prediction: str
    falsifier: str
    boundary: str
    status: HypothesisStatus = HypothesisStatus.DRAFT
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        for name in ("statement", "mechanism", "prediction", "falsifier", "boundary"):
            if not getattr(self, name).strip():
                raise ValueError(f"hypothesis {name} must not be empty")
        if not isinstance(self.status, HypothesisStatus):
            raise ValueError("hypothesis status is invalid")


@dataclass(frozen=True)
class Claim:
    project_id: EntityId
    statement: str
    intent: str
    status: ClaimStatus = ClaimStatus.PROPOSED
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.statement.strip() or not self.intent.strip():
            raise ValueError("claim statement and intent must not be empty")
        if not isinstance(self.status, ClaimStatus):
            raise ValueError("claim status is invalid")


@dataclass(frozen=True)
class Source:
    title: str
    canonical_url: str
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.canonical_url.strip():
            raise ValueError("source title and canonical URL must not be empty")


@dataclass(frozen=True)
class SourcePassage:
    source_id: EntityId
    text: str
    locator: Locator
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("source passage text must not be empty")


@dataclass(frozen=True)
class EvidenceItem:
    claim_id: EntityId
    source_passage_id: EntityId
    relation: EvidenceRelation
    locator: Locator
    rationale: str = ""
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not isinstance(self.relation, EvidenceRelation):
            raise ValueError("evidence relation must be support, contradict, or qualify")


@dataclass(frozen=True)
class Experiment:
    project_id: EntityId
    protocol: str
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.protocol.strip():
            raise ValueError("experiment protocol must not be empty")


@dataclass(frozen=True)
class ExperimentRun:
    experiment_id: EntityId
    manifest_hash: str
    id: EntityId = field(default_factory=new_entity_id)
    started_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if len(self.manifest_hash) != 64 or any(char not in "0123456789abcdef" for char in self.manifest_hash.lower()):
            raise ValueError("experiment run manifest hash must be SHA-256")


@dataclass(frozen=True)
class Result:
    run_id: EntityId
    summary: str
    verified: bool = False
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("result summary must not be empty")


@dataclass(frozen=True)
class Artifact:
    run_id: EntityId
    uri: str
    sha256: str
    schema_version: str
    producer: str
    input_hashes: tuple[str, ...] = ()
    id: EntityId = field(default_factory=new_entity_id)

    def __post_init__(self) -> None:
        if not all((self.uri.strip(), self.schema_version.strip(), self.producer.strip())):
            raise ValueError("artifact URI, schema version, and producer must not be empty")
        hashes = (self.sha256, *self.input_hashes)
        if any(len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()) for value in hashes):
            raise ValueError("artifact hashes must be SHA-256")


@dataclass(frozen=True)
class Decision:
    project_id: EntityId
    kind: str
    rationale: str
    id: EntityId = field(default_factory=new_entity_id)
    recorded_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.rationale.strip():
            raise ValueError("decision kind and rationale must not be empty")


@dataclass(frozen=True)
class Audit:
    entity_id: EntityId
    action: str
    actor: str
    id: EntityId = field(default_factory=new_entity_id)
    recorded_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.action.strip() or not self.actor.strip():
            raise ValueError("audit action and actor must not be empty")


@dataclass(frozen=True)
class Approval:
    entity_id: EntityId
    approver: str
    decision: str
    id: EntityId = field(default_factory=new_entity_id)
    approved_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not self.approver.strip() or self.decision not in {"approved", "rejected"}:
            raise ValueError("approval must have an approver and approved/rejected decision")
