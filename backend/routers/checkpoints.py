"""Durable checkpoint API for workflow step confirmation."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from models.schemas import CheckpointResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/workflows/{wf_id}/checkpoints", tags=["checkpoints"])


@router.get("/current")
async def get_current_checkpoint(wf_id: str):
    """Return the durable pending checkpoint, or synthesize one from step state."""
    from services.state_store import _get_db

    db = await _get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM checkpoints WHERE workflow_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (wf_id,),
        )
        row = await cursor.fetchone()
        if row:
            d = dict(row)
            raw = d.get("data") or "{}"
            try:
                d["data"] = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except json.JSONDecodeError:
                d["data"] = {"raw": raw}
            return d

        # Compatibility for runs that entered waiting_checkpoint before durable
        # checkpoint rows were written.
        cursor = await db.execute(
            "SELECT skill_name, checkpoint_type, display_name, output_files "
            "FROM workflow_steps WHERE workflow_id = ? AND status = 'waiting_checkpoint' "
            "ORDER BY step_order ASC LIMIT 1",
            (wf_id,),
        )
        step = await cursor.fetchone()
        if not step:
            return None
        return {
            "id": None,
            "workflow_id": wf_id,
            "step_name": step["skill_name"],
            "checkpoint_type": step["checkpoint_type"] or "approve",
            "data": {
                "type": "checkpoint_hit",
                "step": step["skill_name"],
                "checkpoint_type": step["checkpoint_type"] or "approve",
                "display_name": step["display_name"],
                "output_files": json.loads(step["output_files"] or "[]"),
            },
            "response": None,
            "status": "pending",
            "created_at": None,
            "resolved_at": None,
        }
    finally:
        await db.close()


@router.post("/resolve")
async def resolve(wf_id: str, body: CheckpointResponse):
    """Resolve an in-memory waiter and mark any durable pending row resolved."""
    from services.state_store import _get_db
    from services.workflow_engine import submit_checkpoint

    payload = {"action": body.action, "data": body.data}
    submit_checkpoint(wf_id, payload)
    db = await _get_db()
    try:
        await db.execute(
            "UPDATE checkpoints SET status = 'resolved', response = ?, resolved_at = CURRENT_TIMESTAMP "
            "WHERE workflow_id = ? AND status = 'pending'",
            (json.dumps(payload, ensure_ascii=False), wf_id),
        )
        await db.commit()
    finally:
        await db.close()
    return {"ok": True}
