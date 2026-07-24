"""Source-level proof that workbench UI wires research-run lifecycle endpoints.

Does not count as product_complete alone — pairs with dual-clean research-runs E2E
for API→executor→persistence and frontend vitest for client request bodies.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
MAIN = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
TEST = (ROOT / "frontend" / "src" / "main.test.ts").read_text(encoding="utf-8")


def test_api_client_exposes_research_run_lifecycle() -> None:
    for needle in (
        "export type ResearchRun=",
        "export type ResearchRunList=",
        "export const startResearchRun=",
        "export const listResearchRuns=",
        "export const getResearchRun=",
        "export const advanceResearchRunStep=",
        "export const retryResearchRunStep=",
        "export const resumeResearchRun=",
        "export const cancelResearchRun=",
        "/api/research-runs/projects/",
        "/api/research-runs/${runId}/steps/",
        "/api/research-runs/${runId}/resume",
        "/api/research-runs/${runId}/cancel",
        "gate_passed",
    ):
        assert needle in API, needle


def test_workbench_binds_lifecycle_handlers_and_controls() -> None:
    for needle in (
        "startResearchRun",
        "listResearchRuns",
        "getResearchRun",
        "advanceResearchRunStep",
        "retryResearchRunStep",
        "resumeResearchRun",
        "cancelResearchRun",
        "advanceRun(true)",
        "advanceRun(false)",
        "retryRunStep",
        "resumeRun",
        "cancelRun",
        "restoreRun",
        "openResearchRun",
        "refreshResearchRunList",
        "researchRuns",
        "研究流程历史",
        "门禁推进",
        "诚实阻断",
        "重试阻塞步",
        "恢复运行",
        "恢复流程",
        "取消流程",
        "verifiedArtifacts",
        "gate_passed: true",
        "gate_passed: false",
        "researchRunList?.active",
        "researchRunList?.runs",
    ):
        assert needle in MAIN, needle


def test_frontend_unit_covers_research_run_client_routes() -> None:
    assert "wires research-run lifecycle to non-forgeable gate endpoints" in TEST
    assert "POST /api/research-runs/run-1/steps/contract/retry" in TEST
    assert "POST /api/research-runs/run-1/cancel" in TEST
