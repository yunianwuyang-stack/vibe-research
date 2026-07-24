CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES research_projects(id),
    template TEXT NOT NULL,          -- idea_discovery | experiment_bridge | auto_review | paper_writing | full_pipeline
    title TEXT NOT NULL,             -- 用户输入的研究方向
    params TEXT DEFAULT '{}',        -- JSON: AUTO_PROCEED, HUMAN_CHECKPOINT 等
    status TEXT DEFAULT 'pending',   -- pending | running | paused | completed | failed
    current_step TEXT,               -- 当前执行的 skill 名称
    workspace_dir TEXT,              -- 工作区目录路径
    enable_checkpoints INTEGER DEFAULT 0,  -- 0=关闭检查点(自动连续执行) 1=开启检查点(步骤完成后暂停确认)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    skill_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    step_order INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',   -- pending | running | waiting_checkpoint | completed | failed | skipped
    has_checkpoint INTEGER DEFAULT 0,
    checkpoint_type TEXT,            -- idea_select | approve | feedback
    output_files TEXT DEFAULT '[]',  -- JSON array
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS workflow_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    step_name TEXT,
    level TEXT DEFAULT 'info',       -- info | warn | error | progress
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    step_name TEXT NOT NULL,
    checkpoint_type TEXT NOT NULL,
    data TEXT DEFAULT '{}',          -- JSON: 展示给用户的数据
    response TEXT,                   -- JSON: 用户的回复
    status TEXT DEFAULT 'pending',   -- pending | resolved | feedback | timed_out
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

-- Durable workflow operations ledger.  The workflow engine writes an attempt
-- for every real node invocation; retries therefore remain distinguishable
-- from the original execution after a desktop restart.
CREATE TABLE IF NOT EXISTS workflow_step_attempts (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    skill_name TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    invocation TEXT NOT NULL DEFAULT 'workflow',
    status TEXT NOT NULL DEFAULT 'running',
    recovery_operation_id TEXT,
    output_files TEXT NOT NULL DEFAULT '[]',
    artifact_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(workflow_id, skill_name, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_workflow_step_attempts_run
ON workflow_step_attempts(workflow_id, skill_name, attempt_number);

CREATE TABLE IF NOT EXISTS workflow_artifact_lineage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    step_name TEXT NOT NULL,
    attempt_id TEXT NOT NULL REFERENCES workflow_step_attempts(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    predecessor_sha256 TEXT,
    size INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'current',
    recorded_at TEXT NOT NULL,
    UNIQUE(attempt_id, path)
);

CREATE INDEX IF NOT EXISTS idx_workflow_artifact_lineage_current
ON workflow_artifact_lineage(workflow_id, path, state, id);

CREATE TABLE IF NOT EXISTS workflow_recovery_operations (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    skill_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    resume_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflow_recovery_operations_run
ON workflow_recovery_operations(workflow_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workflow_operation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL REFERENCES workflows(id),
    project_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_operation_events_cursor
ON workflow_operation_events(id, project_id, workflow_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS research_projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    research_question TEXT NOT NULL,
    inclusion_criteria TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'needs_evidence',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS research_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hypothesis_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    hypothesis_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version > 0),
    parent_version_id TEXT REFERENCES hypothesis_versions(id),
    statement TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    prediction TEXT NOT NULL,
    falsification_criteria TEXT NOT NULL,
    boundary_conditions TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    manifest_artifact_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','frozen','falsified','superseded')),
    change_reason TEXT NOT NULL,
    state_reason TEXT,
    created_by TEXT NOT NULL,
    frozen_by TEXT,
    frozen_at TEXT,
    falsified_by TEXT,
    falsified_at TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, hypothesis_id, version)
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_versions_project
ON hypothesis_versions(project_id, hypothesis_id, version DESC);

CREATE TABLE IF NOT EXISTS hypothesis_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    hypothesis_id TEXT NOT NULL,
    version_id TEXT NOT NULL REFERENCES hypothesis_versions(id),
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_hypothesis_events_version
ON hypothesis_events(project_id, hypothesis_id, version_id, id);

CREATE TABLE IF NOT EXISTS research_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    provenance TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'needs_evidence',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evidence_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    identity TEXT NOT NULL,
    title TEXT NOT NULL,
    authors_json TEXT NOT NULL DEFAULT '[]',
    publication_year INTEGER,
    doi TEXT,
    canonical_url TEXT NOT NULL,
    citation_status TEXT NOT NULL DEFAULT 'needs_review',
    claim_support_status TEXT NOT NULL DEFAULT 'needs_review',
    decision_reason TEXT,
    citation_machine_verdict TEXT,
    citation_machine_layer TEXT,
    citation_machine_detail TEXT,
    citation_machine_checked_at TEXT,
    citation_machine_artifact_path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, identity)
);

CREATE TABLE IF NOT EXISTS evidence_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(id),
    provider TEXT NOT NULL,
    query TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_response_sha256 TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    UNIQUE(evidence_card_id, provider, source_url, raw_response_sha256)
);

