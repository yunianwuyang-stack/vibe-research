"""Independent, persisted adversarial review for evidence-native research projects."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db


MODES = {"deterministic", "model"}
SEVERITIES = {"critical", "major", "minor", "info"}
VERDICTS = {"pass", "block"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


def _finding(severity: str, code: str, message: str, *, locator: str = "") -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message, "locator": locator}


async def _snapshot(project_id: str) -> dict[str, Any]:
    from services import experiment_execution, hypothesis_lifecycle

    db = await get_db()
    try:
        await hypothesis_lifecycle._ensure_schema(db)
        project = await (await db.execute(
            "SELECT id,title,research_question,inclusion_criteria,status FROM research_projects WHERE id=?", (project_id,)
        )).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
        cards = await (await db.execute(
            "SELECT id,identity,title,doi,canonical_url,citation_status,claim_support_status FROM evidence_cards WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        narrative = await (await db.execute("SELECT * FROM narrative_maps WHERE project_id=?", (project_id,))).fetchone()
        graph = await (await db.execute("SELECT * FROM claim_evidence_graphs WHERE project_id=?", (project_id,))).fetchone()
        links = await (await db.execute(
            "SELECT claim_id,evidence_card_id,relation,status FROM claim_evidence_links WHERE project_id=? ORDER BY claim_id,id", (project_id,)
        )).fetchall()
        experiments = await (await db.execute(
            "SELECT * FROM experiment_runs WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        hypotheses = await (await db.execute(
            "SELECT * FROM hypothesis_versions WHERE project_id=? ORDER BY hypothesis_id,version",
            (project_id,),
        )).fetchall()
        draft_record = await (await db.execute(
            "SELECT * FROM approved_drafts WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (project_id,),
        )).fetchone()
        experiment_integrity = {
            row["id"]: await experiment_execution.inspect_run_integrity(db, row)
            for row in experiments
        }
    finally:
        await db.close()

    result: dict[str, Any] = {
        "project": dict(project),
        "evidence_cards": [dict(row) for row in cards],
        "claim_links": [dict(row) for row in links],
        "experiments": [],
        "hypotheses": [],
        "narrative": None,
        "claim_evidence_graph": None,
        "draft": None,
    }
    latest_versions: dict[str, int] = {}
    for row in hypotheses:
        latest_versions[row["hypothesis_id"]] = max(latest_versions.get(row["hypothesis_id"], 0), int(row["version"]))
    for row in hypotheses:
        value = dict(row)
        value["is_current"] = int(value["version"]) == latest_versions[value["hypothesis_id"]]
        integrity = hypothesis_lifecycle.manifest_integrity(value)
        value["manifest_document"] = integrity.pop("manifest")
        value["manifest"] = {
            "path": value["manifest_path"],
            "sha256": value["manifest_sha256"],
            "artifact_id": value["manifest_artifact_id"],
        }
        value["manifest_integrity"] = integrity
        result["hypotheses"].append(value)
    if narrative:
        value = dict(narrative)
        result["narrative"] = {
            "approved": bool(value["approved"]),
            "claims": json.loads(value["claims_json"]),
            "competing_explanations": json.loads(value["competing_json"]),
            "boundaries": json.loads(value["boundaries_json"]),
            "limitations": json.loads(value["limitations_json"]),
        }
    if graph:
        value = dict(graph)
        artifact = _workspace(project_id) / value["artifact_path"]
        file_hash = hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.is_file() else None
        result["claim_evidence_graph"] = {
            "artifact_path": value["artifact_path"],
            "sha256": value["sha256"],
            "file_sha256": file_hash,
            "gate": json.loads(value["gate_json"]),
        }
    for row in experiments:
        value = dict(row)
        value["statistics"] = json.loads(value.pop("statistics_json"))
        value["specification"] = json.loads(value.pop("specification_json"))
        value["result"] = json.loads(value.pop("result_json"))
        value["integrity"] = experiment_integrity[value["id"]]
        result["experiments"].append(value)
    draft = _workspace(project_id) / "paper" / "main.md"
    if draft.is_file():
        content = draft.read_text(encoding="utf-8")
        result["draft"] = {
            "path": "paper/main.md",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content[:24000],
            "truncated": len(content) > 24000,
            "record": dict(draft_record) if draft_record else None,
        }
        try:
            from services import approved_drafts

            draft_state = await approved_drafts.read(project_id)
            result["draft"]["hypothesis_validation"] = draft_state["hypothesis_validation"]
            result["draft"]["dependency_status"] = draft_state["status"]
            result["draft"]["stale_reason"] = draft_state["stale_reason"]
        except HTTPException as error:
            result["draft"]["hypothesis_validation"] = {"passed": False, "issues": [error.detail]}
            result["draft"]["dependency_status"] = "stale"
            result["draft"]["stale_reason"] = str(error.detail)
    from services.evidence_screening import read as read_screening
    screening = await read_screening(project_id)
    if screening["protocol"]:
        protocol = screening["protocol"]
        prisma = screening["prisma"] or {"flow": {}, "excluded_reasons": []}
        result["screening"] = {
            "protocol": {
                key: protocol[key]
                for key in ("status", "version", "protocol_sha256", "title", "inclusion_criteria", "exclusion_criteria", "source_strategy")
            },
            "decisions": [
                {key: decision[key] for key in ("evidence_card_id", "decision", "reason", "actor")}
                for decision in screening["decisions"]
            ],
            "flow": prisma["flow"],
            "excluded_reasons": prisma["excluded_reasons"],
        }
    from services import claim_evidence

    support = await claim_evidence._snapshot(project_id)
    result["claim_support"] = support["claims"]
    result["claim_experiment_links"] = support["experiment_links"]
    result["claim_support_gate"] = support["gate"]
    from services import innovation_check

    result["innovation_check"] = await innovation_check.snapshot_for_assurance(project_id)
    return result


async def _deterministic_findings(project_id: str, snapshot: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    cards = snapshot["evidence_cards"]
    if not cards:
        findings.append(_finding("critical", "no_evidence_cards", "No evidence cards are registered for this project."))

    hypotheses = snapshot.get("hypotheses", [])
    current_hypotheses = [item for item in hypotheses if item.get("is_current")]
    current_frozen = [item for item in current_hypotheses if item.get("status") == "frozen"]
    if not hypotheses:
        findings.append(_finding("critical", "missing_registered_hypothesis", "No versioned hypothesis manifest is registered for this project."))
    elif not current_frozen:
        findings.append(_finding("critical", "missing_frozen_hypothesis", "At least one current registered hypothesis must remain frozen."))
    for hypothesis in current_hypotheses:
        integrity = hypothesis.get("manifest_integrity", {})
        if not integrity.get("passed"):
            findings.append(_finding(
                "critical",
                "hypothesis_manifest_integrity_failed",
                "A current hypothesis manifest is missing, non-canonical, or does not match its ledger/content.",
                locator=hypothesis["id"],
            ))

    screening = snapshot.get("screening")
    if screening:
        protocol = screening["protocol"]
        flow = screening["flow"]
        if protocol["status"] != "active":
            findings.append(_finding("critical", "screening_protocol_inactive", "A saved screening protocol must be activated before its decisions can support the evidence record."))
        elif flow.get("records_not_yet_screened", 0):
            findings.append(_finding("critical", "screening_incomplete", "An active screening protocol has evidence cards without a current inclusion, exclusion, or uncertainty decision."))

    narrative = snapshot["narrative"]
    if not narrative:
        findings.append(_finding("critical", "missing_narrative_map", "A researcher-owned narrative map is required."))
    elif not narrative["approved"]:
        findings.append(_finding("critical", "narrative_not_approved", "The narrative map has not received human approval."))
    else:
        for key in ("competing_explanations", "boundaries", "limitations"):
            if not narrative[key]:
                findings.append(_finding("critical", f"missing_{key}", f"The narrative map has no {key}."))

    graph = snapshot["claim_evidence_graph"]
    if not graph:
        findings.append(_finding("critical", "missing_claim_evidence_graph", "No persisted Claim-Evidence graph exists."))
    else:
        if graph["file_sha256"] is None:
            findings.append(_finding("critical", "graph_artifact_missing", "The persisted Claim-Evidence graph artifact is missing.", locator=graph["artifact_path"]))
        elif graph["file_sha256"] != graph["sha256"]:
            findings.append(_finding("critical", "graph_artifact_hash_mismatch", "The Claim-Evidence graph artifact hash does not match the ledger.", locator=graph["artifact_path"]))
        if not graph["gate"].get("passed"):
            missing = ", ".join(graph["gate"].get("unsupported_claim_ids", [])) or "unknown"
            findings.append(_finding("critical", "unsupported_claims", f"Claim-Evidence gate is blocked; unsupported claims: {missing}."))

    for experiment in snapshot["experiments"]:
        if experiment["status"] == "completed" and not experiment["statistics"].get("passed"):
            findings.append(_finding("critical", "statistics_gate_failed", "A completed experiment did not pass its statistics gate.", locator=experiment["id"]))
        if experiment["status"] == "failed":
            findings.append(_finding("major", "failed_experiment", "A failed experiment remains in the research record and needs disposition.", locator=experiment["id"]))
        if experiment["status"] == "completed" and (not experiment["result_sha256"] or not experiment["manifest_sha256"]):
            findings.append(_finding("critical", "experiment_lineage_missing", "A completed experiment lacks a result or manifest hash.", locator=experiment["id"]))
        if experiment.get("dependency_status") == "stale":
            findings.append(_finding("critical", "stale_experiment_dependency", "An experiment depends on a hypothesis version that is no longer current and frozen.", locator=experiment["id"]))
        if experiment["status"] == "completed" and not experiment.get("integrity", {}).get("passed"):
            issues = ", ".join(experiment.get("integrity", {}).get("issues", [])) or "unknown"
            findings.append(_finding("critical", "experiment_manifest_integrity_failed", f"Experiment specification/manifest/result lineage failed integrity checks: {issues}.", locator=experiment["id"]))

    draft = snapshot["draft"]
    if draft:
        from services.scientific_narrative import audit_text
        from services.approved_drafts import body_for_scientific_audit

        audit = await audit_text(project_id, body_for_scientific_audit(draft["content"]))
        for issue in audit["issues"]:
            findings.append(_finding("critical", f"draft_{issue['code']}", "The persisted draft violates a deterministic scientific writing gate.", locator=str(issue.get("line", issue.get("locator", "")))))
        if draft.get("dependency_status") != "current":
            findings.append(_finding("critical", "stale_draft_hypothesis", "The persisted draft depends on a hypothesis registration that is no longer current and frozen.", locator=draft["path"]))
        if not draft.get("hypothesis_validation", {}).get("passed"):
            findings.append(_finding("critical", "draft_hypothesis_frontmatter_invalid", "Draft hypothesis frontmatter is missing, modified, or does not match the current frozen registry.", locator=draft["path"]))
    else:
        findings.append(_finding("critical", "draft_not_generated", "A persisted scientific draft is required before final submission assurance can pass."))

    support_nodes = snapshot.get("claim_support", [])
    approved_support_count = sum(
        len(item.get("supporting_link_ids", [])) + len(item.get("supporting_experiment_link_ids", []))
        for item in support_nodes
    )
    if not approved_support_count:
        findings.append(_finding("critical", "no_approved_support_links", "No approved eligible literature-passage or confirmatory-experiment support links exist."))

    innovation = snapshot.get("innovation_check") or {}
    if not innovation or innovation.get("status") in {None, "missing"}:
        findings.append(_finding("critical", "missing_innovation_check", "A persisted novelty/innovation check is required before final submission."))
    else:
        if innovation.get("file_sha256") is None:
            findings.append(_finding("critical", "innovation_report_missing", "The novelty report artifact is missing.", locator=str(innovation.get("artifact_path") or "")))
        elif innovation.get("file_sha256") != innovation.get("sha256"):
            findings.append(_finding("critical", "innovation_report_hash_mismatch", "The novelty report hash does not match the ledger.", locator=str(innovation.get("artifact_path") or "")))
        if not innovation.get("gate_passed"):
            low = ", ".join(innovation.get("low_novelty_claim_ids") or []) or "unknown"
            findings.append(_finding("critical", "innovation_gate_failed", f"Novelty/innovation gate is blocked; low-novelty claims without override: {low}."))
    return findings


def _reviewer_prompt(snapshot: dict[str, Any], deterministic_findings: list[dict[str, str]]) -> str:
    evidence = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    baseline = json.dumps(deterministic_findings, ensure_ascii=False, sort_keys=True)
    return (
        "You are an independent adversarial reviewer. Review only the supplied project snapshot. "
        "Do not invent sources, experiments, results, or page locators. Treat unresolved evidence, hash mismatches, "
        "unsupported claims, unapproved narrative maps, and failed statistical gates as reasons to block. "
        "Return JSON only with this schema: "
        '{"verdict":"pass|block","findings":[{"severity":"critical|major|minor|info","code":"snake_case","message":"specific falsifiable concern","locator":"optional"}]}. '
        "A pass requires no critical or major finding.\n\n"
        f"Deterministic baseline findings:\n{baseline}\n\nProject snapshot:\n{evidence}"
    )


def _parse_model_review(value: str) -> tuple[str, list[dict[str, str]]]:
    candidate = value.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError("Reviewer response is not valid JSON") from exc
    if not isinstance(parsed, dict) or parsed.get("verdict") not in VERDICTS or not isinstance(parsed.get("findings"), list):
        raise ValueError("Reviewer response does not match the required verdict/findings schema")
    findings: list[dict[str, str]] = []
    for item in parsed["findings"]:
        if not isinstance(item, dict):
            raise ValueError("Reviewer findings must be objects")
        severity = str(item.get("severity", "")).lower()
        code = str(item.get("code", "")).strip()
        message = str(item.get("message", "")).strip()
        locator = str(item.get("locator", "")).strip()
        if severity not in SEVERITIES or not re.fullmatch(r"[a-z][a-z0-9_]{1,80}", code) or not message:
            raise ValueError("Reviewer finding has an invalid severity, code, or message")
        findings.append(_finding(severity, code, message, locator=locator))
    blocking = any(item["severity"] in {"critical", "major"} for item in findings)
    if parsed["verdict"] == "pass" and blocking:
        raise ValueError("Reviewer marked a blocking finding as pass")
    return parsed["verdict"], findings


async def _read(review_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM adversarial_reviews WHERE id=?", (review_id,))).fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, detail="Adversarial review not found")
    result = dict(row)
    result["findings"] = json.loads(result.pop("findings_json"))
    return result


async def list_reviews(project_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        project = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
        rows = await (await db.execute("SELECT id FROM adversarial_reviews WHERE project_id=? ORDER BY created_at DESC,rowid DESC", (project_id,))).fetchall()
    finally:
        await db.close()
    return [await _read(row["id"]) for row in rows]


async def current_inputs_sha256(project_id: str) -> str:
    """Hash the current review surface so approvals cannot reuse stale reviews."""
    return _sha(await _snapshot(project_id))


async def _write_report(project_id: str, review_id: str, report: dict[str, Any]) -> tuple[str, str]:
    directory = _workspace(project_id) / "adversarial-reviews"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{review_id}.json"
    raw = _canonical(report)
    path.write_bytes(raw)
    return str(path.relative_to(_workspace(project_id)).as_posix()), hashlib.sha256(raw).hexdigest()


async def _complete(
    review_id: str,
    project_id: str,
    mode: str,
    inputs_sha256: str,
    verdict: str,
    findings: list[dict[str, str]],
    review_text: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    report = {
        "format_version": "1.0",
        "id": review_id,
        "project_id": project_id,
        "mode": mode,
        "reviewer_role": "reviewer" if mode == "model" else "deterministic_verifier",
        "status": "completed",
        "verdict": verdict,
        "inputs_sha256": inputs_sha256,
        "findings": findings,
        "review_text": review_text,
        "input_snapshot": snapshot,
    }
    report_path, report_sha256 = await _write_report(project_id, review_id, report)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE adversarial_reviews SET status='completed',verdict=?,findings_json=?,review_text=?,report_path=?,report_sha256=?,failure_reason=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (verdict, json.dumps(findings, ensure_ascii=False), review_text, report_path, report_sha256, review_id),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, project_id, "adversarial_review", report_sha256, f"adversarial-review:{review_id}", "verified"),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "adversarial_review_completed", "reviewer" if mode == "model" else "deterministic_verifier", json.dumps({"review_id": review_id, "mode": mode, "verdict": verdict, "report_sha256": report_sha256, "inputs_sha256": inputs_sha256}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await _read(review_id)


async def _fail(review_id: str, project_id: str, mode: str, inputs_sha256: str, snapshot: dict[str, Any], error: Exception) -> dict[str, Any]:
    reason = str(error)[:2000]
    report = {
        "format_version": "1.0",
        "id": review_id,
        "project_id": project_id,
        "mode": mode,
        "reviewer_role": "reviewer" if mode == "model" else "deterministic_verifier",
        "status": "failed",
        "verdict": "error",
        "inputs_sha256": inputs_sha256,
        "failure_reason": reason,
        "input_snapshot": snapshot,
    }
    report_path, report_sha256 = await _write_report(project_id, review_id, report)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE adversarial_reviews SET status='failed',verdict='error',report_path=?,report_sha256=?,failure_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (report_path, report_sha256, reason, review_id),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "adversarial_review_failed", "reviewer" if mode == "model" else "deterministic_verifier", json.dumps({"review_id": review_id, "mode": mode, "reason": reason, "report_sha256": report_sha256}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await _read(review_id)


async def run(project_id: str, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise HTTPException(422, detail="mode must be deterministic or model")
    snapshot = await _snapshot(project_id)
    review_id = uuid.uuid4().hex
    inputs_sha256 = _sha(snapshot)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO adversarial_reviews (id,project_id,mode,reviewer_role,status,verdict,inputs_sha256) VALUES (?,?,?,?,?,?,?)",
            (review_id, project_id, mode, "reviewer" if mode == "model" else "deterministic_verifier", "running", "pending", inputs_sha256),
        )
        await db.commit()
    finally:
        await db.close()
    try:
        deterministic = await _deterministic_findings(project_id, snapshot)
        if mode == "deterministic":
            verdict = "block" if any(item["severity"] in {"critical", "major"} for item in deterministic) else "pass"
            text = "Deterministic evidence, lineage, statistics, and draft audit completed."
            return await _complete(review_id, project_id, mode, inputs_sha256, verdict, deterministic, text, snapshot)
        from services.llm_client import call_llm

        review_text = await call_llm("reviewer", _reviewer_prompt(snapshot, deterministic), timeout=180)
        model_verdict, model_findings = _parse_model_review(review_text)
        findings = deterministic + model_findings
        verdict = "block" if model_verdict == "block" or any(item["severity"] in {"critical", "major"} for item in findings) else "pass"
        return await _complete(review_id, project_id, mode, inputs_sha256, verdict, findings, review_text, snapshot)
    except Exception as error:
        return await _fail(review_id, project_id, mode, inputs_sha256, snapshot, error)
