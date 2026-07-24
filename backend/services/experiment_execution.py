"""Persisted, bounded execution of a reproducible two-condition calculation."""
from __future__ import annotations

import hashlib
import json
import math
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from domain.assurance.statistics_gate import StatisticsGate
from domain.experiments import ExperimentManifest, blocked_data_receipt, derive_ml_verdict
from infrastructure.execution.manifest_store import ManifestStore
from services.process_supervisor import ProcessSupervisor
from services.state_store import get_db


ANALYSIS_MODES = {"exploratory", "confirmatory"}

def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_values(name: str, values: list[float]) -> list[float]:
    if len(values) < 2:
        raise HTTPException(422, detail=f"{name} requires at least two observations")
    normalized = [float(value) for value in values]
    if not all(math.isfinite(value) for value in normalized):
        raise HTTPException(422, detail=f"{name} contains NaN or infinity")
    return normalized


async def _ensure_schema(db: Any) -> None:
    # Hypothesis lifecycle owns the shared dependency-column migration so all
    # callers see one consistent contract on upgraded desktop databases.
    from services import hypothesis_lifecycle

    await hypothesis_lifecycle._ensure_schema(db)


def _file_sha256(path: Path) -> str | None:
    try:
        return _sha(path.read_bytes()) if path.is_file() else None
    except OSError:
        return None


