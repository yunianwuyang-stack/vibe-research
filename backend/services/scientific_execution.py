"""Product-facing execution paths for mathematical and qualitative P6 profiles."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from domain.experiments.scientific import admit_qualitative_corpus, adjudicate_math_claim
from services.state_store import get_db


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


async def _project_exists(project_id: str) -> None:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not row:
            raise HTTPException(404, detail="Research project not found")
    finally:
        await db.close()


async def execute_math(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    await _project_exists(project_id)
    verifier = str(payload.get("verifier") or "llm").casefold()
    artifact = str(payload.get("artifact") or "")
    artifact_hash = _sha(artifact.encode()) if artifact else None
    result = adjudicate_math_claim(
        claim=str(payload.get("claim") or ""), verifier=verifier,
        artifact_hash=artifact_hash, replayable=bool(payload.get("replayable")),
        counterexample=payload.get("counterexample"),
    )
    run_id = uuid.uuid4().hex
    workspace = WORKSPACES_DIR / project_id / "experiments" / run_id
    workspace.mkdir(parents=True, exist_ok=False)
    receipt = workspace / "math-receipt.json"
    receipt.write_bytes(_canonical(result))
    return {"id": run_id, "profile": "theoretical_mathematical", **result,
            "receipt_path": str(receipt), "receipt_sha256": _sha(receipt.read_bytes())}


async def admit_qualitative(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    await _project_exists(project_id)
    result = admit_qualitative_corpus(
        source_uri=str(payload.get("source_uri") or ""),
        source_sha256=str(payload.get("source_sha256") or ""),
        rights=payload.get("rights") or {},
        coding_scheme_version=str(payload.get("coding_scheme_version") or ""),
        negative_cases=payload.get("negative_cases") or [],
        reflexivity_note=str(payload.get("reflexivity_note") or ""),
        generated_participants=bool(payload.get("generated_participants")),
    )
    run_id = uuid.uuid4().hex
    workspace = WORKSPACES_DIR / project_id / "experiments" / run_id
    workspace.mkdir(parents=True, exist_ok=False)
    receipt = workspace / "qualitative-receipt.json"
    receipt.write_bytes(_canonical(result))
    return {"id": run_id, "profile": "qualitative_humanities", **result,
            "receipt_path": str(receipt), "receipt_sha256": _sha(receipt.read_bytes())}