CREATE TABLE IF NOT EXISTS screening_protocols (
    project_id TEXT PRIMARY KEY REFERENCES research_projects(id),
    title TEXT NOT NULL,
    inclusion_criteria TEXT NOT NULL,
    exclusion_criteria TEXT NOT NULL,
    source_strategy TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    protocol_sha256 TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    activated_by TEXT,
    activated_at TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS screening_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES research_projects(id),
    evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(id),
    protocol_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_screening_decisions_current ON screening_decisions(project_id, protocol_sha256, evidence_card_id, created_at);


CREATE TABLE IF NOT EXISTS research_runs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), status TEXT NOT NULL,
 current_step TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS research_run_steps (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES research_runs(id), name TEXT NOT NULL,
 status TEXT NOT NULL, input_json TEXT NOT NULL, output_json TEXT NOT NULL DEFAULT '{}', artifact_json TEXT NOT NULL DEFAULT '[]',
 provenance_json TEXT NOT NULL DEFAULT '[]', gate_json TEXT NOT NULL DEFAULT '{}', failure_reason TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(run_id,name)
);

CREATE TABLE IF NOT EXISTS experiment_runs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), status TEXT NOT NULL,
 specification_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', statistics_json TEXT NOT NULL DEFAULT '{}',
 analysis_mode TEXT NOT NULL DEFAULT 'exploratory' CHECK(analysis_mode IN ('exploratory','confirmatory')),
 specification_sha256 TEXT,
 hypothesis_version_id TEXT REFERENCES hypothesis_versions(id),
 hypothesis_manifest_sha256 TEXT,
 dependency_status TEXT NOT NULL DEFAULT 'current' CHECK(dependency_status IN ('current','stale')),
 stale_reason TEXT, stale_at TEXT,
 workspace_path TEXT NOT NULL, manifest_path TEXT, manifest_sha256 TEXT, result_sha256 TEXT,
 stdout_path TEXT, stderr_path TEXT, exit_code INTEGER, failure_reason TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_tasks (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), adapter TEXT NOT NULL,
 prompt TEXT NOT NULL, status TEXT NOT NULL, workspace_path TEXT NOT NULL, command_json TEXT NOT NULL DEFAULT '[]',
 events_json TEXT NOT NULL DEFAULT '[]', result_json TEXT NOT NULL DEFAULT '{}', audit_path TEXT,
 retry_of TEXT, failure_reason TEXT,
 lease_owner TEXT,
 lease_expires_at TEXT,
 heartbeat_at TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_task_leases (
 task_id TEXT PRIMARY KEY REFERENCES agent_tasks(id),
 owner TEXT NOT NULL,
 acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 heartbeat_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 expires_at TEXT NOT NULL,
 released_at TEXT
);

