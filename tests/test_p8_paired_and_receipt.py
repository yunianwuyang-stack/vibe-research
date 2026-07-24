"""Tests for P8.5 paired calibration and P8.6 receipt completeness."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRED = ROOT / "harness" / "v2" / "scripts" / "p8_paired_calibration.py"
COMPLETE = ROOT / "harness" / "v2" / "scripts" / "p8_receipt_completeness.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    spec.loader.exec_module(mod)
    return mod


def test_paired_improves_without_regression():
    mod = _load(PAIRED, "p8_paired_calibration")
    result = mod.run_paired_and_calibration(ROOT)
    assert result["status"] == "PASS"
    assert result["paired_comparison"]["regressed"] == 0
    assert result["paired_comparison"]["improved"] >= 1
    assert result["judge_calibration"]["agreement"] == 1.0
    assert result["judge_calibration"]["false_positive_rate"] == 0.0
    assert result["judge_calibration"]["false_negative_rate"] == 0.0
    assert result["judge_calibration"]["abstention_preserved"] is True
    assert result["deterministic_gate"]["soft_pass_overridden_to_block"] is True


def test_complete_receipt_has_required_fields_and_anti_extrapolation():
    mod = _load(COMPLETE, "p8_receipt_completeness")
    result = mod.build_complete_receipt(ROOT)
    assert result["status"] == "PASS"
    for field in mod.REQUIRED_RECEIPT_FIELDS:
        assert field in result and result[field] not in (None, "")
    assert result["extrapolation_forbidden"] is True
    assert "Do not extrapolate" in result["scope_statement"]
    assert result["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
    assert result["evaluation_tier"] == "INTERNAL_HELDOUT"


def test_cli_scripts(tmp_path: Path):
    for script in (PAIRED, COMPLETE):
        receipt = tmp_path / (script.stem + ".json")
        proc = subprocess.run(
            [sys.executable, str(script), "--receipt", str(receipt), "--root", str(ROOT)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert proc.returncode == 0, f"{script.name}: {proc.stderr}"
        assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "PASS"
