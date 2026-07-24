from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from application.golden_path import GOLDEN_PATH
from application.research_run_engine import ResearchRunEngine, RunAdvance
from config import DB_PATH
from infrastructure.persistence.research_run_repository import SqliteResearchRunRepository
from services.capability_graph import build as capability_graph

router = APIRouter(prefix="/api/research-runs", tags=["research-runs"])
_repository = SqliteResearchRunRepository(DB_PATH)
_engine = ResearchRunEngine(_repository, default_task_specs=tuple((step.name, step.gates) for step in GOLDEN_PATH))

class Advance(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    gate_passed: bool
    failure_reason: str | None = None

class Cancel(BaseModel):
    reason: str = Field(min_length=1)

def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError): return HTTPException(404, str(error).strip("'"))
    if isinstance(error, ValueError): return HTTPException(409, str(error))
    return HTTPException(500, "research run operation failed")

@router.get("/capability-graph")
async def graph(request: Request):
    result = capability_graph()
    result["registered_routes"] = sorted({getattr(route, "path", "") for route in request.app.routes if getattr(route, "path", "").startswith("/api/")})
    result["production_wiring"] = {"research_projects":"/api/research-projects", "research_runs":"/api/research-runs", "literature":"/api/literature/search", "mutation_owner":"application.research_run_engine.ResearchRunEngine"}
    return result

@router.get("/projects/{project_id}")
async def list_for_project(project_id: str):
    try: return _engine.list_for_project(project_id)
    except Exception as error: raise _http_error(error) from error

@router.post("/projects/{project_id}")
async def start(project_id: str):
    try: return _engine.create(project_id)
    except Exception as error: raise _http_error(error) from error

@router.get("/{run_id}")
async def get(run_id: str):
    try: return _engine.read(run_id)
    except Exception as error: raise _http_error(error) from error

@router.post("/{run_id}/steps/{name}")
async def advance(run_id: str, name: str, body: Advance):
    try: return _engine.advance(RunAdvance(run_id, name, body.input, body.artifacts, body.provenance, body.gate_passed, body.failure_reason))
    except Exception as error: raise _http_error(error) from error

@router.post("/{run_id}/cancel")
async def cancel(run_id: str, body: Cancel):
    try: return _engine.cancel(run_id, body.reason)
    except Exception as error: raise _http_error(error) from error

@router.post("/{run_id}/steps/{name}/retry")
async def retry(run_id: str, name: str):
    try: return _engine.retry(run_id, name)
    except Exception as error: raise _http_error(error) from error

@router.post("/{run_id}/resume")
async def resume(run_id: str):
    try: return _engine.resume(run_id)
    except Exception as error: raise _http_error(error) from error