CREATE TABLE IF NOT EXISTS narrative_maps (
 project_id TEXT PRIMARY KEY REFERENCES research_projects(id), question TEXT NOT NULL, tension TEXT NOT NULL,
 mechanism TEXT NOT NULL, hypotheses_json TEXT NOT NULL DEFAULT '[]', claims_json TEXT NOT NULL DEFAULT '[]',
 competing_json TEXT NOT NULL DEFAULT '[]', boundaries_json TEXT NOT NULL DEFAULT '[]', limitations_json TEXT NOT NULL DEFAULT '[]',
 approved INTEGER NOT NULL DEFAULT 0, approved_by TEXT, approved_at TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS approved_drafts (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES research_projects(id),
 artifact_id TEXT NOT NULL,
 path TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 evidence_version_sha256 TEXT NOT NULL,
 claim_evidence_graph_sha256 TEXT NOT NULL,
 hypothesis_manifest_set_sha256 TEXT NOT NULL,
 hypothesis_bindings_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'current' CHECK(status IN ('current','stale','superseded')),
 stale_reason TEXT,
 stale_at TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_approved_drafts_project
ON approved_drafts(project_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS claim_evidence_links (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES research_projects(id),
 claim_id TEXT NOT NULL,
 evidence_card_id TEXT NOT NULL REFERENCES evidence_cards(id),
 relation TEXT NOT NULL,
 passage TEXT NOT NULL,
 locator TEXT,
 status TEXT NOT NULL DEFAULT 'needs_review',
 reviewed_by TEXT,
 review_reason TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(project_id, claim_id, evidence_card_id, relation, passage, locator)
);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_links_project ON claim_evidence_links(project_id, claim_id, status);

CREATE TABLE IF NOT EXISTS claim_experiment_links (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES research_projects(id),
 claim_id TEXT NOT NULL,
 experiment_run_id TEXT NOT NULL REFERENCES experiment_runs(id),
 relation TEXT NOT NULL,
 result_locator TEXT NOT NULL,
 interpretation TEXT NOT NULL,
 evidence_card_ids_json TEXT NOT NULL DEFAULT '[]',
 result_sha256 TEXT NOT NULL,
 manifest_sha256 TEXT NOT NULL,
 hypothesis_version_id TEXT NOT NULL,
 hypothesis_manifest_sha256 TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'needs_review',
 reviewed_by TEXT,
 review_reason TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(project_id, claim_id, experiment_run_id, relation, result_locator)
);

CREATE INDEX IF NOT EXISTS idx_claim_experiment_links_project ON claim_experiment_links(project_id, claim_id, status);

CREATE TABLE IF NOT EXISTS claim_evidence_graphs (
 project_id TEXT PRIMARY KEY REFERENCES research_projects(id),
 artifact_path TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 sources_version_sha256 TEXT NOT NULL,
 gate_json TEXT NOT NULL DEFAULT '{}',
 generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adversarial_reviews (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES research_projects(id),
 mode TEXT NOT NULL,
 reviewer_role TEXT NOT NULL,
 status TEXT NOT NULL,
 verdict TEXT NOT NULL,
 inputs_sha256 TEXT NOT NULL,
 findings_json TEXT NOT NULL DEFAULT '[]',
 review_text TEXT NOT NULL DEFAULT '',
 report_path TEXT,
 report_sha256 TEXT,
 failure_reason TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_adversarial_reviews_project ON adversarial_reviews(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS innovation_checks (
 id TEXT PRIMARY KEY,
 project_id TEXT NOT NULL REFERENCES research_projects(id),
 status TEXT NOT NULL,
 gate_passed INTEGER NOT NULL DEFAULT 0,
 claims_json TEXT NOT NULL,
 findings_json TEXT NOT NULL,
 closest_prior_art_json TEXT NOT NULL,
 report_path TEXT NOT NULL,
 report_sha256 TEXT NOT NULL,
 sources_version_sha256 TEXT NOT NULL,
 overrides_json TEXT NOT NULL DEFAULT '{}',
 created_by TEXT NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_innovation_checks_project
ON innovation_checks(project_id, created_at DESC);