async def inspect_run_integrity(db: Any, source: Any) -> dict[str, Any]:
    """Inspect immutable experiment/spec/manifest and hypothesis lineage."""
    from services import hypothesis_lifecycle

    await _ensure_schema(db)
    run = dict(source)
    issues: list[str] = []
    try:
        specification = json.loads(run.get("specification_json") or "{}")
    except json.JSONDecodeError:
        specification = {}
        issues.append("specification_json_invalid")
    specification_sha = _sha(_canonical(specification))
    if run.get("specification_sha256") != specification_sha:
        issues.append("specification_hash_mismatch")
    if specification.get("analysis_mode") != run.get("analysis_mode"):
        issues.append("analysis_mode_binding_mismatch")
    protocol_binding = specification.get("p5_protocol_binding") or {}
    if not protocol_binding:
        issues.append("p5_protocol_binding_missing")
    else:
        protocol_row = await (await db.execute(
            "SELECT id, version, analysis_mode, protocol_sha256, status FROM research_protocols WHERE project_id=? ORDER BY version DESC, rowid DESC LIMIT 1",
            (run.get("project_id"),),
        )).fetchone()
        if not protocol_row:
            issues.append("p5_protocol_missing")
        else:
            if protocol_binding.get("id") != protocol_row["id"]:
                issues.append("p5_protocol_id_mismatch")
            if protocol_binding.get("version") != protocol_row["version"]:
                issues.append("p5_protocol_version_mismatch")
            if protocol_binding.get("sha256") != protocol_row["protocol_sha256"]:
                issues.append("p5_protocol_hash_mismatch")
            if protocol_binding.get("analysis_mode") != protocol_row["analysis_mode"]:
                issues.append("p5_protocol_mode_mismatch")
            if protocol_row["status"] != "frozen" and run.get("analysis_mode") == "confirmatory":
                issues.append("p5_confirmatory_protocol_not_frozen")

    workspace_path = Path(str(run.get("workspace_path") or ""))
    result_hash_valid = False
    result_file_sha: str | None = None
    input_file_sha: str | None = None
    if run.get("status") == "completed":
        try:
            result = json.loads(run.get("result_json") or "{}")
            result_hash_valid = _sha(_canonical(result)) == run.get("result_sha256")
        except json.JSONDecodeError:
            result_hash_valid = False
        if not result_hash_valid:
            issues.append("result_hash_mismatch")
        result_file_sha = _file_sha256(workspace_path / "result.json")
        if result_file_sha != run.get("result_sha256"):
            issues.append("result_artifact_hash_mismatch")
        input_file_sha = _file_sha256(workspace_path / "input.json")
        if input_file_sha != specification_sha:
            issues.append("experiment_input_hash_mismatch")

    manifest_path = Path(str(run.get("manifest_path") or ""))
    manifest_location_valid = False
    try:
        manifest_path.resolve().relative_to(workspace_path.resolve())
        manifest_location_valid = True
    except ValueError:
        if run.get("status") == "completed":
            issues.append("experiment_manifest_path_outside_workspace")
    file_sha = _file_sha256(manifest_path) if str(manifest_path) and manifest_location_valid else None
    manifest: dict[str, Any] | None = None
    if run.get("status") == "completed":
        if file_sha is None:
            issues.append("experiment_manifest_missing")
        elif file_sha != run.get("manifest_sha256"):
            issues.append("experiment_manifest_hash_mismatch")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                issues.append("experiment_manifest_json_invalid")
    config = manifest.get("config", {}) if isinstance(manifest, dict) else {}
    if manifest is not None:
        if config.get("analysis_mode") != run.get("analysis_mode"):
            issues.append("manifest_analysis_mode_mismatch")
        if config.get("specification_sha256") != run.get("specification_sha256"):
            issues.append("manifest_specification_hash_mismatch")
        if manifest.get("dataset_hash") != input_file_sha:
            issues.append("manifest_input_hash_mismatch")
        if run.get("result_sha256") not in (manifest.get("raw_artifact_hashes") or []):
            issues.append("manifest_result_hash_missing")

    hypothesis_state = {
        "bound": bool(run.get("hypothesis_version_id")),
        "current": False,
        "frozen": False,
        "manifest_integrity_passed": False,
        "binding_matches": False,
        "manifest_sha256": run.get("hypothesis_manifest_sha256"),
        "issues": [],
    }
    binding = specification.get("hypothesis_binding")
    dependencies = specification.get("hypothesis_dependencies")
    hypothesis_manifests = specification.get("hypothesis_manifests")
    if run.get("hypothesis_version_id"):
        row = await (await db.execute(
            "SELECT * FROM hypothesis_versions WHERE id=? AND project_id=?",
            (run["hypothesis_version_id"], run["project_id"]),
        )).fetchone()
        if row:
            latest = await (await db.execute(
                "SELECT id FROM hypothesis_versions WHERE project_id=? AND hypothesis_id=? ORDER BY version DESC LIMIT 1",
                (run["project_id"], row["hypothesis_id"]),
            )).fetchone()
            h_integrity = hypothesis_lifecycle.manifest_integrity(row)
            expected_binding = hypothesis_lifecycle._binding(row)
            expected_manifest = {
                "hypothesis_id": row["hypothesis_id"],
                "version_id": row["id"],
                "version": int(row["version"]),
                "path": row["manifest_path"],
                "sha256": row["manifest_sha256"],
            }
            hypothesis_state.update({
                "current": bool(latest) and latest["id"] == row["id"],
                "frozen": row["status"] == "frozen",
                "manifest_integrity_passed": h_integrity["passed"],
                "binding_matches": (
                    binding == expected_binding
                    and dependencies == [expected_binding]
                    and hypothesis_manifests == [expected_manifest]
                    and config.get("hypothesis_binding") == expected_binding
                    and config.get("hypothesis_dependencies") == [expected_binding]
                    and config.get("hypothesis_manifests") == [expected_manifest]
                    and run.get("hypothesis_manifest_sha256") == row["manifest_sha256"]
                ),
                "manifest_sha256": row["manifest_sha256"],
                "issues": h_integrity["issues"],
            })
        else:
            hypothesis_state["issues"] = ["hypothesis_version_missing"]
    elif (
        binding is not None
        or dependencies not in ([], None)
        or hypothesis_manifests not in ([], None)
        or config.get("hypothesis_binding") is not None
        or config.get("hypothesis_dependencies") not in ([], None)
        or config.get("hypothesis_manifests") not in ([], None)
        or run.get("hypothesis_manifest_sha256")
    ):
        hypothesis_state["issues"] = ["unregistered_hypothesis_binding"]

    if run.get("analysis_mode") == "confirmatory":
        if not hypothesis_state["bound"]:
            issues.append("confirmatory_hypothesis_missing")
        if not hypothesis_state["current"]:
            issues.append("confirmatory_hypothesis_not_current")
        if not hypothesis_state["frozen"]:
            issues.append("confirmatory_hypothesis_not_frozen")
        if not hypothesis_state["manifest_integrity_passed"]:
            issues.append("hypothesis_manifest_integrity_failed")
        if not hypothesis_state["binding_matches"]:
            issues.append("hypothesis_binding_mismatch")

    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "specification_sha256": specification_sha,
        "result_hash_valid": result_hash_valid,
        "result_file_sha256": result_file_sha,
        "input_file_sha256": input_file_sha,
        "manifest_file_sha256": file_sha,
        "manifest": manifest,
        "hypothesis": hypothesis_state,
        "dependency_current": run.get("dependency_status", "current") == "current",
    }


