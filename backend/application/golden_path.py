"""Persistent research orchestration; no step self-verifies."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any

@dataclass(frozen=True)
class WorkflowStep:
 name:str; input_schema:str; output_schema:str; capabilities:tuple[str,...]; gates:tuple[str,...]; stale_dependencies:tuple[str,...]
_NAMES=("contract","question","hypothesis","evidence","experiment_run","result","claim","adversarial_review","approval","audit")
_GATES={
 "adversarial_review":("current_evidence_statistics_and_draft_review",),
 "approval":("current_adversarial_review","human_approval","verified_artifact"),
}
GOLDEN_PATH=tuple(WorkflowStep(n,"research.v1","research.v1",("production",),_GATES.get(n,("human_or_evidence_gate",)),() if i==0 else (_NAMES[i-1],)) for i,n in enumerate(_NAMES))
LEGACY_TEMPLATE_ADAPTER={f"legacy_{i}":"read-only" for i in range(34)}
def capability_graph() -> dict[str,Any]:
 return {"schema_version":"1.0","nodes":[asdict(step) for step in GOLDEN_PATH],"edges":[{"from":_NAMES[i-1],"to":name,"type":"requires"} for i,name in enumerate(_NAMES) if i]}


class GoldenPath:
    """Compatibility fa?ade exposing the declarative graph without execution claims."""
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
    def run(self, contract: str) -> dict[str, str]:
        if not contract.strip(): raise ValueError("research contract required")
        self.events.append({"action":"start_requested","audit":True})
        return {"contract":contract, **{step.name:f"{step.name}:needs_execution" for step in GOLDEN_PATH}}
