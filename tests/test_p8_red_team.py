"""P8.4 red-team critical sensitivity and class coverage tests."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "harness" / "v2" / "scripts" / "p8_red_team.py"


def _load():
    spec = importlib.util.spec_from_file_location("p8_red_team", MODULE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(MODULE.parent))
    spec.loader.exec_module(mod)
    return mod


def test_all_critical_classes_blocked_with_sensitivity_one():
    mod = _load()
    result = mod.run_red_team(ROOT)
    assert result["status"] == "PASS"
    assert result["metrics"]["critical_sensitivity"] == 1.0
    assert result["metrics"]["specificity"] >= 0.8
    assert result["metrics"]["coverage"] >= 0.8
    assert result["metrics"]["abstention_preserved"] is True
    assert result["metrics"]["fn_block"] == 0
    classes = {c["class"] for c in result["per_case"] if c["case_id"].startswith("RT-")}
    for required in mod.CRITICAL_CLASSES:
        assert required in classes


def test_each_red_team_case_is_correct():
    mod = _load()
    result = mod.run_red_team(ROOT)
    for row in result["per_case"]:
        if row["case_id"].startswith("RT-"):
            assert row["predicted"] == "block"
            assert row["correct"] is True


def test_cli_receipt(tmp_path: Path):
    receipt = tmp_path / "rt.json"
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--receipt", str(receipt), "--root", str(ROOT)],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["schema"] == "harness-v2-p8-red-team/1"
    assert data["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
