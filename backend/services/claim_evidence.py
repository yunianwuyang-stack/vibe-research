"""Persistent, reviewable links between narrative claims and evidence cards."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db


RELATIONS = {"supports", "contradicts", "context"}
REVIEW_STATUSES = {"approved", "rejected"}
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


def _resolve_result_locator(result: Any, locator: str) -> Any:
    """Resolve a conservative dotted path into an immutable experiment result."""
    locator = locator.strip()
    if not locator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", locator):
        raise ValueError("result_locator must be a dotted result-object path")
    current = result
    for segment in locator.split("."):
        if not isinstance(current, dict) or segment not in current:
            raise ValueError(f"result_locator does not exist: {locator}")
        current = current[segment]
    if current is None or isinstance(current, (dict, list)):
        raise ValueError("result_locator must identify a scalar result")
    return current


def _normalize_card_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise HTTPException(422, detail="evidence_card_ids must be a non-empty list")
    normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
    if not normalized:
        raise HTTPException(422, detail="At least one evidence_card_id is required")
    return normalized


async def _validate_experiment_support(
    db: Any,
    project_id: str,
    experiment_run_id: str,
    evidence_card_ids: list[str],
    result_locator: str,
) -> tuple[Any, Any]:
    from services import experiment_execution

    await experiment_execution._ensure_schema(db)
    run = await (await db.execute(
        "SELECT * "
        "FROM experiment_runs WHERE id=? AND project_id=?",
        (experiment_run_id, project_id),
    )).fetchone()
    if not run:
        raise HTTPException(404, detail="Experiment run not found")
    if run["status"] != "completed":
        raise HTTPException(409, detail="Only completed experiment runs can support a claim")
    if run["analysis_mode"] != "confirmatory":
        raise HTTPException(409, detail="Only a confirmatory experiment bound to a frozen hypothesis can support a claim")
    integrity = await experiment_execution.inspect_run_integrity(db, run)
    try:
        specification = json.loads(run["specification_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        specification = {}
    protocol_binding = specification.get("p5_protocol_binding") if isinstance(specification, dict) else None
    protocol_issues = [
        issue for issue in integrity["issues"]
        if str(issue).startswith("p5_protocol_")
    ]
    if not isinstance(protocol_binding, dict) or not protocol_binding or protocol_issues:
        raise HTTPException(
            409,
            detail={
                "message": "Confirmatory experiment requires a valid P5 protocol binding with clean protocol lineage",
                "p5_protocol_binding_present": isinstance(protocol_binding, dict) and bool(protocol_binding),
                "p5_protocol_issues": protocol_issues,
            },
        )
    hypothesis = integrity["hypothesis"]
    if run["dependency_status"] != "current":
        raise HTTPException(409, detail="The experiment is stale because its registered hypothesis changed")
    if not (
        hypothesis["bound"]
        and hypothesis["current"]
        and hypothesis["frozen"]
        and hypothesis["manifest_integrity_passed"]
        and hypothesis["binding_matches"]
    ):
        raise HTTPException(409, detail="The experiment hypothesis binding is no longer current, frozen, and intact")
    if not integrity["passed"]:
        raise HTTPException(409, detail={"message": "Experiment lineage integrity failed", "issues": integrity["issues"]})
    statistics = json.loads(run["statistics_json"])
    if not statistics.get("passed"):
        raise HTTPException(409, detail="Experiment statistics gate must pass before linking the result to a claim")
    for field in ("result_sha256", "manifest_sha256"):
        digest = str(run[field] or "").lower()
        if not SHA256_PATTERN.fullmatch(digest):
            raise HTTPException(409, detail=f"Experiment {field} lineage is missing or invalid")
    placeholders = ",".join("?" for _ in evidence_card_ids)
    cards = await (await db.execute(
        f"SELECT id,citation_status,claim_support_status FROM evidence_cards WHERE project_id=? AND id IN ({placeholders})",
        (project_id, *evidence_card_ids),
    )).fetchall()
    cards_by_id = {card["id"]: card for card in cards}
    if any(card_id not in cards_by_id for card_id in evidence_card_ids):
        raise HTTPException(404, detail="One or more evidence basis cards were not found in this project")
    if any(
        cards_by_id[card_id]["citation_status"] != "approved"
        or cards_by_id[card_id]["claim_support_status"] != "approved"
        for card_id in evidence_card_ids
    ):
        raise HTTPException(409, detail="Every experiment evidence basis must have approved citation existence and claim support")
    try:
        result_value = _resolve_result_locator(json.loads(run["result_json"]), result_locator)
    except (json.JSONDecodeError, ValueError) as error:
        raise HTTPException(422, detail=str(error)) from error
    return run, result_value


async def _snapshot(project_id: str) -> dict[str, Any]:
    from services import experiment_execution

    db = await get_db()
    try:
        await experiment_execution._ensure_schema(db)
        project = await (await db.execute("SELECT id,title FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
        narrative = await (await db.execute("SELECT claims_json FROM narrative_maps WHERE project_id=?", (project_id,))).fetchone()
        claims = json.loads(narrative["claims_json"]) if narrative else []
        cards = await (await db.execute(
            "SELECT id,title,canonical_url,citation_status,claim_support_status FROM evidence_cards WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        links = await (await db.execute(
            "SELECT id,claim_id,evidence_card_id,relation,passage,locator,status,reviewed_by,review_reason,created_at,updated_at "
            "FROM claim_evidence_links WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        experiments = await (await db.execute(
            "SELECT * "
            "FROM experiment_runs WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        experiment_links = await (await db.execute(
            "SELECT id,claim_id,experiment_run_id,relation,result_locator,interpretation,evidence_card_ids_json,"
            "result_sha256,manifest_sha256,hypothesis_version_id,hypothesis_manifest_sha256,status,reviewed_by,review_reason,created_at,updated_at "
            "FROM claim_experiment_links WHERE project_id=? ORDER BY created_at,id",
            (project_id,),
        )).fetchall()
        run_integrity = {
            row["id"]: await experiment_execution.inspect_run_integrity(db, row)
            for row in experiments
        }
    finally:
        await db.close()

    card_rows = [dict(row) for row in cards]
    link_rows = [dict(row) for row in links]
    cards_by_id = {card["id"]: card for card in card_rows}
    experiment_rows: list[dict[str, Any]] = []
    for row in experiments:
        value = dict(row)
        value["result"] = json.loads(value.pop("result_json"))
        value["statistics"] = json.loads(value.pop("statistics_json"))
        value["integrity"] = run_integrity[value["id"]]
        experiment_rows.append(value)
    experiments_by_id = {experiment["id"]: experiment for experiment in experiment_rows}
    experiment_link_rows: list[dict[str, Any]] = []
    for row in experiment_links:
        value = dict(row)
        value["evidence_card_ids"] = json.loads(value.pop("evidence_card_ids_json"))
        experiment = experiments_by_id.get(value["experiment_run_id"])
        bases_valid = bool(value["evidence_card_ids"]) and all(
            cards_by_id.get(card_id, {}).get("citation_status") == "approved"
            and cards_by_id.get(card_id, {}).get("claim_support_status") == "approved"
            for card_id in value["evidence_card_ids"]
        )
        lineage_valid = bool(experiment) and (
            experiment.get("result_sha256") == value["result_sha256"]
            and experiment.get("manifest_sha256") == value["manifest_sha256"]
            and experiment.get("hypothesis_version_id") == value["hypothesis_version_id"]
            and experiment.get("hypothesis_manifest_sha256") == value["hypothesis_manifest_sha256"]
        )
        locator_valid = False
        result_value: Any = None
        if experiment:
            try:
                result_value = _resolve_result_locator(experiment["result"], value["result_locator"])
                locator_valid = True
            except ValueError:
                pass
        value["result_value"] = result_value
        hypothesis_integrity = experiment.get("integrity", {}).get("hypothesis", {}) if experiment else {}
        value["eligibility"] = {
            "experiment_completed": bool(experiment) and experiment.get("status") == "completed",
            "analysis_mode_confirmatory": bool(experiment) and experiment.get("analysis_mode") == "confirmatory",
            "dependency_current": bool(experiment) and experiment.get("dependency_status") == "current",
            "statistics_passed": bool(experiment) and bool(experiment.get("statistics", {}).get("passed")),
            "lineage_valid": lineage_valid,
            "experiment_manifest_valid": bool(experiment) and bool(experiment.get("integrity", {}).get("passed")),
            "hypothesis_current": bool(hypothesis_integrity.get("current")),
            "hypothesis_frozen": bool(hypothesis_integrity.get("frozen")),
            "hypothesis_manifest_valid": bool(hypothesis_integrity.get("manifest_integrity_passed")),
            "hypothesis_binding_valid": bool(hypothesis_integrity.get("binding_matches")),
            "evidence_basis_valid": bases_valid,
            "result_locator_valid": locator_valid,
            "review_approved": value["status"] == "approved",
        }
        value["eligible"] = all(value["eligibility"].values())
        experiment_link_rows.append(value)
    claim_nodes: list[dict[str, Any]] = []
    for claim_id in claims:
        approved_evidence_supports = [
            link["id"]
            for link in link_rows
            if link["claim_id"] == claim_id
            and link["relation"] == "supports"
            and link["status"] == "approved"
            and cards_by_id.get(link["evidence_card_id"], {}).get("citation_status") == "approved"
            and cards_by_id.get(link["evidence_card_id"], {}).get("claim_support_status") == "approved"
        ]
        approved_experiment_supports = [
            link["id"]
            for link in experiment_link_rows
            if link["claim_id"] == claim_id
            and link["relation"] == "supports"
            and link["status"] == "approved"
            and link["eligible"]
        ]
        supported = bool(approved_evidence_supports or approved_experiment_supports)
        claim_nodes.append(
            {
                "id": claim_id,
                "supporting_link_ids": approved_evidence_supports,
                "supporting_experiment_link_ids": approved_experiment_supports,
                "status": "supported" if supported else "needs_evidence",
            }
        )
    gate = {
        "passed": bool(claim_nodes) and all(node["status"] == "supported" for node in claim_nodes),
        "total_claims": len(claim_nodes),
        "supported_claims": sum(node["status"] == "supported" for node in claim_nodes),
        "approved_evidence_support_count": sum(len(node["supporting_link_ids"]) for node in claim_nodes),
        "approved_experiment_support_count": sum(len(node["supporting_experiment_link_ids"]) for node in claim_nodes),
        "unsupported_claim_ids": [node["id"] for node in claim_nodes if node["status"] != "supported"],
        "rule": "Every narrative claim requires approved support from either a reviewed evidence passage or a current confirmatory experiment bound to an intact current frozen hypothesis, with valid statistics, locator, evidence basis, and immutable lineage.",
    }
    return {
        "format_version": "claim-evidence-graph/v2",
        "project": {"id": project["id"], "title": project["title"]},
        "claims": claim_nodes,
        "evidence_cards": card_rows,
        "links": link_rows,
        "experiments": experiment_rows,
        "experiment_links": experiment_link_rows,
        "gate": gate,
    }


async def publish_graph(project_id: str) -> dict[str, Any]:
    """Write a byte-addressable graph artifact when source state changes."""
    snapshot = await _snapshot(project_id)
    sources_version = _sha(snapshot)
    db = await get_db()
    try:
        current = await (await db.execute("SELECT artifact_path,sha256,sources_version_sha256 FROM claim_evidence_graphs WHERE project_id=?", (project_id,))).fetchone()
    finally:
        await db.close()
    if current and current["sources_version_sha256"] == sources_version:
        path = _workspace(project_id) / current["artifact_path"]
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == current["sha256"]:
            result = json.loads(path.read_text(encoding="utf-8"))
            result["artifact"] = {"path": current["artifact_path"], "sha256": current["sha256"]}
            return result

    relative_path = "evidence/claim-evidence-graph.json"
    path = _workspace(project_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        **snapshot,
        "sources_version_sha256": sources_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    content = _canonical(document)
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    artifact_status = "verified" if document["gate"]["passed"] else "needs_review"
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO claim_evidence_graphs (project_id,artifact_path,sha256,sources_version_sha256,gate_json,generated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(project_id) DO UPDATE SET artifact_path=excluded.artifact_path,sha256=excluded.sha256,sources_version_sha256=excluded.sources_version_sha256,gate_json=excluded.gate_json,generated_at=excluded.generated_at",
            (project_id, relative_path, digest, sources_version, json.dumps(document["gate"], ensure_ascii=False), document["generated_at"]),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, project_id, "claim_evidence_graph", digest, f"claim-evidence:{sources_version}", artifact_status),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "claim_evidence_graph_published", "system", json.dumps({"path": relative_path, "sha256": digest, "sources_version_sha256": sources_version, "gate": document["gate"]}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    document["artifact"] = {"path": relative_path, "sha256": digest}
    return document


async def read_graph(project_id: str) -> dict[str, Any]:
    """Return the current graph, regenerating it if a citation or link changed."""
    snapshot = await _snapshot(project_id)
    sources_version = _sha(snapshot)
    db = await get_db()
    try:
        current = await (await db.execute("SELECT artifact_path,sha256,sources_version_sha256 FROM claim_evidence_graphs WHERE project_id=?", (project_id,))).fetchone()
    finally:
        await db.close()
    if not current or current["sources_version_sha256"] != sources_version:
        return await publish_graph(project_id)
    path = _workspace(project_id) / current["artifact_path"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != current["sha256"]:
        return await publish_graph(project_id)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["artifact"] = {"path": current["artifact_path"], "sha256": current["sha256"]}
    return document


async def create_link(project_id: str, values: dict[str, str]) -> dict[str, Any]:
    claim_id = values["claim_id"].strip()
    evidence_card_id = values["evidence_card_id"].strip()
    relation = values["relation"].strip()
    passage = values["passage"].strip()
    locator = values.get("locator", "").strip() or None
    if relation not in RELATIONS:
        raise HTTPException(422, detail="relation must be supports, contradicts, or context")
    if not all((claim_id, evidence_card_id, passage)):
        raise HTTPException(422, detail="claim_id, evidence_card_id, and passage are required")
    db = await get_db()
    try:
        narrative = await (await db.execute("SELECT claims_json FROM narrative_maps WHERE project_id=?", (project_id,))).fetchone()
        if not narrative:
            raise HTTPException(409, detail="Save the narrative map before linking evidence")
        if claim_id not in json.loads(narrative["claims_json"]):
            raise HTTPException(422, detail="claim_id must match a claim in the saved narrative map")
        card = await (await db.execute("SELECT citation_status FROM evidence_cards WHERE id=? AND project_id=?", (evidence_card_id, project_id))).fetchone()
        if not card:
            raise HTTPException(404, detail="Evidence card not found")
        if card["citation_status"] != "approved":
            raise HTTPException(409, detail="Approve citation existence before linking it to a claim")
        link_id = uuid.uuid4().hex
        try:
            await db.execute(
                "INSERT INTO claim_evidence_links (id,project_id,claim_id,evidence_card_id,relation,passage,locator) VALUES (?,?,?,?,?,?,?)",
                (link_id, project_id, claim_id, evidence_card_id, relation, passage, locator),
            )
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise HTTPException(409, detail="This evidence passage is already linked to the claim") from error
            raise
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "claim_evidence_link_created", "researcher", json.dumps({"link_id": link_id, "claim_id": claim_id, "evidence_card_id": evidence_card_id, "relation": relation}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await publish_graph(project_id)


async def review_link(project_id: str, link_id: str, actor: str, decision: str, reason: str) -> dict[str, Any]:
    if decision not in REVIEW_STATUSES or not actor.strip() or not reason.strip():
        raise HTTPException(422, detail="actor, reason and approved/rejected decision are required")
    db = await get_db()
    try:
        link = await (await db.execute(
            "SELECT link.id,card.citation_status FROM claim_evidence_links link JOIN evidence_cards card ON card.id=link.evidence_card_id "
            "WHERE link.id=? AND link.project_id=?",
            (link_id, project_id),
        )).fetchone()
        if not link:
            raise HTTPException(404, detail="Claim-Evidence link not found")
        if decision == "approved" and link["citation_status"] != "approved":
            raise HTTPException(409, detail="Citation existence must remain approved before a Claim-Evidence link can be approved")
        await db.execute(
            "UPDATE claim_evidence_links SET status=?,reviewed_by=?,review_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (decision, actor.strip(), reason.strip(), link_id),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "claim_evidence_link_reviewed", actor.strip(), json.dumps({"link_id": link_id, "status": decision, "reason": reason.strip()}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await publish_graph(project_id)


async def create_experiment_link(project_id: str, values: dict[str, Any]) -> dict[str, Any]:
    claim_id = str(values.get("claim_id") or "").strip()
    experiment_run_id = str(values.get("experiment_run_id") or "").strip()
    relation = str(values.get("relation") or "").strip()
    result_locator = str(values.get("result_locator") or "").strip()
    interpretation = str(values.get("interpretation") or "").strip()
    evidence_card_ids = _normalize_card_ids(values.get("evidence_card_ids"))
    if relation not in RELATIONS:
        raise HTTPException(422, detail="relation must be supports, contradicts, or context")
    if not all((claim_id, experiment_run_id, result_locator, interpretation)):
        raise HTTPException(422, detail="claim_id, experiment_run_id, result_locator, and interpretation are required")
    db = await get_db()
    try:
        narrative = await (await db.execute(
            "SELECT claims_json FROM narrative_maps WHERE project_id=?", (project_id,)
        )).fetchone()
        if not narrative:
            raise HTTPException(409, detail="Save the narrative map before linking an experiment")
        if claim_id not in json.loads(narrative["claims_json"]):
            raise HTTPException(422, detail="claim_id must match a claim in the saved narrative map")
        run, result_value = await _validate_experiment_support(
            db, project_id, experiment_run_id, evidence_card_ids, result_locator
        )
        link_id = uuid.uuid4().hex
        try:
            await db.execute(
                "INSERT INTO claim_experiment_links "
                "(id,project_id,claim_id,experiment_run_id,relation,result_locator,interpretation,evidence_card_ids_json,result_sha256,manifest_sha256,hypothesis_version_id,hypothesis_manifest_sha256) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    link_id, project_id, claim_id, experiment_run_id, relation, result_locator,
                    interpretation, json.dumps(evidence_card_ids, ensure_ascii=False),
                    run["result_sha256"], run["manifest_sha256"],
                    run["hypothesis_version_id"], run["hypothesis_manifest_sha256"],
                ),
            )
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise HTTPException(409, detail="This experiment result is already linked to the claim") from error
            raise
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "claim_experiment_link_created",
                "researcher",
                json.dumps(
                    {
                        "link_id": link_id,
                        "claim_id": claim_id,
                        "experiment_run_id": experiment_run_id,
                        "evidence_card_ids": evidence_card_ids,
                        "result_locator": result_locator,
                        "result_value": result_value,
                        "result_sha256": run["result_sha256"],
                        "manifest_sha256": run["manifest_sha256"],
                        "hypothesis_version_id": run["hypothesis_version_id"],
                        "hypothesis_manifest_sha256": run["hypothesis_manifest_sha256"],
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return await publish_graph(project_id)


async def review_experiment_link(
    project_id: str,
    link_id: str,
    actor: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    if decision not in REVIEW_STATUSES or not actor.strip() or not reason.strip():
        raise HTTPException(422, detail="actor, reason and approved/rejected decision are required")
    db = await get_db()
    try:
        link = await (await db.execute(
            "SELECT * FROM claim_experiment_links WHERE id=? AND project_id=?",
            (link_id, project_id),
        )).fetchone()
        if not link:
            raise HTTPException(404, detail="Claim-Experiment link not found")
        if decision == "approved":
            evidence_card_ids = _normalize_card_ids(json.loads(link["evidence_card_ids_json"]))
            run, _ = await _validate_experiment_support(
                db,
                project_id,
                link["experiment_run_id"],
                evidence_card_ids,
                link["result_locator"],
            )
            if run["result_sha256"] != link["result_sha256"] or run["manifest_sha256"] != link["manifest_sha256"]:
                raise HTTPException(409, detail="Experiment result or manifest lineage changed after the link was created")
            if (
                run["hypothesis_version_id"] != link["hypothesis_version_id"]
                or run["hypothesis_manifest_sha256"] != link["hypothesis_manifest_sha256"]
            ):
                raise HTTPException(409, detail="Experiment hypothesis lineage changed after the link was created")
        await db.execute(
            "UPDATE claim_experiment_links SET status=?,reviewed_by=?,review_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (decision, actor.strip(), reason.strip(), link_id),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "claim_experiment_link_reviewed",
                actor.strip(),
                json.dumps({"link_id": link_id, "status": decision, "reason": reason.strip()}, ensure_ascii=False),
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return await publish_graph(project_id)
