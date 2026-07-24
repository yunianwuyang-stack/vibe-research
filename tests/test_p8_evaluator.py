from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "harness" / "v2" / "scripts" / "p8_evaluator.py"
spec = importlib.util.spec_from_file_location("p8_evaluator", MODULE)
assert spec and spec.loader
p8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p8)


def test_manifest_is_internal_and_denies_builder_gold_access():
    manifest = p8.build_manifest(ROOT)
    assert manifest["tier"] == "INTERNAL_HELDOUT"
    assert manifest["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
    assert manifest["gold_access"]["builder_can_read_gold"] is False
    assert len(manifest["case_ids"]) == 8


def test_external_sealed_requires_independent_signature():
    policy = p8.load_policy(ROOT)
    registration = {field: "registered" for field in p8.REQUIRED_FIELDS}
    registration.update({"tier": "EXTERNAL_SEALED", "alpha": 0.05, "power": 0.8})
    with pytest.raises(ValueError, match="signed pack"):
        p8.validate_registration(registration, policy=policy)


def test_deterministic_gate_rejects_critical_sensitivity_failure():
    policy = p8.load_policy(ROOT)
    result = {
        "case_id": "RT-FAKE-DOI",
        "pack_hash": "a" * 64,
        "checker_hash": "b" * 64,
        "environment_hash": "c" * 64,
        "denominator": 8,
        "metrics": {"critical_sensitivity": 0.875, "specificity": 1.0, "coverage": 1.0},
        "verdict": "pass",
    }
    assert p8.evaluate_result(result, policy=policy)["verdict"] == "block"


def test_empty_evaluation_cannot_pass():
    policy = p8.load_policy(ROOT)
    result = {
        "case_id": "RT-FAKE-DOI",
        "pack_hash": "a" * 64,
        "checker_hash": "b" * 64,
        "environment_hash": "c" * 64,
        "denominator": 0,
        "metrics": {},
        "verdict": "pass",
    }
    with pytest.raises(ValueError, match="empty evaluation"):
        p8.evaluate_result(result, policy=policy)
