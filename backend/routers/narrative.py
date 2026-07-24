from fastapi import APIRouter
from pydantic import BaseModel, Field

from services import scientific_narrative

router = APIRouter(prefix="/api/research-projects/{project_id}/narrative", tags=["scientific-narrative"])


class NarrativeMap(BaseModel):
    question: str = Field(min_length=1)
    tension: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    hypotheses: list[str] = Field(min_length=1)
    claims: list[str] = Field(min_length=1)
    competing_explanations: list[str] = Field(min_length=1)
    boundaries: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)


class Approval(BaseModel): actor: str = Field(min_length=1)
class Audit(BaseModel): text: str = Field(min_length=1); causal_identified: bool = False

@router.get("")
async def read(project_id: str): return await scientific_narrative.read_map(project_id)
@router.put("")
async def save(project_id: str, body: NarrativeMap): return await scientific_narrative.save_map(project_id, body.model_dump())
@router.post("/approve")
async def approve(project_id: str, body: Approval): return await scientific_narrative.approve_map(project_id, body.actor)
@router.post("/audit")
async def audit(project_id: str, body: Audit): return await scientific_narrative.audit_text(project_id, body.text, causal_identified=body.causal_identified)
