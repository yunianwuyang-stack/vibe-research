"""P5 typed research design and fail-closed gates."""
from __future__ import annotations
import hashlib, json, uuid
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from services.state_store import get_db

PROFILE_REQUIRED = {
    "systematic_review_meta": ("search_strategy", "screening_rule", "synthesis_plan", "falsification_criteria"),
    "observational_causal": ("estimand", "dag", "identification_strategy", "falsification_criteria"),
    "experimental_ml": ("baseline", "ablation_plan", "evaluation_metric", "falsification_criteria"),
    "theoretical_mathematical": ("claim", "proof_obligation", "counterexample_plan", "falsification_criteria"),
    "qualitative_humanities": ("corpus_scope", "coding_scheme", "negative_case_plan", "falsification_criteria"),
}
PROFILE_ALIASES = {"theory": "theoretical_mathematical", "qualitative": "qualitative_humanities"}
VALID_CONTRIBUTIONS = ("theoretical", "empirical", "methodological", "data", "replication")

def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _sha(value: Any) -> str:
    return hashlib.sha256(_dump(value).encode()).hexdigest()

def _required(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text: raise HTTPException(422, detail=f"{name} is required")
    return text

async def _schema(db: Any) -> None:
    await db.executescript("""
    CREATE TABLE IF NOT EXISTS research_designs (project_id TEXT PRIMARY KEY REFERENCES research_projects(id), contribution_json TEXT NOT NULL, profile_type TEXT NOT NULL, profile_json TEXT NOT NULL, design_sha256 TEXT NOT NULL, created_by TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS prior_art_matrices (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), freeze_date TEXT NOT NULL, query_json TEXT NOT NULL, entries_json TEXT NOT NULL, corpus_sha256 TEXT NOT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS research_protocols (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), version INTEGER NOT NULL, analysis_mode TEXT NOT NULL, protocol_json TEXT NOT NULL, protocol_sha256 TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS ethics_data_rights (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES research_projects(id), assessment_json TEXT NOT NULL, assessment_sha256 TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)

async def _exists(db: Any, project_id: str) -> None:
    if not await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone(): raise HTTPException(404, detail="Research project not found")

def _profile(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    kind = PROFILE_ALIASES.get(kind, kind)
    if kind not in PROFILE_REQUIRED: raise HTTPException(422, detail={"message": "Unsupported study profile", "allowed": sorted(PROFILE_REQUIRED)})
    missing = [key for key in PROFILE_REQUIRED[kind] if not str(value.get(key) or "").strip()]
    if missing: raise HTTPException(422, detail={"message": "Study profile is incomplete", "missing": missing})
    value = dict(value); value["profile_type"] = kind
    return value

async def save_design(project_id: str, contribution: dict[str, Any], profile_type: str, profile: dict[str, Any], actor: str) -> dict[str, Any]:
    contribution = {key: bool(contribution.get(key)) for key in ("theoretical", "empirical", "methodological", "data", "replication")} | {"falsifier": _required(contribution.get("falsifier"), "falsifier")}
    if not any(contribution[key] for key in ("theoretical", "empirical", "methodological", "data", "replication")): raise HTTPException(422, detail="At least one contribution kind is required")
    actor = _required(actor, "actor"); profile = _profile(profile_type, profile); profile_type = profile["profile_type"]; digest = _sha({"contribution": contribution, "profile_type": profile_type, "profile": profile}); db = await get_db()
    try:
        await _schema(db); await _exists(db, project_id); await db.execute("INSERT INTO research_designs VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(project_id) DO UPDATE SET contribution_json=excluded.contribution_json,profile_type=excluded.profile_type,profile_json=excluded.profile_json,design_sha256=excluded.design_sha256,created_by=excluded.created_by,updated_at=CURRENT_TIMESTAMP", (project_id, _dump(contribution), profile_type, _dump(profile), digest, actor)); await db.execute("INSERT INTO research_events(project_id,event_type,actor,payload) VALUES(?,?,?,?)", (project_id, "p5_design_saved", actor, _dump({"sha256": digest, "profile_type": profile_type}))); await db.commit()
    finally: await db.close()
    return await read(project_id)

async def freeze_prior_art(project_id: str, freeze_date: str, query: dict[str, Any], entries: list[dict[str, Any]], actor: str) -> dict[str, Any]:
    try: datetime.fromisoformat(freeze_date.replace("Z", "+00:00"))
    except ValueError as exc: raise HTTPException(422, detail="freeze_date must be ISO-8601") from exc
    if not entries: raise HTTPException(409, detail="closest-prior-art corpus is empty")
    normalized = [{"id": _required(item.get("id") or f"prior-{i}", "prior_art.id"), "title": _required(item.get("title"), "prior_art.title"), "source_url": _required(item.get("source_url"), "prior_art.source_url"), "similarities": _required(item.get("similarities"), "prior_art.similarities"), "differences": _required(item.get("differences"), "prior_art.differences"), "evidence_strength": _required(item.get("evidence_strength"), "prior_art.evidence_strength"), "unresolved_conflicts": str(item.get("unresolved_conflicts") or "").strip()} for i, item in enumerate(entries, 1)]
    hosts = []
    for item in normalized:
        parts = str(item["source_url"]).split("/", 3)
        if len(parts) < 3 or not parts[2].strip():
            raise HTTPException(422, detail="prior_art.source_url must include a host")
        hosts.append(parts[2].casefold())
    source_count = len(set(hosts))
    if len(normalized) < 2 or source_count < 2: raise HTTPException(409, detail="closest-prior-art requires at least two entries from two independent sources")
    if any(item["unresolved_conflicts"] for item in normalized): raise HTTPException(409, detail="closest-prior-art has unresolved conflicts")
    actor = _required(actor, "actor"); digest = _sha({"freeze_date": freeze_date, "query": query, "entries": normalized}); db = await get_db()
    try:
        await _schema(db); await _exists(db, project_id); await db.execute("INSERT INTO prior_art_matrices VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", (uuid.uuid4().hex, project_id, freeze_date, _dump(query), _dump(normalized), digest, actor)); await db.execute("INSERT INTO research_events(project_id,event_type,actor,payload) VALUES(?,?,?,?)", (project_id, "p5_prior_art_frozen", actor, _dump({"freeze_date": freeze_date, "sha256": digest, "entries": len(normalized)}))); await db.commit()
    finally: await db.close()
    return await read(project_id)

async def save_protocol(project_id: str, protocol: dict[str, Any], analysis_mode: str, actor: str) -> dict[str, Any]:
    if analysis_mode not in {"exploratory", "confirmatory"}: raise HTTPException(422, detail="analysis_mode must be exploratory or confirmatory")
    missing = [key for key in ("estimand", "outcome", "exposure", "baseline", "ablation_plan", "falsification_criteria") if not str(protocol.get(key) or "").strip()]
    if missing: raise HTTPException(422, detail={"message": "Protocol is incomplete", "missing": missing})
    actor = _required(actor, "actor"); db = await get_db()
    try:
        await _schema(db); await _exists(db, project_id); row = await (await db.execute("SELECT COALESCE(MAX(version),0) AS version FROM research_protocols WHERE project_id=?", (project_id,))).fetchone(); version = int(row["version"]) + 1; digest = _sha({"version": version, "analysis_mode": analysis_mode, "protocol": protocol}); status = "frozen" if analysis_mode == "confirmatory" else "draft"; await db.execute("INSERT INTO research_protocols VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", (uuid.uuid4().hex, project_id, version, analysis_mode, _dump(protocol), digest, status, actor)); await db.execute("INSERT INTO research_events(project_id,event_type,actor,payload) VALUES(?,?,?,?)", (project_id, "p5_protocol_saved", actor, _dump({"version": version, "analysis_mode": analysis_mode, "status": status, "sha256": digest}))); await db.commit()
    finally: await db.close()
    return await read(project_id)

async def assess_ethics(project_id: str, assessment: dict[str, Any], actor: str) -> dict[str, Any]:
    fields = ("subjects", "jurisdiction", "irb_status", "consent_status", "dua_status", "license_status", "pii_categories", "allowed_use", "retention_deletion"); missing = [key for key in fields if assessment.get(key) in (None, "")]
    if missing: raise HTTPException(422, detail={"message": "Ethics/data-rights assessment is incomplete", "missing": missing})
    blocked = [key for key in ("irb_status", "consent_status", "dua_status", "license_status") if str(assessment[key]).casefold() in {"missing", "unknown", "not_verified", "pending", "required"}]; status = "blocked" if blocked else "verified"; actor = _required(actor, "actor"); digest = _sha(assessment); db = await get_db()
    try:
        await _schema(db); await _exists(db, project_id); await db.execute("INSERT INTO ethics_data_rights VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)", (uuid.uuid4().hex, project_id, _dump(assessment), digest, status, actor)); await db.execute("INSERT INTO research_events(project_id,event_type,actor,payload) VALUES(?,?,?,?)", (project_id, "p5_ethics_assessed", actor, _dump({"status": status, "blocked_fields": blocked, "sha256": digest}))); await db.commit()
    finally: await db.close()
    return await read(project_id)

async def read(project_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        await _schema(db); await _exists(db, project_id); result = {"project_id": project_id}
        for name, table, order in (("design", "research_designs", "updated_at DESC, rowid DESC"), ("prior_art", "prior_art_matrices", "rowid DESC"), ("protocol", "research_protocols", "version DESC, rowid DESC"), ("ethics_data_rights", "ethics_data_rights", "rowid DESC")):
            row = await (await db.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY {order} LIMIT 1", (project_id,))).fetchone(); result[name] = None if not row else dict(row)
            if result[name]:
                for key in list(result[name]):
                    if key.endswith("_json"): result[name][key.removesuffix("_json")] = json.loads(result[name].pop(key))
        return result
    finally: await db.close()

async def gate(project_id: str) -> dict[str, Any]:
    state = await read(project_id); findings = []
    if not state["design"]: findings.append("missing_research_design")
    if not state["prior_art"] or not state["prior_art"].get("entries"): findings.append("missing_or_empty_frozen_closest_prior_art")
    if not state["protocol"]: findings.append("missing_protocol")
    elif state["protocol"]["analysis_mode"] == "confirmatory" and state["protocol"]["status"] != "frozen": findings.append("confirmatory_protocol_not_frozen")
    if not state["ethics_data_rights"] or state["ethics_data_rights"]["status"] != "verified": findings.append("ethics_or_data_rights_not_verified")
    return {"project_id": project_id, "passed": not findings, "status": "ready" if not findings else "blocked", "findings": findings}


async def execution_data_rights_gate(project_id: str, requested_purpose: str = "") -> dict[str, Any]:
    """Return a conservative, non-sensitive decision for data mounting."""
    state = await read(project_id)
    assessment = state.get("ethics_data_rights")
    reasons: list[str] = []
    if not assessment or assessment.get("status") != "verified":
        reasons.append("consent_unverified")
        return {"passed": False, "reason_codes": reasons}
    value = assessment.get("assessment", {})
    if requested_purpose and requested_purpose not in str(value.get("allowed_use", "")):
        reasons.append("license_unverified")
    if not str(value.get("jurisdiction", "")).strip():
        reasons.append("missing_jurisdiction")
    retention = str(value.get("retention_deletion", "")).strip()
    if not retention:
        reasons.append("retention_invalid")
    pii = value.get("pii_categories")
    if pii not in ([], "none", "None", None) and not value.get("consent_status"):
        reasons.append("pii_not_approved")
    return {"passed": not reasons, "reason_codes": list(dict.fromkeys(reasons))}
