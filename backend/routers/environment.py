"""Read-only environment diagnostics and canonical runtime registries."""
from fastapi import APIRouter

from config import PROJECT_ROOT, SKILLS_DIR
from services.capability_registry import build_registry, runtime_candidates
from services.environment_doctor import EnvironmentDoctor
from services.skill_registry import discover

router = APIRouter(prefix="/api/environment", tags=["environment"])


@router.get("/doctor")
async def environment_doctor():
    report = EnvironmentDoctor(PROJECT_ROOT).report()
    capabilities = build_registry(runtime_candidates())
    skills = discover(SKILLS_DIR)
    report["capabilities"] = capabilities["capabilities"]
    report["skill_registry"] = {
        "schema_version": skills["schema_version"],
        "count": skills["count"],
    }
    return report


@router.get("/registry")
async def environment_registry():
    """Return canonical Skill metadata and observable tool availability."""
    return {
        "schema_version": "1.0",
        "skills": discover(SKILLS_DIR),
        "capabilities": build_registry(runtime_candidates()),
    }
