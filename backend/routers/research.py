from typing import Any

from pydantic import BaseModel, Field
from fastapi import APIRouter
from services import adversarial_review, assurance, claim_evidence, evidence_screening, hypothesis_lifecycle, innovation_check, research_contracts, p5_research_design

router = APIRouter(prefix="/api/research-projects", tags=["research-projects"])
class CreateContract(BaseModel):
    title: str = Field(min_length=1)
    research_question: str = Field(min_length=1)
    inclusion_criteria: str = Field(min_length=1)
class Evidence(BaseModel):
    kind: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    provenance: str = Field(min_length=1)
    content: str = Field(min_length=1)
class ProviderEvidence(BaseModel):
    provider: str = Field(pattern=r"^(openalex|crossref|datacite|arxiv|semantic_scholar)$")
    query: str = Field(min_length=3)
    source_url: str = Field(min_length=8)
class Approval(BaseModel):
    actor: str = Field(min_length=1)
    approved: bool
    reason: str = Field(min_length=1)
class SaveProviderEvidence(BaseModel):
    provider: str = Field(pattern=r"^(openalex|crossref|datacite|arxiv|semantic_scholar)$")
    query: str = Field(min_length=3)
    source_url: str = Field(min_length=8)
    snapshot_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
class EvidenceReview(BaseModel):
    actor: str = Field(min_length=1)
    decision: str = Field(pattern=r"^(approved|rejected)$")
    reason: str = Field(min_length=1)
class ClaimEvidenceLink(BaseModel):
    claim_id: str = Field(min_length=1, max_length=240)
    evidence_card_id: str = Field(min_length=1, max_length=64)
    relation: str = Field(pattern=r"^(supports|contradicts|context)$")
    passage: str = Field(min_length=1, max_length=12000)
    locator: str = Field(default="", max_length=500)


class ClaimExperimentLink(BaseModel):
    claim_id: str = Field(min_length=1, max_length=240)
    experiment_run_id: str = Field(min_length=1, max_length=64)
    relation: str = Field(pattern=r"^(supports|contradicts|context)$")
    result_locator: str = Field(min_length=1, max_length=500)
    interpretation: str = Field(min_length=1, max_length=12000)
    evidence_card_ids: list[str] = Field(min_length=1, max_length=100)
class AdversarialReviewRequest(BaseModel):
    mode: str = Field(default="deterministic", pattern=r"^(deterministic|model)$")
class InnovationCheckRequest(BaseModel):
    actor: str = Field(default="researcher", min_length=1, max_length=240)
    claims: list[str] | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    provider: str | None = Field(default=None, pattern=r"^(openalex|crossref|datacite|arxiv|semantic_scholar)$")
