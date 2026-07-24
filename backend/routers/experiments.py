from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from services import experiment_execution

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class ExecuteExperiment(BaseModel):
    control: list[float] = Field(min_length=2, max_length=10000)
    treatment: list[float] = Field(min_length=2, max_length=10000)
    seeds: int = Field(default=3, ge=1, le=1000)
    metric: str = Field(default="outcome", min_length=1, max_length=100)
    analysis_mode: str = Field(default="exploratory", pattern="^(exploratory|confirmatory)$")
    hypothesis_version_id: str | None = Field(default=None, min_length=1, max_length=128)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    dataset_ref: str | None = Field(default=None, min_length=1, max_length=256)
    execution_purpose: str | None = Field(default=None, min_length=1, max_length=256)


@router.get("/projects/{project_id}")
async def list_project_experiments(project_id: str):
    return await experiment_execution.list_runs(project_id)


@router.post("/projects/{project_id}")
async def execute(project_id: str, body: ExecuteExperiment):
    values: dict[str, Any] = body.model_dump()
    timeout = values.pop("timeout_seconds")
    return await experiment_execution.execute(project_id, values, timeout_seconds=timeout)


@router.post("/{run_id}/replay")
async def replay(run_id: str):
    return await experiment_execution.replay(run_id)


class MathExecution(BaseModel):
    claim: str = Field(min_length=1)
    verifier: str = Field(default="llm", pattern="^(llm|sympy|lean|coq|isabelle)$")
    artifact: str = ""
    replayable: bool = False
    counterexample: dict[str, Any] | None = None

class QualitativeAdmission(BaseModel):
    source_uri: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)
    rights: dict[str, Any]
    coding_scheme_version: str = Field(min_length=1)
    negative_cases: list[str] = Field(min_length=1)
    reflexivity_note: str = Field(min_length=1)
    generated_participants: bool = False

@router.post("/projects/{project_id}/math")
async def execute_math(project_id: str, body: MathExecution):
    from services import scientific_execution
    return await scientific_execution.execute_math(project_id, body.model_dump())

@router.post("/projects/{project_id}/qualitative")
async def admit_qualitative(project_id: str, body: QualitativeAdmission):
    from services import scientific_execution
    return await scientific_execution.admit_qualitative(project_id, body.model_dump())
