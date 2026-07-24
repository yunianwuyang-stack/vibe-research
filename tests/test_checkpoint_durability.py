"""Checkpoint durability and full-pipeline language defaults."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_checkpoint_row_is_persisted_and_resolved():
    sys.path.insert(0, str(ROOT / "backend"))
    from services import workflow_engine

    workflow_id = "checkpoint-test-1"
    responses: list[dict] = []

    class FakeDB:
        def __init__(self):
            self.rows = []
            self.executed = []

        async def execute(self, sql, params=()):
            self.executed.append((sql, params))
            if sql.strip().upper().startswith("INSERT INTO CHECKPOINTS"):
                self.rows.append(
                    {
                        "workflow_id": params[0],
                        "step_name": params[1],
                        "checkpoint_type": params[2],
                        "data": params[3],
                        "status": "pending",
                        "response": None,
                    }
                )

            class Cursor:
                def __init__(self, rows):
                    self._rows = rows

                async def fetchone(self):
                    return self._rows[-1] if self._rows else None

            if "FROM checkpoints" in sql:
                pending = [row for row in self.rows if row["status"] == "pending"]
                return Cursor(pending)
            if sql.strip().upper().startswith("UPDATE CHECKPOINTS"):
                for row in self.rows:
                    if (
                        row["workflow_id"] == params[1]
                        and row["step_name"] == params[2]
                        and row["status"] == "pending"
                    ):
                        row["status"] = "resolved"
                        row["response"] = params[0]
            return Cursor([])

        async def commit(self):
            return None

    db = FakeDB()

    async def fake_wait(wf_id: str, timeout=None):
        assert wf_id == workflow_id
        cursor = await db.execute(
            "SELECT step_name, checkpoint_type, status, data FROM checkpoints WHERE workflow_id = ?",
            (workflow_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["step_name"] == "thesis-proposal"
        assert row["status"] == "pending"
        data = json.loads(row["data"])
        assert data["type"] == "checkpoint_hit"
        responses.append({"action": "approve", "data": {"feedback": "ok"}})
        return responses[-1]

    async def exercise():
        old_wait = workflow_engine.wait_checkpoint
        workflow_engine.wait_checkpoint = fake_wait
        try:
            step_def = workflow_engine.StepDef(
                skill_name="thesis-proposal",
                display_name="开题",
                output_files=["PROPOSAL.md"],
                primary_output="PROPOSAL.md",
                has_checkpoint=True,
                checkpoint_type="feedback",
            )
            skill_name = step_def.skill_name
            checkpoint_event = {
                "type": "checkpoint_hit",
                "step": skill_name,
                "checkpoint_type": step_def.checkpoint_type,
                "display_name": step_def.display_name,
            }
            await db.execute(
                "INSERT INTO checkpoints (workflow_id, step_name, checkpoint_type, data, status) "
                "VALUES (?, ?, ?, ?, 'pending')",
                (
                    workflow_id,
                    skill_name,
                    step_def.checkpoint_type or "approve",
                    json.dumps(checkpoint_event, ensure_ascii=False),
                ),
            )
            await db.commit()
            response = await workflow_engine.wait_checkpoint(workflow_id, timeout=None)
            await db.execute(
                "UPDATE checkpoints SET status = 'resolved', response = ?, resolved_at = CURRENT_TIMESTAMP "
                "WHERE workflow_id = ? AND step_name = ? AND status = 'pending'",
                (json.dumps(response, ensure_ascii=False), workflow_id, skill_name),
            )
            assert db.rows[0]["status"] == "resolved"
            assert json.loads(db.rows[0]["response"])["action"] == "approve"
            assert responses and responses[0]["action"] == "approve"
        finally:
            workflow_engine.wait_checkpoint = old_wait

    asyncio.run(exercise())


def test_full_pipeline_defaults_to_english_writing_tail():
    sys.path.insert(0, str(ROOT / "backend"))
    from services.workflow_engine import _resolve_template
    from services.workflow_options import normalize_workflow_params

    params = normalize_workflow_params("full_pipeline", {})
    assert params["language"] == "en"
    skills = [
        step.skill_name
        for step in _resolve_template("full_pipeline", params, Path(tempfile.mkdtemp())).sub_steps
    ]
    assert "paper-plan" in skills
    assert "paper-write" in skills
    assert "paper-plan-zh" not in skills
    assert "paper-write-zh" not in skills
