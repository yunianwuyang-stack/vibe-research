from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "harness" / "v2" / "scripts" / "p0_qualification.py"
SPEC = importlib.util.spec_from_file_location("p0_qualification", MODULE_PATH)
assert SPEC and SPEC.loader
p0_qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p0_qualification)


def test_real_p0_evidence_derives_terminal_pass() -> None:
    provenance, qualification = p0_qualification.build(ROOT)
    assert provenance["verdict"] == "VERIFIED_PASS"
    assert provenance["coverage"] == {
        "tasks_total": 6,
        "tasks_verified": 6,
        "artifact_decision_coverage": 1.0,
        "unknown_count": 0,
    }
    assert qualification["terminal_state"] == "PASS"
    assert [row["requirement_id"] for row in qualification["requirements"]] == list(
        p0_qualification.P0_REQUIREMENTS
    )
    assert all(row["state"] == "VERIFIED_PASS" for row in qualification["requirements"])


def test_tampered_receipt_fails_closed(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"status": "BLOCKED"}), encoding="utf-8")
    with pytest.raises(p0_qualification.QualificationError, match="non-PASS"):
        p0_qualification._validate_receipt(tmp_path, "REQ-P0-01", "receipt.json")


def test_preflight_requires_goal_agent_and_product_backend_classification(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(
        json.dumps(
            {
                "qualification": {
                    "goal_agents_excluded": True,
                    "echo_health_fake_excluded": True,
                },
                "backend_evidence": [{"classification": "product_broker"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(p0_qualification.QualificationError, match="distinguish"):
        p0_qualification._validate_receipt(tmp_path, "REQ-P0-06", "preflight.json")


def test_artifact_verifier_rejects_license_scope_drift(tmp_path: Path) -> None:
    root = tmp_path
    contract_dir = root / "harness/v2/contracts"
    provenance_dir = root / "harness/v2/provenance"
    contract_dir.mkdir(parents=True)
    provenance_dir.mkdir(parents=True)
    decision = {
        "decision_id": p0_qualification.ORIGINAL_DECISION_ID,
        "status": "verified",
        "reuse_mode": "original_implementation",
        "license_scope_hash": "a" * 64,
    }
    (provenance_dir / "decisions.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    for index, requirement_id in enumerate(p0_qualification.P0_REQUIREMENTS, start=1):
        contract = {
            "id": f"P0-{index}",
            "requirement_ids": [requirement_id],
            "allowed_paths": [f"artifact-{index}"],
            "source_decision_ids": [],
            "reuse_mode": "original_implementation",
            "license_scope_hash": "b" * 64 if index == 1 else "a" * 64,
        }
        (contract_dir / f"P0-{index}.json").write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(p0_qualification.QualificationError, match="license scope hash drift"):
        p0_qualification._verify_artifact_decisions(root)
