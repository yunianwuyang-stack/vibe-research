"""Versioned, auditable hypothesis lifecycle for a research project."""
from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db


EDITABLE_FIELDS = (
    "statement",
    "mechanism",
    "prediction",
    "falsification_criteria",
    "boundary_conditions",
)
TERMINAL_STATUSES = {"falsified", "superseded"}
MANIFEST_FORMAT = "vibe-research/hypothesis-manifest/v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


def _manifest_document(
    *,
    project_id: str,
    hypothesis_id: str,
    version_id: str,
    version: int,
    parent_version_id: str | None,
    content: dict[str, str],
    created_by: str,
    change_reason: str,
    created_at: str,
) -> dict[str, Any]:
    """Return the immutable, content-addressed contract for one version.

    Lifecycle state deliberately lives in the append-only event ledger.  Freeze,
    unfreeze, and falsification therefore never rewrite the registered manifest.
    """
    return {
        "format": MANIFEST_FORMAT,
        "project_id": project_id,
        "hypothesis_id": hypothesis_id,
        "version_id": version_id,
        "version": int(version),
        "parent_version_id": parent_version_id,
        "statement": content["statement"],
        "mechanism": content["mechanism"],
        "prediction": content["prediction"],
        "falsification_criteria": content["falsification_criteria"],
        "boundary_conditions": content["boundary_conditions"],
        "created_by": created_by,
        "change_reason": change_reason,
        "created_at_utc": created_at,
    }


def _manifest_relative_path(hypothesis_id: str, version: int, digest: str) -> str:
    return f"hypotheses/{hypothesis_id}/v{version}-{digest}.json"