class ScreeningProtocol(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    inclusion_criteria: str = Field(min_length=3, max_length=12000)
    exclusion_criteria: str = Field(min_length=3, max_length=12000)
    source_strategy: str = Field(min_length=3, max_length=12000)
    actor: str = Field(min_length=1, max_length=240)
class ScreeningActivation(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
class ScreeningDecision(BaseModel):
    decision: str = Field(pattern=r"^(included|excluded|uncertain)$")
    reason: str = Field(min_length=1, max_length=4000)
    actor: str = Field(min_length=1, max_length=240)


class P5DesignRequest(BaseModel):
    contribution: dict[str, Any]
    profile_type: str = Field(min_length=1)
    profile: dict[str, Any]
    actor: str = Field(min_length=1, max_length=240)


class P5PriorArtRequest(BaseModel):
    freeze_date: str = Field(min_length=1)
    query: dict[str, Any]
    entries: list[dict[str, Any]]
    actor: str = Field(min_length=1, max_length=240)


class P5ProtocolRequest(BaseModel):
    protocol: dict[str, Any]
    analysis_mode: str = Field(pattern=r"^(exploratory|confirmatory)$")
    actor: str = Field(min_length=1, max_length=240)


class P5EthicsRequest(BaseModel):
    assessment: dict[str, Any]
    actor: str = Field(min_length=1, max_length=240)


class HypothesisWrite(BaseModel):
    statement: str = Field(min_length=1, max_length=12000)
    mechanism: str = Field(min_length=1, max_length=12000)
    prediction: str = Field(min_length=1, max_length=12000)
    falsification_criteria: str = Field(min_length=1, max_length=12000)
    boundary_conditions: str = Field(min_length=1, max_length=12000)
    actor: str = Field(min_length=1, max_length=240)
    change_reason: str = Field(min_length=1, max_length=4000)


class HypothesisTransition(BaseModel):
    actor: str = Field(min_length=1, max_length=240)
    reason: str = Field(min_length=1, max_length=4000)


async def _transition_hypothesis(project_id: str, version_id: str, action: str, body: HypothesisTransition):
    await hypothesis_lifecycle.transition(project_id, version_id, action, **body.model_dump())
    return await research_contracts.get_contract(project_id)


@router.post("")
async def create(body: CreateContract): return await research_contracts.create_contract(**body.model_dump())
@router.get("")
async def list_projects(): return await research_contracts.list_contracts()
@router.post("/{project_id}/hypotheses")
async def create_hypothesis(project_id: str, body: HypothesisWrite):
    value = body.model_dump()
    actor = value.pop("actor")
    reason = value.pop("change_reason")
    await hypothesis_lifecycle.create(project_id, value, actor, reason)
    return await research_contracts.get_contract(project_id)
@router.post("/{project_id}/hypotheses/{version_id}/revisions")
async def revise_hypothesis(project_id: str, version_id: str, body: HypothesisWrite):
    value = body.model_dump()
    actor = value.pop("actor")
    reason = value.pop("change_reason")
    await hypothesis_lifecycle.revise(project_id, version_id, value, actor, reason)
    return await research_contracts.get_contract(project_id)
@router.post("/{project_id}/hypotheses/{version_id}/freeze")
async def freeze_hypothesis(project_id: str, version_id: str, body: HypothesisTransition):
    return await _transition_hypothesis(project_id, version_id, "freeze", body)
@router.post("/{project_id}/hypotheses/{version_id}/unfreeze")
async def unfreeze_hypothesis(project_id: str, version_id: str, body: HypothesisTransition):
    return await _transition_hypothesis(project_id, version_id, "unfreeze", body)
@router.post("/{project_id}/hypotheses/{version_id}/falsify")
async def falsify_hypothesis(project_id: str, version_id: str, body: HypothesisTransition):
    return await _transition_hypothesis(project_id, version_id, "falsify", body)
@router.get("/{project_id}")
async def get(project_id: str): return await research_contracts.get_contract(project_id)
@router.post("/{project_id}/evidence")
async def evidence(project_id: str, body: Evidence): return await research_contracts.add_evidence(project_id, **body.model_dump())
@router.post("/{project_id}/provider-evidence")
async def provider_evidence(project_id: str, body: ProviderEvidence): return await research_contracts.verify_provider_evidence(project_id, **body.model_dump())
@router.post("/{project_id}/evidence-cards")
async def save_evidence_card(project_id: str, body: SaveProviderEvidence): return await research_contracts.save_provider_evidence(project_id, **body.model_dump())
@router.post("/{project_id}/evidence-cards/{card_id}/review")
async def review_evidence_card(project_id: str, card_id: str, body: EvidenceReview): return await research_contracts.review_evidence_card(project_id, card_id, **body.model_dump())
@router.post("/{project_id}/evidence-cards/{card_id}/claim-support")
async def review_claim_support(project_id: str, card_id: str, body: EvidenceReview): return await research_contracts.review_claim_support(project_id, card_id, **body.model_dump())
@router.get("/{project_id}/screening")
async def get_screening(project_id: str): return await evidence_screening.read(project_id)
@router.put("/{project_id}/screening/protocol")
async def save_screening_protocol(project_id: str, body: ScreeningProtocol): return await evidence_screening.save_protocol(project_id, **body.model_dump())
@router.post("/{project_id}/screening/activate")
async def activate_screening_protocol(project_id: str, body: ScreeningActivation): return await evidence_screening.activate(project_id, **body.model_dump())
@router.post("/{project_id}/screening/evidence-cards/{card_id}")
async def record_screening_decision(project_id: str, card_id: str, body: ScreeningDecision): return await evidence_screening.decide(project_id, card_id, **body.model_dump())
@router.post("/{project_id}/screening/prisma")
async def export_screening_prisma(project_id: str): return await evidence_screening.export_prisma(project_id)
@router.get("/{project_id}/claim-evidence-graph")
async def claim_evidence_graph(project_id: str): return await claim_evidence.read_graph(project_id)
@router.post("/{project_id}/claim-evidence-links")
async def create_claim_evidence_link(project_id: str, body: ClaimEvidenceLink): return await claim_evidence.create_link(project_id, body.model_dump())
@router.post("/{project_id}/claim-evidence-links/{link_id}/review")
async def review_claim_evidence_link(project_id: str, link_id: str, body: EvidenceReview): return await claim_evidence.review_link(project_id, link_id, **body.model_dump())
@router.post("/{project_id}/claim-experiment-links")
async def create_claim_experiment_link(project_id: str, body: ClaimExperimentLink): return await claim_evidence.create_experiment_link(project_id, body.model_dump())
@router.post("/{project_id}/claim-experiment-links/{link_id}/review")
async def review_claim_experiment_link(project_id: str, link_id: str, body: EvidenceReview): return await claim_evidence.review_experiment_link(project_id, link_id, **body.model_dump())
@router.get("/{project_id}/adversarial-reviews")
async def list_adversarial_reviews(project_id: str): return await adversarial_review.list_reviews(project_id)
@router.post("/{project_id}/adversarial-reviews")
async def run_adversarial_review(project_id: str, body: AdversarialReviewRequest): return await adversarial_review.run(project_id, body.mode)
@router.get("/{project_id}/innovation-check")
async def get_innovation_check(project_id: str): return await innovation_check.read(project_id)
@router.post("/{project_id}/innovation-check")
async def run_innovation_check(project_id: str, body: InnovationCheckRequest):
    return await innovation_check.run(
        project_id,
        actor=body.actor,
        claims=body.claims,
        overrides=body.overrides,
        provider=body.provider,
    )
@router.get("/{project_id}/p5")
async def get_p5_research_design(project_id: str): return await p5_research_design.read(project_id)
@router.get("/{project_id}/p5/gate")
async def get_p5_gate(project_id: str): return await p5_research_design.gate(project_id)
@router.post("/{project_id}/p5/design")
async def save_p5_design(project_id: str, body: P5DesignRequest): return await p5_research_design.save_design(project_id, **body.model_dump())
@router.post("/{project_id}/p5/prior-art")
async def freeze_p5_prior_art(project_id: str, body: P5PriorArtRequest): return await p5_research_design.freeze_prior_art(project_id, **body.model_dump())
@router.post("/{project_id}/p5/protocol")
async def save_p5_protocol(project_id: str, body: P5ProtocolRequest): return await p5_research_design.save_protocol(project_id, **body.model_dump())
@router.post("/{project_id}/p5/ethics")
async def assess_p5_ethics(project_id: str, body: P5EthicsRequest): return await p5_research_design.assess_ethics(project_id, **body.model_dump())
@router.get("/{project_id}/assurance")
async def get_assurance(project_id: str): return await assurance.read(project_id)
@router.post("/{project_id}/approval")
async def approval(project_id: str, body: Approval): return await research_contracts.approve(project_id, **body.model_dump())
