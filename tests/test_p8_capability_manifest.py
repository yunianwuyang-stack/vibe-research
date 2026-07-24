"""P8.3 EXTERNAL_SEALED honesty and capability manifest private-claim ban."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "harness" / "v2" / "scripts" / "p8_capability_manifest.py"
P8_EVAL = ROOT / "harness" / "v2" / "scripts" / "p8_evaluator.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_missing_pack_records_private_eval_not_available():
    mod = _load(MODULE, "p8_capability_manifest")
    result = mod.build_capability_manifest(ROOT, claimed_capabilities=["INTERNAL_HELDOUT", "panel_isolated"])
    assert result["status"] == "PASS"
    assert result["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
    assert result["private_eval_available"] is False
    assert result["evaluation_tier"] == "INTERNAL_HELDOUT"
    assert result["signed_pack"]["valid"] is False


def test_private_claims_blocked_without_pack():
    mod = _load(MODULE, "p8_capability_manifest")
    result = mod.build_capability_manifest(
        ROOT,
        claimed_capabilities=["INTERNAL_HELDOUT", "external_sealed_verified", "PRIVATE_BENCHMARK"],
    )
    assert result["status"] == "BLOCKED"
    assert any("illegal_private_claims" in f for f in result["failures"])
    assert "external_sealed_verified" in result["illegal_claims_detected"]


def test_valid_signed_pack_enables_external_sealed(tmp_path: Path):
    mod = _load(MODULE, "p8_capability_manifest")
    pack = {
        "pack_id": "ext-pack-1",
        "signature": "a" * 64,
        "signer_id": "independent-os-identity",
        "gold_hash": "b" * 64,
        "created_at": "2026-07-19T00:00:00Z",
    }
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    result = mod.build_capability_manifest(
        ROOT,
        claimed_capabilities=["EXTERNAL_SEALED"],
        pack_path=pack_path,
    )
    assert result["status"] == "PASS"
    assert result["external_status"] == "EXTERNAL_SEALED"
    assert result["private_eval_available"] is True
    assert result["signed_pack"]["valid"] is True


def test_self_signed_pack_rejected(tmp_path: Path):
    mod = _load(MODULE, "p8_capability_manifest")
    h = "c" * 64
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(
        json.dumps(
            {
                "pack_id": "bad",
                "signature": h,
                "signer_id": "same",
                "gold_hash": h,
                "created_at": "2026-07-19T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    result = mod.build_capability_manifest(ROOT, pack_path=pack_path)
    assert result["signed_pack"]["valid"] is False
    assert result["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"


def test_p8_evaluator_registration_still_requires_signed_pack():
    p8 = _load(P8_EVAL, "p8_evaluator")
    policy = p8.load_policy(ROOT)
    registration = {field: "registered" for field in p8.REQUIRED_FIELDS}
    registration.update({"tier": "EXTERNAL_SEALED", "alpha": 0.05, "power": 0.8})
    with pytest.raises(ValueError, match="signed pack"):
        p8.validate_registration(registration, policy=policy)


def test_cli_default_pass(tmp_path: Path):
    receipt = tmp_path / "cap.json"
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--receipt", str(receipt), "--claim", "INTERNAL_HELDOUT"],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