def _write_manifest(project_id: str, relative_path: str, raw: bytes) -> None:
    path = (_workspace(project_id) / relative_path).resolve()
    path.relative_to(_workspace(project_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise HTTPException(409, detail="Hypothesis manifest path already contains different bytes")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def manifest_integrity(row: Any) -> dict[str, Any]:
    """Verify the DB ledger, canonical JSON, content-addressed file, and row content."""
    value = dict(row)
    issues: list[str] = []
    manifest: dict[str, Any] | None = None
    raw_text = str(value.get("manifest_json") or "")
    ledger_sha = str(value.get("manifest_sha256") or "")
    if not raw_text:
        issues.append("manifest_json_missing")
    else:
        try:
            parsed = json.loads(raw_text)
            if not isinstance(parsed, dict):
                raise ValueError("manifest must be an object")
            manifest = parsed
            canonical = _canonical(parsed)
            if canonical.decode("utf-8") != raw_text:
                issues.append("manifest_json_not_canonical")
            if _sha256(canonical) != ledger_sha:
                issues.append("manifest_ledger_hash_mismatch")
            expected_content = {name: str(value.get(name) or "") for name in EDITABLE_FIELDS}
            expected = _manifest_document(
                project_id=value["project_id"],
                hypothesis_id=value["hypothesis_id"],
                version_id=value["id"],
                version=int(value["version"]),
                parent_version_id=value.get("parent_version_id"),
                content=expected_content,
                created_by=value["created_by"],
                change_reason=value["change_reason"],
                created_at=str(value["created_at"]),
            )
            if parsed != expected:
                issues.append("manifest_row_content_mismatch")
        except (json.JSONDecodeError, TypeError, ValueError, KeyError):
            issues.append("manifest_json_invalid")
    relative = str(value.get("manifest_path") or "")
    file_sha: str | None = None
    if not relative:
        issues.append("manifest_path_missing")
    else:
        try:
            path = (_workspace(value["project_id"]) / relative).resolve()
            path.relative_to(_workspace(value["project_id"]))
            if not path.is_file():
                issues.append("manifest_file_missing")
            else:
                file_raw = path.read_bytes()
                file_sha = _sha256(file_raw)
                if file_sha != ledger_sha:
                    issues.append("manifest_file_hash_mismatch")
                if raw_text and file_raw != raw_text.encode("utf-8"):
                    issues.append("manifest_file_ledger_mismatch")
        except (OSError, ValueError):
            issues.append("manifest_path_invalid")
    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "ledger_sha256": ledger_sha or None,
        "file_sha256": file_sha,
        "manifest": manifest,
    }


def _required_text(value: Any, name: str, *, limit: int = 12000) -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{name} is required")
    if len(text) > limit:
        raise HTTPException(status_code=422, detail=f"{name} exceeds {limit} characters")
    return text


def _content(values: dict[str, Any]) -> dict[str, str]:
    return {name: _required_text(values.get(name), name) for name in EDITABLE_FIELDS}


async def _ensure_schema(db: Any) -> None:
    """Validate that schema migrations ran before performing domain backfills."""
    required = {
        "hypothesis_versions": {"manifest_json", "manifest_sha256", "manifest_path", "manifest_artifact_id"},
        "experiment_runs": {"analysis_mode", "specification_sha256", "hypothesis_version_id", "hypothesis_manifest_sha256", "dependency_status", "stale_reason", "stale_at"},
        "claim_experiment_links": {"hypothesis_version_id", "hypothesis_manifest_sha256"},
    }
    for table, columns in required.items():
        rows = await (await db.execute(f"PRAGMA table_info({table})")).fetchall()
        present = {row["name"] for row in rows}
        missing = sorted(columns - present)
        if missing:
            raise RuntimeError(f"schema migration required for {table}: {missing}")

    # Backfill manifests produced by the short-lived pre-manifest development
    # build.  The original row timestamps/content remain the canonical source.
    rows = await (await db.execute(
        "SELECT * FROM hypothesis_versions WHERE manifest_json IS NULL OR manifest_sha256 IS NULL "
        "OR manifest_path IS NULL OR manifest_artifact_id IS NULL"
    )).fetchall()
    for source in rows:
        row = dict(source)
        content = {name: str(row[name]) for name in EDITABLE_FIELDS}
        document = _manifest_document(
            project_id=row["project_id"],
            hypothesis_id=row["hypothesis_id"],
            version_id=row["id"],
            version=int(row["version"]),
            parent_version_id=row["parent_version_id"],
            content=content,
            created_by=row["created_by"],
            change_reason=row["change_reason"],
            created_at=str(row["created_at"]),
        )
        raw = _canonical(document)
        digest = _sha256(raw)
        relative = _manifest_relative_path(row["hypothesis_id"], int(row["version"]), digest)
        artifact_id = str(row.get("manifest_artifact_id") or uuid.uuid4().hex)
        _write_manifest(row["project_id"], relative, raw)
        await db.execute(
            "UPDATE hypothesis_versions SET manifest_json=?,manifest_sha256=?,manifest_path=?,manifest_artifact_id=? WHERE id=?",
            (raw.decode("utf-8"), digest, relative, artifact_id, row["id"]),
        )
        await db.execute(
            "INSERT OR IGNORE INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, row["project_id"], "hypothesis.manifest", digest, f"hypothesis:{row['hypothesis_id']}:v{row['version']}:{relative}", "verified"),
        )
    await db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_hypothesis_manifest_sha256 ON hypothesis_versions(project_id,manifest_sha256)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_experiment_hypothesis_dependency ON experiment_runs(project_id,hypothesis_version_id,dependency_status)"
    )


def _binding(row: Any) -> dict[str, Any]:
    value = dict(row)
    return {
        "hypothesis_id": value["hypothesis_id"],
        "version_id": value["id"],
        "version": int(value["version"]),
        "manifest_sha256": value["manifest_sha256"],
        "manifest_path": value["manifest_path"],
        "frozen_at": value.get("frozen_at"),
        "frozen_by": value.get("frozen_by"),
    }