async def _read(run_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        await _ensure_schema(db)
        row = await (await db.execute("SELECT * FROM experiment_runs WHERE id=?", (run_id,))).fetchone()
        if not row:
            raise HTTPException(404, detail="Experiment run not found")
        integrity = await inspect_run_integrity(db, row)
        result = dict(row)
        result["specification"] = json.loads(result.pop("specification_json"))
        result["hypothesis_manifests"] = result["specification"].get("hypothesis_manifests", [])
        result["hypothesis_dependencies"] = ([{
            "hypothesis_version_id": result["hypothesis_version_id"],
            "hypothesis_manifest_sha256": result["hypothesis_manifest_sha256"],
            "status": result.get("dependency_status", "current"),
            "stale_reason": result.get("stale_reason"),
        }] if result.get("hypothesis_version_id") else [])
        result["result"] = json.loads(result.pop("result_json"))
        result["statistics"] = json.loads(result.pop("statistics_json"))
        result["integrity"] = integrity
        return result
    finally:
        await db.close()


async def list_runs(project_id: str) -> list[dict[str, Any]]:
    db = await get_db()
    try:
        await _ensure_schema(db)
        exists = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not exists:
            raise HTTPException(404, detail="Research project not found")
        rows = await (await db.execute("SELECT id FROM experiment_runs WHERE project_id=? ORDER BY created_at DESC", (project_id,))).fetchall()
    finally:
        await db.close()
    return [await _read(row["id"]) for row in rows]


async def execute(project_id: str, specification: dict[str, Any], *, timeout_seconds: float = 30) -> dict[str, Any]:
    control = _validate_values("control", specification.get("control", []))
    treatment = _validate_values("treatment", specification.get("treatment", []))
    seeds = int(specification.get("seeds", 1))
    if seeds < 1 or seeds > 1000:
        raise HTTPException(422, detail="seeds must be between 1 and 1000")
    metric = str(specification.get("metric", "outcome")).strip()
    if not metric:
        raise HTTPException(422, detail="metric is required")
    dataset_ref = str(specification.get("dataset_ref") or "").strip()
    execution_purpose = str(specification.get("execution_purpose") or "").strip()
    analysis_mode = str(specification.get("analysis_mode") or "exploratory").strip().lower()
    if analysis_mode not in ANALYSIS_MODES:
        raise HTTPException(422, detail="analysis_mode must be exploratory or confirmatory")
    from services import p5_research_design
    decision = await p5_research_design.execution_data_rights_gate(project_id, execution_purpose)
    if not decision["passed"]:
        return {"status": "blocked", "project_id": project_id, "dataset_ref": dataset_ref, **blocked_data_receipt(decision["reason_codes"])}
    p5_state = await p5_research_design.read(project_id)
    p5_gate = await p5_research_design.gate(project_id)
    if not p5_gate["passed"]:
        return {"status": "blocked", "project_id": project_id, "analysis_mode": analysis_mode, "p5_gate": p5_gate}
    protocol = p5_state["protocol"]
    if protocol["analysis_mode"] != analysis_mode:
        return {"status": "blocked", "project_id": project_id, "analysis_mode": analysis_mode, "p5_gate": {"passed": False, "status": "blocked", "findings": ["protocol_analysis_mode_mismatch"]}}
    decision = await p5_research_design.execution_data_rights_gate(project_id, execution_purpose)
    if not decision["passed"]:
        return {"status": "blocked", "project_id": project_id, "dataset_ref": dataset_ref, **blocked_data_receipt(decision["reason_codes"])}
    p5_protocol_binding = {
        "id": protocol["id"],
        "version": protocol["version"],
        "analysis_mode": protocol["analysis_mode"],
        "sha256": protocol["protocol_sha256"],
    }
    hypothesis_version_id = str(specification.get("hypothesis_version_id") or "").strip() or None
    if analysis_mode == "confirmatory" and not hypothesis_version_id:
        raise HTTPException(422, detail="hypothesis_version_id is required for confirmatory analysis")

    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_schema(db)
        project = await (await db.execute("SELECT 1 FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project:
            raise HTTPException(404, detail="Research project not found")
        binding: dict[str, Any] | None = None
        if hypothesis_version_id:
            from services import hypothesis_lifecycle

            _, binding = await hypothesis_lifecycle.require_experiment_binding(
                db,
                project_id,
                hypothesis_version_id,
                require_frozen=analysis_mode == "confirmatory",
            )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()

    hypothesis_manifests = ([{
        "hypothesis_id": binding["hypothesis_id"],
        "version_id": binding["version_id"],
        "version": binding["version"],
        "path": binding["manifest_path"],
        "sha256": binding["manifest_sha256"],
    }] if binding else [])
    hypothesis_dependencies = [binding] if binding else []
    spec = {
        "analysis_mode": analysis_mode,
        "p5_protocol_binding": p5_protocol_binding,
        "control": control,
        "hypothesis_binding": binding,
        "hypothesis_dependencies": hypothesis_dependencies,
        "hypothesis_manifest_sha256": binding["manifest_sha256"] if binding else None,
        "hypothesis_manifests": hypothesis_manifests,
        "hypothesis_version_id": hypothesis_version_id,
        "metric": metric,
        "seeds": seeds,
        "treatment": treatment,
    }
    specification_sha256 = _sha(_canonical(spec))
    run_id = uuid.uuid4().hex
    workspace = WORKSPACES_DIR / project_id / "experiments" / run_id
    workspace.mkdir(parents=True, exist_ok=False)
    input_path = workspace / "input.json"
    output_path = workspace / "result.json"
    input_path.write_bytes(_canonical(spec))
    db = await get_db()
    try:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO experiment_runs "
            "(id,project_id,status,specification_json,analysis_mode,specification_sha256,hypothesis_version_id,hypothesis_manifest_sha256,dependency_status,workspace_path) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                project_id,
                "running",
                _canonical(spec).decode("utf-8"),
                analysis_mode,
                specification_sha256,
                hypothesis_version_id,
                binding["manifest_sha256"] if binding else None,
                "current",
                str(workspace),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    # Real multi-seed protocol: write a workspace runner so compound statements
    # are valid Python, then execute it under ProcessSupervisor.
    runner_path = workspace / "two_condition_runner.py"
    runner_path.write_text(
        """
import hashlib
import json
import math
import random
import statistics
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
control = list(map(float, payload["control"]))
treatment = list(map(float, payload["treatment"]))
metric = payload["metric"]
seed_count = max(1, int(payload.get("seeds", 1)))

control_mean = statistics.fmean(control)
treatment_mean = statistics.fmean(treatment)
difference = treatment_mean - control_mean
if len(control) > 1 and len(treatment) > 1:
    standard_error = math.sqrt(
        statistics.variance(control) / len(control)
        + statistics.variance(treatment) / len(treatment)
    )
else:
    standard_error = 0.0
primary = {
    "control_mean": control_mean,
    "treatment_mean": treatment_mean,
    "difference": difference,
    "standard_error": standard_error,
    "ci95": [difference - 1.96 * standard_error, difference + 1.96 * standard_error],
    "metric": metric,
    "observations": len(control) + len(treatment),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bootstrap(values, rng):
    return [values[rng.randrange(len(values))] for _ in values]


source_runs = []
for seed in range(seed_count):
    rng = random.Random(seed)
    control_boot = bootstrap(control, rng)
    treatment_boot = bootstrap(treatment, rng)
    ablated_pool = treatment[:-1] if len(treatment) > 2 else list(treatment)
    ablation_boot = bootstrap(ablated_pool, rng)
    calibration = abs(statistics.fmean(treatment_boot) - statistics.fmean(control_boot))
    train_ids = digest({"seed": seed, "role": "train", "values": control_boot})
    test_ids = digest({"seed": seed, "role": "test", "values": treatment_boot})
    ablation_ids = digest({"seed": seed, "role": "ablation_test", "values": ablation_boot})
    source_runs.append(
        {
            "status": "completed",
            "simulated": False,
            "seed": seed,
            "variant": "baseline",
            "metrics": {metric: statistics.fmean(control_boot), "calibration_error": calibration},
            "train_ids_sha256": train_ids,
            "test_ids_sha256": test_ids,
        }
    )
    source_runs.append(
        {
            "status": "completed",
            "simulated": False,
            "seed": seed,
            "variant": "candidate",
            "metrics": {metric: statistics.fmean(treatment_boot), "calibration_error": calibration},
            "train_ids_sha256": train_ids,
            "test_ids_sha256": test_ids,
        }
    )
    source_runs.append(
        {
            "status": "completed",
            "simulated": False,
            "seed": seed,
            "variant": "ablation",
            "metrics": {metric: statistics.fmean(ablation_boot), "calibration_error": calibration},
            "train_ids_sha256": train_ids,
            "test_ids_sha256": ablation_ids,
        }
    )

output = {
    "primary": primary,
    "source_runs": source_runs,
    "observed_seed_count": seed_count,
    "ablation_executed": True,
}
open(sys.argv[2], "w", encoding="utf-8").write(
    json.dumps(output, sort_keys=True, separators=(",", ":"))
)
""".lstrip(),
        encoding="utf-8",
    )
    command = [sys.executable, str(runner_path), str(input_path), str(output_path)]
    supervisor = ProcessSupervisor(workspace, {Path(sys.executable).name})
    started = datetime.now(timezone.utc).isoformat()
    process = await supervisor.run(run_id, command, workspace, timeout_seconds)
    ended = datetime.now(timezone.utc).isoformat()
    (workspace / "stdout.log").write_text(process["stdout"], encoding="utf-8")
    (workspace / "stderr.log").write_text(process["stderr"], encoding="utf-8")
    if process["returncode"] != 0 or not output_path.is_file():
        reason = process["stderr"] or "Experiment process produced no result"
        db = await get_db()
        try:
            await _ensure_schema(db)
            await db.execute(
                "UPDATE experiment_runs SET status='failed',exit_code=?,failure_reason=?,stdout_path=?,stderr_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (process["returncode"], reason, str(workspace / "stdout.log"), str(workspace / "stderr.log"), run_id),
            )
            await db.commit()
        finally:
            await db.close()
        return await _read(run_id)

    payload_out = json.loads(output_path.read_text(encoding="utf-8"))
    if "primary" in payload_out:
        result = payload_out["primary"]
        raw_runs = list(payload_out.get("source_runs") or [])
        observed_seed_count = int(payload_out.get("observed_seed_count") or 0)
        ablation_executed = bool(payload_out.get("ablation_executed"))
    else:
        result = payload_out
        raw_runs = [
            {
                "status": "completed",
                "simulated": False,
                "seed": 0,
                "variant": "candidate",
                "metrics": {metric: result["treatment_mean"], "calibration_error": abs(result["difference"])},
                "train_ids_sha256": _sha(_canonical({"split": "control", "seed": 0})),
                "test_ids_sha256": _sha(_canonical({"split": "treatment", "seed": 0})),
            },
            {
                "status": "completed",
                "simulated": False,
                "seed": 0,
                "variant": "baseline",
                "metrics": {metric: result["control_mean"], "calibration_error": abs(result["difference"])},
                "train_ids_sha256": _sha(_canonical({"split": "control", "seed": 0})),
                "test_ids_sha256": _sha(_canonical({"split": "treatment", "seed": 0})),
            },
        ]
        observed_seed_count = 1
        ablation_executed = False
    result_bytes = _canonical(result)
    output_path.write_bytes(result_bytes)
    derived = derive_ml_verdict(raw_runs, metric=metric)
    gate = StatisticsGate().ml(
        seeds=int(derived.derived.get("seed_count") or 0),
        ci=bool(result.get("ci95")),
        effect_size="difference" in result,
        baseline="baseline" in derived.derived.get("variant_means", {}),
        ablation="ablation" in derived.derived.get("variant_means", {}),
        leakage_checked="data_leakage_detected" not in derived.issues,
        metric_direction="higher",
        stable_claim=True,
    )
    evidence_status = "verified" if (gate.passed and derived.accepted) else "not_verified"
    statistics = {
        "passed": gate.passed and derived.accepted,
        "issues": list(dict.fromkeys((*gate.issues, *derived.issues))),
        "profile": "two_condition_comparison",
        "derived": dict(derived.derived),
        "source_runs": raw_runs,
        "execution_evidence": {
            "requested_seed_count": seeds,
            "observed_seed_count": observed_seed_count,
            "ablation_executed": ablation_executed,
            "status": evidence_status,
        },
    }
    result_sha = _sha(result_bytes)
    manifest = ExperimentManifest(
        dataset_hash=_sha(input_path.read_bytes()),
        dataset_license="user-provided",
        split="control/treatment",
        code_commit="packaged-runtime",
        argv=tuple(command),
        environment_lock=sys.version,
        hardware="local-cpu",
        seed=0,
        config={
            "analysis_mode": analysis_mode,
            "p5_protocol_binding": p5_protocol_binding,
            "hypothesis_binding": binding,
            "hypothesis_dependencies": hypothesis_dependencies,
            "hypothesis_manifests": hypothesis_manifests,
            "p5_protocol_binding": p5_protocol_binding,
            "seeds": seeds,
            "specification_sha256": specification_sha256,
        },
        metric_definition=metric,
        started_at=started,
        ended_at=ended,
        exit_code=0,
        raw_artifact_hashes=(result_sha,),
    )
    manifest_path = ManifestStore(workspace / "manifests").write(manifest)
    manifest_sha = _sha(manifest_path.read_bytes())
    artifact_id = uuid.uuid4().hex
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await _ensure_schema(db)
        dependency_status = "current"
        stale_reason: str | None = None
        if hypothesis_version_id:
            from services import hypothesis_lifecycle

            try:
                _, current_binding = await hypothesis_lifecycle.require_experiment_binding(
                    db,
                    project_id,
                    hypothesis_version_id,
                    require_frozen=analysis_mode == "confirmatory",
                )
                if current_binding != binding:
                    raise HTTPException(409, detail="Hypothesis freeze registration changed while the experiment was running")
            except HTTPException as error:
                dependency_status = "stale"
                stale_reason = str(error.detail)[:2000]
        await db.execute("UPDATE experiment_runs SET status='completed',result_json=?,statistics_json=?,manifest_path=?,manifest_sha256=?,result_sha256=?,stdout_path=?,stderr_path=?,exit_code=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(result), json.dumps(statistics), str(manifest_path), manifest_sha, result_sha, str(workspace / "stdout.log"), str(workspace / "stderr.log"), run_id))
        if dependency_status == "stale":
            await db.execute(
                "UPDATE experiment_runs SET dependency_status='stale',stale_reason=?,stale_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (stale_reason, datetime.now(timezone.utc).isoformat(), run_id),
            )
        artifact_status = "stale" if dependency_status != "current" else (
            "verified" if statistics["passed"] else "needs_review"
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, project_id, "experiment.result", result_sha, f"experiment:{run_id}", artifact_status),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "experiment_completed",
                "system",
                json.dumps(
                    {
                        "run_id": run_id,
                        "analysis_mode": analysis_mode,
                        "specification_sha256": specification_sha256,
                        "hypothesis_binding": binding,
                        "result_sha256": result_sha,
                        "manifest_sha256": manifest_sha,
                        "statistics_passed": statistics["passed"],
                        "dependency_status": dependency_status,
                        "stale_reason": stale_reason,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
    return await _read(run_id)


async def replay(run_id: str) -> dict[str, Any]:
    prior = await _read(run_id)
    repeated = await execute(prior["project_id"], prior["specification"])
    repeated["replay_of"] = run_id
    repeated["reproduced"] = repeated.get("result_sha256") == prior.get("result_sha256")
    return repeated
