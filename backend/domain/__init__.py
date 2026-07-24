"""Pure research domain model; deliberately independent of delivery frameworks."""

from .entities import (
    Approval,
    Artifact,
    Audit,
    Claim,
    ClaimStatus,
    Decision,
    EvidenceItem,
    EvidenceRelation,
    Experiment,
    ExperimentRun,
    Hypothesis,
    HypothesisStatus,
    Project,
    ResearchQuestion,
    Result,
    Source,
    SourcePassage,
)
from .serialization import entity_from_dict, entity_to_dict
from .research_run import (
    SCHEMA_VERSION as RESEARCH_RUN_SCHEMA_VERSION,
    ArtifactRef,
    AttemptStatus,
    Gate,
    GateStatus,
    ResearchRun,
    RunEvent,
    RunStatus,
    Task,
    TaskAttempt,
    TaskStatus,
    finish_current_task,
    new_run,
    retry_task,
    run_to_dict,
    run_from_dict,
    start_current_task,
    transition_run,
)

__all__ = [
    "Approval", "Artifact", "Audit", "Claim", "ClaimStatus", "Decision", "EvidenceItem",
    "EvidenceRelation", "Experiment", "ExperimentRun", "Hypothesis", "HypothesisStatus",
    "Project", "ResearchQuestion", "Result", "Source", "SourcePassage", "entity_from_dict",
    "entity_to_dict",
    "RESEARCH_RUN_SCHEMA_VERSION", "ArtifactRef", "AttemptStatus", "Gate", "GateStatus",
    "ResearchRun", "RunEvent", "RunStatus", "Task", "TaskAttempt", "TaskStatus",
    "finish_current_task", "new_run", "retry_task", "run_to_dict", "run_from_dict", "start_current_task",
    "transition_run",
]
