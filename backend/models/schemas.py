"""Pydantic models and enums for workflow data."""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CHECKPOINT = "waiting_checkpoint"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TemplateType(str, Enum):
    IDEA_DISCOVERY = "idea_discovery"
    EXPERIMENT_BRIDGE = "experiment_bridge"
    AUTO_REVIEW = "auto_review"
    PAPER_WRITING = "paper_writing"
    PAPER_WRITING_ZH = "paper_writing_zh"
    NATURE_WRITING = "nature_writing"
    FULL_PIPELINE = "full_pipeline"
    COMP_CUMCM = "comp_cumcm"
    COMP_MCM = "comp_mcm"
    COMP_HUAWEI = "comp_huawei"
    COMP_MATHORCUP = "comp_mathorcup"
    COMP_APMCM = "comp_apmcm"
    COMP_APMCM_ZH = "comp_apmcm_zh"
    COMP_STATS = "comp_stats"
    COMP_TEDDY = "comp_teddy"
    COMP_CERTCUP = "comp_certcup"
    COMP_HUAZHONG = "comp_huazhong"
    COMP_HUADONG = "comp_huadong"
    COMP_WUYI = "comp_wuyi"
    COMP_SHUWEI = "comp_shuwei"
    COMP_ZHONGQING = "comp_zhongqing"
    COMP_YANGTZE = "comp_yangtze"
    COMP_DIANGONG = "comp_diangong"
    COMP_LIAONING = "comp_liaoning"
    COMP_SHENZHEN = "comp_shenzhen"
    COMP_HUASHU = "comp_huashu"
    COMP_TIANFU = "comp_tianfu"
    COMP_CERTCUP_EN = "comp_certcup_en"
    COMP_SHUWEI_EN = "comp_shuwei_en"
    THESIS_PROPOSAL = "thesis_proposal"
    LITERATURE_REVIEW = "literature_review"
    COURSE_PAPER = "course_paper"
    COURSE_REPORT = "course_report"
    PAPER_FROM_ASSETS = "paper_from_assets"
    PAPER_SLIDES = "paper_slides"
    PAPER_POSTER = "paper_poster"
    ONE_SENTENCE_PROJECT = "one_sentence_project"
    DEV = "dev"  # legacy one-sentence project card id → aliases to grad_project
    SOFTWARE_COPYRIGHT = "software_copyright"
    COPYRIGHT_MATERIAL = "copyright_material"
    PATENT_DISCLOSURE = "patent_disclosure"
    GRAD_PROJECT = "grad_project"
    HUMANITIES_PAPER = "humanities_paper"


class WorkflowCreate(BaseModel):
    template: TemplateType
    title: str = Field(..., min_length=1)
    params: Dict = Field(default_factory=dict)
    enable_checkpoints: bool = False
    project_id: Optional[str] = None


class StepInfo(BaseModel):
    skill_name: str
    display_name: str
    step_order: int
    status: StepStatus = StepStatus.PENDING
    has_checkpoint: bool = False
    checkpoint_type: Optional[str] = None
    output_files: List[str] = Field(default_factory=list)
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None


class WorkflowInfo(BaseModel):
    id: str
    project_id: Optional[str] = None
    template: TemplateType
    title: str
    params: Dict = Field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step: Optional[str] = None
    steps: List[StepInfo] = Field(default_factory=list)
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None


class CheckpointData(BaseModel):
    checkpoint_type: str
    step_name: str
    data: Dict = Field(default_factory=dict)


class CheckpointResponse(BaseModel):
    action: str
    data: Dict = Field(default_factory=dict)


class LogEntry(BaseModel):
    step_name: Optional[str] = None
    level: str = "info"
    message: str
    created_at: Optional[datetime.datetime] = None
