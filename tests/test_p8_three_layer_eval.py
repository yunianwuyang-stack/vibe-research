"""P8.2 three-layer internal eval tests."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "harness" / "v2" / "scripts" / "p8_three_layer_eval.py"


def _load():
    spec = importlib.util.spec_from_file_location("p8_three_layer_eval", MODULE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # scripts dir for worker import
    sys.path.insert(0, str(MODULE.parent))
    spec.loader.exec_module(mod)
    return mod


def test_builder_view_has_no_gold_fields():
    mod = _load()
    view = mod.builder_cannot_read_gold(ROOT)
    assert view["gold_readable"] is False
    assert view["gold_fields_present_in_builder_view"] is False
    assert all("expected_verdict" not in c for c in view["public_cases"])
    assert all("gold_sha256" not in c for c in view["public_cases"])
    assert len(view["public_case_ids"]) >= 8


def test_three_layers_pass_and_tier_honest(tmp_path: Path):
    receipt = tmp_path / "three-layer.json"
    proc = subprocess.run(
        [sys.executable, str(MODULE), "--receipt", str(receipt), "--root", str(ROOT)],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["status"] == "PASS"
    assert data["evaluation_tier"] == "INTERNAL_HELDOUT"
    assert data["external_status"] == "PRIVATE_EVAL_NOT_AVAILABLE"
    assert set(data["layers_present"]) == {
        "L1_DETERMINISTIC_CONTRACTS",
        "L2_PUBLIC_REGRESSION",
        "L3_INTERNAL_HELDOUT",
    }
    assert data["layers"]["L1_DETERMINISTIC_CONTRACTS"]["status"] == "PASS"
    assert data["layers"]["L2_PUBLIC_REGRESSION"]["status"] == "PASS"
    assert data["layers"]["L2_PUBLIC_REGRESSION"]["gold_used"] is False
    assert data["layers"]["L2_PUBLIC_REGRESSION"]["evaluation_tier"] == "PUBLIC"
    l3 = data["layers"]["L3_INTERNAL_HELDOUT"]
    assert l3["status"] == "PASS"
    assert l3["gold_exposed_in_return"] is False
    assert l3["metrics"]["critical_sensitivity"] == 1.0
    assert l3["metrics"]["abstention_preserved"] is True
    # Gold values must not leak into top-level receipt JSON text
    raw = receipt.read_text(encoding="utf-8")
    assert "frozen-gold-" not in raw
    assert "expected_verdict" not in raw


def test_public_case_view_strips_gold():
    mod = _load()
    row = {
        "case_id": "RT-FAKE-DOI",
        "class": "fake_doi",
        "tier": "INTERNAL_HELDOUT",
        "expected_verdict": "block",
        "gold_sha256": "frozen-gold-rt-fake-doi",
    }
    pub = mod.public_case_view(row)
    assert pub == {
        "case_id": "RT-FAKE-DOI",
        "class": "fake_doi",
        "tier": "INTERNAL_HELDOUT",
    }