async def current_frozen_manifest_set(
    db: Any,
    project_id: str,
    *,
    require: bool = True,
) -> dict[str, Any]:
    """Return the canonical set of current frozen registered hypotheses."""
    await _ensure_schema(db)
    rows = await (await db.execute(
        "SELECT h.* FROM hypothesis_versions h "
        "JOIN (SELECT hypothesis_id,MAX(version) AS version FROM hypothesis_versions WHERE project_id=? GROUP BY hypothesis_id) current "
        "ON current.hypothesis_id=h.hypothesis_id AND current.version=h.version "
        "WHERE h.project_id=? AND h.status='frozen' ORDER BY h.hypothesis_id,h.version",
        (project_id, project_id),
    )).fetchall()
    if require and not rows:
        raise HTTPException(409, detail="At least one current registered hypothesis must be frozen")
    bindings: list[dict[str, Any]] = []
    hypotheses: list[dict[str, Any]] = []
    for row in rows:
        integrity = manifest_integrity(row)
        if not integrity["passed"]:
            raise HTTPException(
                409,
                detail={
                    "message": "A frozen hypothesis manifest failed integrity validation",
                    "version_id": row["id"],
                    "issues": integrity["issues"],
                },
            )
        bindings.append(_binding(row))
        hypotheses.append({
            "hypothesis_id": row["hypothesis_id"],
            "version_id": row["id"],
            "version": int(row["version"]),
            "statement": row["statement"],
            "mechanism": row["mechanism"],
            "prediction": row["prediction"],
            "falsification_criteria": row["falsification_criteria"],
            "boundary_conditions": row["boundary_conditions"],
            "manifest_sha256": row["manifest_sha256"],
        })
    return {
        "bindings": bindings,
        "hypotheses": hypotheses,
        "manifest_set_sha256": _sha256(_canonical(bindings)),
    }


async def require_experiment_binding(
    db: Any,
    project_id: str,
    version_id: str,
    *,
    require_frozen: bool,
) -> tuple[Any, dict[str, Any]]:
    await _ensure_schema(db)
    row = await _version(db, project_id, version_id)
    await _require_current(db, row)
    if require_frozen and row["status"] != "frozen":
        raise HTTPException(409, detail="Confirmatory analysis requires a current frozen hypothesis version")
    if row["status"] in TERMINAL_STATUSES:
        raise HTTPException(409, detail="A terminal hypothesis version cannot bind a new experiment")
    integrity = manifest_integrity(row)
    if not integrity["passed"]:
        raise HTTPException(409, detail={"message": "Hypothesis manifest integrity failed", "issues": integrity["issues"]})
    return row, _binding(row)


async def _invalidate_dependents(
    db: Any,
    project_id: str,
    version_id: str,
    event_type: str,
    reason: str,
) -> dict[str, list[str]]:
    await _ensure_schema(db)
    experiment_rows = await (await db.execute(
        "SELECT id FROM experiment_runs WHERE project_id=? AND hypothesis_version_id=? AND dependency_status='current'",
        (project_id, version_id),
    )).fetchall()
    experiment_ids = [row["id"] for row in experiment_rows]
    if experiment_ids:
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in experiment_ids)
        stale_reason = f"{event_type}: {reason}"
        await db.execute(
            f"UPDATE experiment_runs SET dependency_status='stale',stale_reason=?,stale_at=?,updated_at=CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            (stale_reason, now, *experiment_ids),
        )
        await db.execute(
            f"UPDATE claim_experiment_links SET status='stale',review_reason=?,updated_at=CURRENT_TIMESTAMP WHERE experiment_run_id IN ({placeholders})",
            (stale_reason, *experiment_ids),
        )
        for run_id in experiment_ids:
            await db.execute(
                "UPDATE research_artifacts SET status='stale' WHERE project_id=? AND provenance=?",
                (project_id, f"experiment:{run_id}"),
            )

    draft_rows = await (await db.execute(
        "SELECT id,artifact_id FROM approved_drafts WHERE project_id=? AND status='current'",
        (project_id,),
    )).fetchall()
    draft_ids = [row["id"] for row in draft_rows]
    if draft_ids:
        now = datetime.now(timezone.utc).isoformat()
        stale_reason = f"{event_type}: {reason}"
        await db.execute(
            "UPDATE approved_drafts SET status='stale',stale_reason=?,stale_at=?,updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND status='current'",
            (stale_reason, now, project_id),
        )
        for row in draft_rows:
            await db.execute("UPDATE research_artifacts SET status='stale' WHERE id=?", (row["artifact_id"],))
    return {"experiment_run_ids": experiment_ids, "draft_ids": draft_ids}


