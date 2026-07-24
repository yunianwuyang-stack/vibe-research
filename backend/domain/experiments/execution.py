"""Reproducible, fail-closed execution primitives for P6."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


@dataclass(frozen=True)
class DataRightsGate:
    purpose: str
    jurisdiction: str
    retention_days: int
    pii_approved: bool = False
    license: str = ""

    @property
    def allowed(self) -> bool:
        return bool(self.purpose.strip() and self.jurisdiction.strip() and self.license.strip()
                    and self.retention_days > 0 and self.pii_approved)

    def assert_allowed(self) -> None:
        if not self.allowed:
            raise PermissionError("ethics/data-rights gate blocked execution")


@dataclass(frozen=True)
class ExecutionSpec:
    dataset_snapshot: Mapping[str, Any]
    environment_lock: Mapping[str, Any]
    command: tuple[str, ...]
    seeds: tuple[int, ...]
    hardware: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    simulated: bool = False
    data_rights: DataRightsGate | None = None
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if self.simulated:
            raise ValueError("simulated execution is disabled")
        if not self.command or not self.seeds:
            raise ValueError("command and at least one seed are required")
        if any(not isinstance(seed, int) for seed in self.seeds):
            raise ValueError("seeds must be integers")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout must be positive")

    @property
    def specification_hash(self) -> str:
        return _sha256_bytes(_canonical({
            "dataset_snapshot": self.dataset_snapshot,
            "environment_lock": self.environment_lock,
            "command": self.command,
            "seeds": self.seeds,
            "hardware": self.hardware,
            "result_schema": self.result_schema,
            "simulated": self.simulated,
            "timeout_seconds": self.timeout_seconds,
        }))


@dataclass(frozen=True)
class ExecutionArtifact:
    status: str
    simulated: bool
    specification_hash: str
    raw_output_sha256: str
    result: Mapping[str, Any]
    exit_code: int
    seed: int
    command: tuple[str, ...]
    stderr_sha256: str = ""
    receipt_sha256: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "simulated": self.simulated,
            "specification_hash": self.specification_hash,
            "raw_output_sha256": self.raw_output_sha256, "result": dict(self.result),
            "exit_code": self.exit_code, "seed": self.seed, "command": list(self.command),
            "stderr_sha256": self.stderr_sha256, "receipt_sha256": self.receipt_sha256,
        }


def _schema_valid(result: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    required = schema.get("required", [])
    return schema.get("type", "object") == "object" and all(key in result for key in required)


def artifact_is_accepted(*, spec: ExecutionSpec, artifact: Mapping[str, Any]) -> bool:
    """Accept only an artifact proving every declared seed ran successfully."""
    result = artifact.get("result")
    if not isinstance(result, Mapping) or not _schema_valid(result, spec.result_schema):
        return False
    runs = result.get("runs")
    if not isinstance(runs, list) or len(runs) != len(spec.seeds):
        return False
    observed_seeds = []
    for run in runs:
        if not isinstance(run, Mapping) or run.get("status") != "completed":
            return False
        digest = run.get("raw_output_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return False
        observed_seeds.append(run.get("seed"))
    return (
        tuple(observed_seeds) == spec.seeds
        and artifact.get("status") == "completed"
        and artifact.get("simulated") is False
        and artifact.get("specification_hash") == spec.specification_hash
        and artifact.get("exit_code") == 0
    )


def run_execution(spec: ExecutionSpec, output_dir: str | os.PathLike[str]) -> ExecutionArtifact:
    """Run a real subprocess once per seed and persist raw output plus receipt."""
    if spec.data_rights is not None:
        spec.data_rights.assert_allowed()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for seed in spec.seeds:
        env = os.environ.copy()
        env["VIBE_RESEARCH_SEED"] = str(seed)
        started = time.time()
        try:
            completed = subprocess.run(spec.command, cwd=root, env=env, capture_output=True,
                                       text=True, timeout=spec.timeout_seconds, check=False)
            status = "completed" if completed.returncode == 0 else "failed"
            stdout = completed.stdout
            stderr = completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else "timeout"
            status, exit_code = "timeout", 124
        raw_path = root / f"raw-{seed}.json"
        raw = {"seed": seed, "stdout": stdout, "stderr": stderr, "exit_code": exit_code}
        raw_path.write_bytes(_canonical(raw))
        records.append({"seed": seed, "status": status, "raw_output": str(raw_path),
                        "raw_output_sha256": _sha256_bytes(raw_path.read_bytes()),
                        "stderr_sha256": _sha256_bytes(stderr.encode()),
                        "duration_ms": round((time.time() - started) * 1000)})
        if status != "completed":
            return _persist_artifact(spec, root, status, seed, records[-1], exit_code, {})
    result = {"runs": records}
    return _persist_artifact(spec, root, "completed", spec.seeds[-1], records[-1], 0, result)


def _persist_artifact(spec: ExecutionSpec, root: Path, status: str, seed: int,
                      record: Mapping[str, Any], exit_code: int,
                      result: Mapping[str, Any]) -> ExecutionArtifact:
    artifact = ExecutionArtifact(status=status, simulated=False,
        specification_hash=spec.specification_hash,
        raw_output_sha256=str(record["raw_output_sha256"]), result=result,
        exit_code=exit_code, seed=seed, command=spec.command,
        stderr_sha256=str(record.get("stderr_sha256", "")))
    payload = artifact.as_dict()
    receipt = root / "execution-receipt.json"
    receipt.write_bytes(_canonical(payload))
    return ExecutionArtifact(**{**payload, "receipt_sha256": _sha256_bytes(receipt.read_bytes())})


def derive_numeric_registry(artifact: ExecutionArtifact, formulas: Mapping[str, str]) -> dict[str, Any]:
    if artifact.status != "completed" or artifact.simulated or not formulas:
        raise ValueError("numeric registry requires a completed real artifact and formulas")
    return {"artifact_sha256": artifact.receipt_sha256, "values": dict(artifact.result),
            "formulas": dict(formulas), "lineage_complete": True}


def environment_fingerprint() -> dict[str, str]:
    return {"python": sys.version.split()[0], "platform": platform.platform()}
