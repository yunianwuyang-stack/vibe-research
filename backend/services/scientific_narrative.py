"""Persistent researcher-owned argument maps and deterministic narrative gates."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from domain.assurance.numeric_registry import NumericValue
from domain.assurance.paper_numbers import PaperNumericVerifier
from domain.narrative.lint import NarrativeLint
from services.state_store import get_db


async def save_map(project_id: str, values: dict[str, Any]) -> dict[str, Any]:
    required = ("question", "tension", "mechanism")
    if not all(str(values.get(name, "")).strip() for name in required):
        raise HTTPException(422, detail="question, literature tension and mechanism are required")
    collections = ("hypotheses", "claims", "competing_explanations", "boundaries", "limitations")
    if any(not values.get(name) for name in collections):
        raise HTTPException(422, detail="hypotheses, claims, competing explanations, boundaries and limitations are required")
    claims = [str(value).strip() for value in values["claims"]]
    if any(not claim for claim in claims) or len(set(claims)) != len(claims):
        raise HTTPException(422, detail="claim identifiers must be non-empty and unique")
    values = {**values, "claims": claims}
    db = await get_db()
    try:
        project = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project: raise HTTPException(404, detail="Research project not found")
        await db.execute("INSERT INTO narrative_maps (project_id,question,tension,mechanism,hypotheses_json,claims_json,competing_json,boundaries_json,limitations_json,approved,approved_by,approved_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,NULL,NULL,CURRENT_TIMESTAMP) ON CONFLICT(project_id) DO UPDATE SET question=excluded.question,tension=excluded.tension,mechanism=excluded.mechanism,hypotheses_json=excluded.hypotheses_json,claims_json=excluded.claims_json,competing_json=excluded.competing_json,boundaries_json=excluded.boundaries_json,limitations_json=excluded.limitations_json,approved=0,approved_by=NULL,approved_at=NULL,updated_at=CURRENT_TIMESTAMP", (project_id, values["question"], values["tension"], values["mechanism"], json.dumps(values["hypotheses"]), json.dumps(values["claims"]), json.dumps(values["competing_explanations"]), json.dumps(values["boundaries"]), json.dumps(values["limitations"])))
        await db.commit()
    finally: await db.close()
    # Saving the map creates a reviewable graph artifact even before evidence is linked.
    from services.claim_evidence import publish_graph
    await publish_graph(project_id)
    return await read_map(project_id)


async def read_map(project_id: str) -> dict[str, Any]:
    db = await get_db()
    try: row = await (await db.execute("SELECT * FROM narrative_maps WHERE project_id=?", (project_id,))).fetchone()
    finally: await db.close()
    if not row: raise HTTPException(404, detail="Narrative map has not been created")
    value = dict(row)
    for source, target in (("hypotheses_json","hypotheses"),("claims_json","claims"),("competing_json","competing_explanations"),("boundaries_json","boundaries"),("limitations_json","limitations")): value[target] = json.loads(value.pop(source))
    value["approved"] = bool(value["approved"])
    return value


async def approve_map(project_id: str, actor: str) -> dict[str, Any]:
    if not actor.strip(): raise HTTPException(422, detail="Human actor is required")
    await read_map(project_id); now = datetime.now(timezone.utc).isoformat(); db = await get_db()
    try:
        await db.execute("UPDATE narrative_maps SET approved=1,approved_by=?,approved_at=?,updated_at=CURRENT_TIMESTAMP WHERE project_id=?", (actor, now, project_id))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"narrative_map_approved",actor,json.dumps({"approved_at":now}))); await db.commit()
    finally: await db.close()
    return await read_map(project_id)


async def numeric_registry(project_id: str) -> list[NumericValue]:
    """Manuscript-facing numbers share draft-save eligibility (confirmatory + intact)."""
    from services.approved_drafts import _eligible_numeric_registry

    db = await get_db()
    try:
        return await _eligible_numeric_registry(db, project_id)
    finally:
        await db.close()


async def audit_text(project_id: str, text: str, *, causal_identified: bool = False) -> dict[str, Any]:
    lint = NarrativeLint().check(text, causal_identified=causal_identified)
    numbers = PaperNumericVerifier().verify(text, await numeric_registry(project_id))
    issues = [{"code": item.code, "line": item.line} for item in lint]
    issues += [{"code":"unverified_number","locator":item.locator,"value":item.value} for item in numbers if not item.verified]
    return {"passed":not issues,"issues":issues,"numbers":[item.__dict__ for item in numbers]}