async def _project_for_update(db: Any, project_id: str) -> Any:
    row = await (await db.execute(
        "SELECT id,status FROM research_projects WHERE id=?", (project_id,)
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Research project not found")
    if row["status"] == "approved":
        raise HTTPException(
            status_code=409,
            detail="Approved research contract is immutable; create a project revision first",
        )
    return row


async def _version(db: Any, project_id: str, version_id: str) -> Any:
    row = await (await db.execute(
        "SELECT * FROM hypothesis_versions WHERE id=? AND project_id=?",
        (version_id, project_id),
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Hypothesis version not found")
    return row


async def _require_current(db: Any, row: Any) -> None:
    latest = await (await db.execute(
        "SELECT id FROM hypothesis_versions WHERE project_id=? AND hypothesis_id=? ORDER BY version DESC LIMIT 1",
        (row["project_id"], row["hypothesis_id"]),
    )).fetchone()
    if not latest or latest["id"] != row["id"]:
        raise HTTPException(status_code=409, detail="Only the current hypothesis version can change state")


async def _record_event(
    db: Any,
    row: dict[str, Any],
    event_type: str,
    actor: str,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> None:
    event_payload = {
        "hypothesis_id": row["hypothesis_id"],
        "version_id": row["id"],
        "version": row["version"],
        **(payload or {}),
    }
    encoded = json.dumps(event_payload, ensure_ascii=False, sort_keys=True)
    await db.execute(
        "INSERT INTO hypothesis_events (project_id,hypothesis_id,version_id,event_type,actor,reason,payload) VALUES (?,?,?,?,?,?,?)",
        (row["project_id"], row["hypothesis_id"], row["id"], event_type, actor, reason, encoded),
    )
    await db.execute(
        "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
        (row["project_id"], event_type, actor, json.dumps({**event_payload, "reason": reason}, ensure_ascii=False, sort_keys=True)),
    )
    await db.execute(
        "UPDATE research_projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (row["project_id"],),
    )


async def read_project(db: Any, project_id: str) -> dict[str, Any]:
    await _ensure_schema(db)
    rows = await (await db.execute(
        "SELECT * FROM hypothesis_versions WHERE project_id=? ORDER BY created_at DESC, hypothesis_id, version DESC",
        (project_id,),
    )).fetchall()
    events = await (await db.execute(
        "SELECT * FROM hypothesis_events WHERE project_id=? ORDER BY id",
        (project_id,),
    )).fetchall()
    by_version: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        item = dict(event)
        item["payload"] = json.loads(item["payload"] or "{}")
        by_version.setdefault(item["version_id"], []).append(item)
    latest: dict[str, int] = {}
    for row in rows:
        latest[row["hypothesis_id"]] = max(latest.get(row["hypothesis_id"], 0), int(row["version"]))
    hypotheses: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["is_current"] = int(item["version"]) == latest[item["hypothesis_id"]]
        item["events"] = by_version.get(item["id"], [])
        integrity = manifest_integrity(item)
        item["manifest_document"] = integrity.pop("manifest")
        item["manifest"] = {
            "path": item["manifest_path"],
            "sha256": item["manifest_sha256"],
            "artifact_id": item["manifest_artifact_id"],
        }
        item["manifest_integrity"] = integrity
        hypotheses.append(item)
    current = [item for item in hypotheses if item["is_current"]]
    frozen = [item for item in current if item["status"] == "frozen"]
    falsified = [item for item in current if item["status"] == "falsified"]
    frozen_integrity_passed = bool(frozen) and all(
        item["manifest_integrity"]["passed"] for item in frozen
    )
    return {
        "hypotheses": hypotheses,
        "hypothesis_readiness": {
            "ready": frozen_integrity_passed,
            "current_count": len(current),
            "frozen_count": len(frozen),
            "falsified_count": len(falsified),
            "manifest_integrity_passed": all(item["manifest_integrity"]["passed"] for item in current),
            "rule": "At least one current hypothesis with an intact immutable manifest must be frozen before confirmatory work.",
        },
    }


async def read(project_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        exists = await (await db.execute(
            "SELECT id FROM research_projects WHERE id=?", (project_id,)
        )).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Research project not found")
        return await read_project(db, project_id)
    finally:
        await db.close()


async def create(
    project_id: str,
    values: dict[str, Any],
    actor: str,
    change_reason: str,
) -> dict[str, Any]:
    content = _content(values)
    actor = _required_text(actor, "actor", limit=240)
    reason = _required_text(change_reason, "change_reason", limit=4000)
    hypothesis_id = uuid.uuid4().hex
    version_id = uuid.uuid4().hex
    artifact_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    document = _manifest_document(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        version_id=version_id,
        version=1,
        parent_version_id=None,
        content=content,
        created_by=actor,
        change_reason=reason,
        created_at=created_at,
    )
    manifest_raw = _canonical(document)
    manifest_sha256 = _sha256(manifest_raw)
    manifest_path = _manifest_relative_path(hypothesis_id, 1, manifest_sha256)
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_schema(db)
        await _project_for_update(db, project_id)
        _write_manifest(project_id, manifest_path, manifest_raw)
        row = {
            "id": version_id,
            "project_id": project_id,
            "hypothesis_id": hypothesis_id,
            "version": 1,
        }
        await db.execute(
            """INSERT INTO hypothesis_versions
               (id,project_id,hypothesis_id,version,parent_version_id,statement,mechanism,prediction,falsification_criteria,boundary_conditions,manifest_json,manifest_sha256,manifest_path,manifest_artifact_id,status,change_reason,created_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                version_id, project_id, hypothesis_id, 1, None,
                content["statement"], content["mechanism"], content["prediction"],
                content["falsification_criteria"], content["boundary_conditions"],
                manifest_raw.decode("utf-8"), manifest_sha256, manifest_path, artifact_id,
                "draft", reason, actor, created_at, created_at,
            ),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, project_id, "hypothesis.manifest", manifest_sha256, f"hypothesis:{hypothesis_id}:v1:{manifest_path}", "verified"),
        )
        await _record_event(
            db,
            row,
            "hypothesis_created",
            actor,
            reason,
            {"status": "draft", "manifest_sha256": manifest_sha256, "manifest_path": manifest_path, "artifact_id": artifact_id},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    state = await read(project_id)
    return next(item for item in state["hypotheses"] if item["id"] == version_id)


async def revise(
    project_id: str,
    version_id: str,
    values: dict[str, Any],
    actor: str,
    change_reason: str,
) -> dict[str, Any]:
    content = _content(values)
    actor = _required_text(actor, "actor", limit=240)
    reason = _required_text(change_reason, "change_reason", limit=4000)
    new_id = uuid.uuid4().hex
    artifact_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_schema(db)
        await _project_for_update(db, project_id)
        old = await _version(db, project_id, version_id)
        await _require_current(db, old)
        if old["status"] == "frozen":
            raise HTTPException(status_code=409, detail="Unfreeze the hypothesis before creating a revision")
        if old["status"] in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="A terminal hypothesis version cannot be revised")
        next_version = int(old["version"]) + 1
        document = _manifest_document(
            project_id=project_id,
            hypothesis_id=old["hypothesis_id"],
            version_id=new_id,
            version=next_version,
            parent_version_id=old["id"],
            content=content,
            created_by=actor,
            change_reason=reason,
            created_at=created_at,
        )
        manifest_raw = _canonical(document)
        manifest_sha256 = _sha256(manifest_raw)
        manifest_path = _manifest_relative_path(old["hypothesis_id"], next_version, manifest_sha256)
        _write_manifest(project_id, manifest_path, manifest_raw)
        invalidated = await _invalidate_dependents(
            db, project_id, old["id"], "hypothesis_revised", reason
        )
        await db.execute(
            "UPDATE hypothesis_versions SET status='superseded',state_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reason, old["id"]),
        )
        row = {
            "id": new_id,
            "project_id": project_id,
            "hypothesis_id": old["hypothesis_id"],
            "version": next_version,
        }
        await db.execute(
            """INSERT INTO hypothesis_versions
               (id,project_id,hypothesis_id,version,parent_version_id,statement,mechanism,prediction,falsification_criteria,boundary_conditions,manifest_json,manifest_sha256,manifest_path,manifest_artifact_id,status,change_reason,created_by,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id, project_id, old["hypothesis_id"], next_version, old["id"],
                content["statement"], content["mechanism"], content["prediction"],
                content["falsification_criteria"], content["boundary_conditions"],
                manifest_raw.decode("utf-8"), manifest_sha256, manifest_path, artifact_id,
                "draft", reason, actor, created_at, created_at,
            ),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, project_id, "hypothesis.manifest", manifest_sha256, f"hypothesis:{old['hypothesis_id']}:v{next_version}:{manifest_path}", "verified"),
        )
        await _record_event(
            db, row, "hypothesis_revised", actor, reason,
            {
                "status": "draft",
                "parent_version_id": old["id"],
                "manifest_sha256": manifest_sha256,
                "manifest_path": manifest_path,
                "artifact_id": artifact_id,
                "invalidated": invalidated,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    state = await read(project_id)
    return next(item for item in state["hypotheses"] if item["id"] == new_id)


async def transition(
    project_id: str,
    version_id: str,
    action: str,
    actor: str,
    reason: str,
) -> dict[str, Any]:
    actor = _required_text(actor, "actor", limit=240)
    reason = _required_text(reason, "reason", limit=4000)
    transitions = {
        "freeze": ({"draft"}, "frozen", "hypothesis_frozen"),
        "unfreeze": ({"frozen"}, "draft", "hypothesis_unfrozen"),
        "falsify": ({"draft", "frozen"}, "falsified", "hypothesis_falsified"),
    }
    if action not in transitions:
        raise HTTPException(status_code=422, detail="Unsupported hypothesis transition")
    allowed, target, event_type = transitions[action]
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_schema(db)
        await _project_for_update(db, project_id)
        current = await _version(db, project_id, version_id)
        await _require_current(db, current)
        if current["status"] not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot {action} a hypothesis in {current['status']} state",
            )
        if action == "freeze":
            integrity = manifest_integrity(current)
            if not integrity["passed"]:
                raise HTTPException(
                    409,
                    detail={"message": "Hypothesis manifest integrity failed", "issues": integrity["issues"]},
                )
        invalidated = {"experiment_run_ids": [], "draft_ids": []}
        if action in {"unfreeze", "falsify"}:
            invalidated = await _invalidate_dependents(db, project_id, version_id, event_type, reason)
        assignments = ["status=?", "state_reason=?", "updated_at=CURRENT_TIMESTAMP"]
        params: list[Any] = [target, reason]
        if action == "freeze":
            assignments.extend(["frozen_by=?", "frozen_at=CURRENT_TIMESTAMP"])
            params.append(actor)
        elif action == "unfreeze":
            assignments.extend(["frozen_by=NULL", "frozen_at=NULL"])
        elif action == "falsify":
            assignments.extend(["falsified_by=?", "falsified_at=CURRENT_TIMESTAMP"])
            params.append(actor)
        params.append(version_id)
        await db.execute(
            f"UPDATE hypothesis_versions SET {','.join(assignments)} WHERE id=?",
            tuple(params),
        )
        row = dict(current)
        await _record_event(
            db,
            row,
            event_type,
            actor,
            reason,
            {
                "from": current["status"],
                "to": target,
                "manifest_sha256": current["manifest_sha256"],
                "invalidated": invalidated,
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    state = await read(project_id)
    return next(item for item in state["hypotheses"] if item["id"] == version_id)
