"""P8.1 isolated reviewer panel: distinct contexts, no gold, cold public cases."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "harness" / "v2" / "scripts" / "p8_reviewer_worker.py"
RUNTIME = ROOT / "harness" / "v2" / "scripts" / "p8_runtime_evaluator.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_worker_strips_gold_and_blocks_fake_doi(tmp_path: Path) -> None:
    payload = {
        "case_id": "RT-FAKE-DOI",
        "class": "fake_doi",
        "tier": "INTERNAL_HELDOUT",
        "expected_verdict": "pass",  # poisoned gold must be ignored
        "generator_summary": "everything is fine",
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--role",
            "domain",
            "--context-id",
            "p8-domain",
            "--audit-dir",
            str(tmp_path),
        ],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "P8_GOLD_DIR"},
        timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["verdict"] == "block"
    assert "expected_verdict" not in result.get("inputs", [])
    audit = json.loads((tmp_path / "domain-RT-FAKE-DOI.json").read_text(encoding="utf-8"))
    assert audit["gold_mount_present"] is False
    assert "expected_verdict" in audit["stripped_forbidden_keys"]
    assert audit["generator_summary_present"] is True


def test_worker_refuses_when_gold_mount_present(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["P8_GOLD_DIR"] = str(tmp_path / "gold")
    proc = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--role",
            "security",
            "--context-id",
            "p8-security",
            "--audit-dir",
            str(tmp_path / "audit"),
        ],
        input=json.dumps({"case_id": "RT-LEAK", "class": "data_leakage", "tier": "INTERNAL_HELDOUT"}),
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=10,
    )
    assert proc.returncode == 3
    assert "gold mount" in proc.stderr.lower()


def test_worker_calibration_abstention() -> None:
    worker = _load(WORKER, "p8_reviewer_worker")
    assert worker.decide_verdict({"case_id": "CAL-ABSTAIN", "class": "calibration"}) == "abstain"
    assert worker.decide_verdict({"case_id": "CAL-ACCEPT", "class": "calibration"}) == "pass"
    assert worker.decide_verdict({"case_id": "CAL-REJECT", "class": "calibration"}) == "block"


def test_runtime_panel_six_roles_sensitivity_and_isolation(tmp_path: Path) -> None:
    receipt_path = tmp_path / "runtime-receipt.json"
    proc = subprocess.run(
        [sys.executable, str(RUNTIME), "--receipt", str(receipt_path)],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={k: v for k, v in os.environ.items() if k != "P8_GOLD_DIR"},
    )
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "PASS"
    assert receipt["evaluation_tier"] == "INTERNAL_HELDOUT"
    assert receipt["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
    assert receipt["red_team"]["critical_sensitivity"] == 1.0
    assert receipt["judge_calibration"]["agreement"] == 1.0
    assert receipt["judge_calibration"]["abstention_preserved"] is True
    exec_info = receipt["reviewer_execution"]
    assert exec_info["distinct_contexts"] is True
    assert set(exec_info["roles"]) == {
        "domain",
        "method",
        "statistics",
        "evidence",
        "writing",
        "security",
    }
    assert exec_info["worker_processes"] == 66  # 6 roles * 11 cases
    assert receipt["gold_access_audit"]["all_workers_without_gold_mount"] is True
