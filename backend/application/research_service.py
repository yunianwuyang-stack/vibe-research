"""Use cases; all mutation flows through a repository port."""

from __future__ import annotations

from dataclasses import replace

from domain import Approval, Audit, Claim, ClaimStatus, EvidenceItem

from .ports import ResearchRepository


class ResearchService:
    def __init__(self, repository: ResearchRepository, actor: str = "system") -> None:
        self.repository = repository
        self.actor = actor

    def create(self, entity: object) -> int:
        revision = self.repository.create(entity)
        self.repository.record_audit(Audit(str(getattr(entity, "id")), "created", self.actor))
        return revision

    def update(self, entity: object, expected_revision: int) -> int:
        revision = self.repository.update(entity, expected_revision)
        self.repository.record_audit(Audit(str(getattr(entity, "id")), "updated", self.actor))
        return revision

    def link_evidence(self, evidence: EvidenceItem) -> int:
        with self.repository.transaction():
            revision = self.create(evidence)
            self.repository.link(str(evidence.claim_id), str(evidence.id), "has_evidence")
            self.repository.link(str(evidence.id), str(evidence.source_passage_id), "uses_passage")
        return revision

    def approve(self, entity_id: str, approver: str) -> Approval:
        with self.repository.transaction():
            self.repository.get(entity_id)
            approval = Approval(entity_id, approver, "approved")
            self.create(approval)
            self.repository.link(str(approval.id), entity_id, "approves")
        return approval

    def retract_claim(self, claim_id: str, expected_revision: int) -> int:
        claim, revision = self.repository.get(claim_id)
        if not isinstance(claim, Claim):
            raise TypeError("only claims can be retracted")
        if revision != expected_revision:
            from .ports import ConcurrencyConflict
            raise ConcurrencyConflict("claim revision changed before retraction")
        return self.update(replace(claim, status=ClaimStatus.RETRACTED), expected_revision)
