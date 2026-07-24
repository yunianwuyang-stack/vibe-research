"""Persisted evidence-screening protocols, decision ledgers, and PRISMA artifacts."""
from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db


DECISIONS = {"included", "excluded", "uncertain"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    try:
        workspace.relative_to(WORKSPACES_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(422, detail="Invalid research project workspace") from exc
    return workspace


def _protocol_value(row: Any) -> dict[str, Any]:
    value = dict(row)
    value["active"] = value["status"] == "active"
    return value


async def _project_exists(project_id: str) -> None:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
    finally:
        await db.close()
    if not row:
        raise HTTPException(404, detail="Research project not found")


async def _protocol(project_id: str) -> dict[str, Any] | None:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM screening_protocols WHERE project_id=?", (project_id,))).fetchone()
    finally:
        await db.close()
    return _protocol_value(row) if row else None


async def _current_decisions(project_id: str, protocol_sha256: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        rows = await (await db.execute(
            "SELECT decision.*,card.title,card.canonical_url FROM screening_decisions decision "
            "JOIN evidence_cards card ON card.id=decision.evidence_card_id "
            "WHERE decision.project_id=? AND decision.protocol_sha256=? "
            "ORDER BY decision.created_at DESC,decision.rowid DESC",
            (project_id, protocol_sha256),
        )).fetchall()
    finally:
        await db.close()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = dict(row)
        latest.setdefault(value["evidence_card_id"], value)
    return sorted(latest.values(), key=lambda value: (value["title"].casefold(), value["evidence_card_id"]))


async def _prisma(project_id: str, protocol: dict[str, Any]) -> dict[str, Any]:
    decisions = await _current_decisions(project_id, protocol["protocol_sha256"])
    db = await get_db()
    try:
        total = int((await (await db.execute("SELECT count(*) FROM evidence_cards WHERE project_id=?", (project_id,))).fetchone())[0])
    finally:
        await db.close()
    counts = Counter(item["decision"] for item in decisions)
    reasons = Counter(item["reason"] for item in decisions if item["decision"] == "excluded")
    return {
        "format_version": "1.0",
        "project_id": project_id,
        "protocol_sha256": protocol["protocol_sha256"],
        "protocol_version": protocol["version"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "flow": {
            "records_identified": total,
            "duplicate_records_removed": 0,
            "records_screened": len(decisions),
            "records_not_yet_screened": max(0, total - len(decisions)),
            "reports_sought_for_retrieval": counts["included"],
            "studies_included": counts["included"],
            "records_excluded": counts["excluded"],
            "records_uncertain": counts["uncertain"],
        },
        "excluded_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0].casefold()))
        ],
        "decisions": decisions,
        "scope_note": "Counts cover persisted evidence cards only; provider search results not saved as cards are not silently included.",
    }


async def _write_artifact(project_id: str, relative_path: str, value: dict[str, Any]) -> tuple[str, str]:
    workspace = _workspace(project_id)
    target = (workspace / relative_path).resolve()
    try:
        target.relative_to(workspace)
    except ValueError as exc:
        raise HTTPException(422, detail="Artifact path escaped project workspace") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value)
    target.write_bytes(raw)
    return target.relative_to(workspace).as_posix(), hashlib.sha256(raw).hexdigest()


async def read(project_id: str) -> dict[str, Any]:
    await _project_exists(project_id)
    protocol = await _protocol(project_id)
    if not protocol:
        return {"protocol": None, "decisions": [], "prisma": None, "artifact": None}
    decisions = await _current_decisions(project_id, protocol["protocol_sha256"])
    return {"protocol": protocol, "decisions": decisions, "prisma": await _prisma(project_id, protocol), "artifact": None}


async def save_protocol(
    project_id: str,
    title: str,
    inclusion_criteria: str,
    exclusion_criteria: str,
    source_strategy: str,
    actor: str,
) -> dict[str, Any]:
    fields = (title, inclusion_criteria, exclusion_criteria, source_strategy, actor)
    if any(not value.strip() for value in fields):
        raise HTTPException(422, detail="title, inclusion criteria, exclusion criteria, source strategy and actor are required")
    await _project_exists(project_id)
    previous = await _protocol(project_id)
    version = (int(previous["version"]) + 1) if previous else 1
    prepared = {
        "format_version": "1.0",
        "project_id": project_id,
        "version": version,
        "title": title.strip(),
        "inclusion_criteria": inclusion_criteria.strip(),
        "exclusion_criteria": exclusion_criteria.strip(),
        "source_strategy": source_strategy.strip(),
        "status": "draft",
        "author": actor.strip(),
    }
    protocol_sha256 = _sha(prepared)
    artifact_path, artifact_sha256 = await _write_artifact(project_id, f"evidence/screening-protocol-v{version}.json", prepared)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO screening_protocols (project_id,title,inclusion_criteria,exclusion_criteria,source_strategy,status,version,protocol_sha256,artifact_path,activated_by,activated_at,updated_at) "
            "VALUES (?,?,?,?,?,'draft',?,?,?,NULL,NULL,CURRENT_TIMESTAMP) "
            "ON CONFLICT(project_id) DO UPDATE SET title=excluded.title,inclusion_criteria=excluded.inclusion_criteria,exclusion_criteria=excluded.exclusion_criteria,source_strategy=excluded.source_strategy,status='draft',version=excluded.version,protocol_sha256=excluded.protocol_sha256,artifact_path=excluded.artifact_path,activated_by=NULL,activated_at=NULL,updated_at=CURRENT_TIMESTAMP",
            (project_id, prepared["title"], prepared["inclusion_criteria"], prepared["exclusion_criteria"], prepared["source_strategy"], version, protocol_sha256, artifact_path),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, project_id, "screening_protocol", artifact_sha256, f"screening-protocol:{protocol_sha256}", "needs_review"),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "screening_protocol_saved", actor.strip(), json.dumps({"version": version, "protocol_sha256": protocol_sha256, "artifact_sha256": artifact_sha256}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await read(project_id)


async def activate(project_id: str, actor: str) -> dict[str, Any]:
    if not actor.strip():
        raise HTTPException(422, detail="Human actor is required")
    protocol = await _protocol(project_id)
    if not protocol:
        raise HTTPException(409, detail="Save a screening protocol before activation")
    activation = {
        "format_version": "1.0",
        "project_id": project_id,
        "version": protocol["version"],
        "protocol_sha256": protocol["protocol_sha256"],
        "status": "active",
        "activated_by": actor.strip(),
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path, artifact_sha256 = await _write_artifact(project_id, f"evidence/screening-protocol-v{protocol['version']}-active.json", activation)
    db = await get_db()
    try:
        await db.execute(
            "UPDATE screening_protocols SET status='active',artifact_path=?,activated_by=?,activated_at=?,updated_at=CURRENT_TIMESTAMP WHERE project_id=?",
            (artifact_path, actor.strip(), activation["activated_at"], project_id),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, project_id, "screening_protocol_activation", artifact_sha256, f"screening-protocol:{protocol['protocol_sha256']}", "verified"),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "screening_protocol_activated", actor.strip(), json.dumps({"protocol_sha256": protocol["protocol_sha256"], "artifact_sha256": artifact_sha256}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await read(project_id)


async def decide(project_id: str, evidence_card_id: str, decision: str, reason: str, actor: str) -> dict[str, Any]:
    if decision not in DECISIONS or not reason.strip() or not actor.strip():
        raise HTTPException(422, detail="decision must be included, excluded, or uncertain; reason and actor are required")
    protocol = await _protocol(project_id)
    if not protocol or protocol["status"] != "active":
        raise HTTPException(409, detail="An active, hash-addressed screening protocol is required before a screening decision")
    db = await get_db()
    try:
        card = await (await db.execute("SELECT id FROM evidence_cards WHERE id=? AND project_id=?", (evidence_card_id, project_id))).fetchone()
        if not card:
            raise HTTPException(404, detail="Evidence card not found")
        decision_id = uuid.uuid4().hex
        await db.execute(
            "INSERT INTO screening_decisions (id,project_id,evidence_card_id,protocol_sha256,decision,reason,actor) VALUES (?,?,?,?,?,?,?)",
            (decision_id, project_id, evidence_card_id, protocol["protocol_sha256"], decision, reason.strip(), actor.strip()),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "screening_decision_recorded", actor.strip(), json.dumps({"decision_id": decision_id, "evidence_card_id": evidence_card_id, "decision": decision, "reason": reason.strip(), "protocol_sha256": protocol["protocol_sha256"]}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    return await export_prisma(project_id)


async def export_prisma(project_id: str) -> dict[str, Any]:
    protocol = await _protocol(project_id)
    if not protocol or protocol["status"] != "active":
        raise HTTPException(409, detail="Activate a screening protocol before exporting a PRISMA artifact")
    value = await _prisma(project_id, protocol)
    path, digest = await _write_artifact(project_id, f"evidence/prisma-v{protocol['version']}-{uuid.uuid4().hex}.json", value)
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, project_id, "prisma_screening", digest, f"screening-protocol:{protocol['protocol_sha256']}", "verified"),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "prisma_artifact_exported", "system", json.dumps({"protocol_sha256": protocol["protocol_sha256"], "artifact_path": path, "sha256": digest}, ensure_ascii=False)),
        )
        await db.commit()
    finally:
        await db.close()
    state = await read(project_id)
    state["artifact"] = {"path": path, "sha256": digest}
    return state
