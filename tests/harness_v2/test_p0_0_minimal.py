from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "harness" / "v2" / "p0_0_minimal.py"


def test_p0_0_checker_passes_and_writes_durable_artifacts(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (ROOT / "harness" / "v2" / "state" / "current.json").exists()
    checkpoint = json.loads(
        (ROOT / "harness" / "v2" / "checkpoints" / "P0.0.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["status"] == "PASS"
    assert checkpoint["next_action"].startswith("read ")


def test_p0_0_failure_injection_is_fail_closed():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--inject-failure"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    checkpoint = json.loads(
        (ROOT / "harness" / "v2" / "checkpoints" / "P0.0.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["status"] == "CHECKPOINTED"
    assert checkpoint["blocker"] == "deterministic checker failure"
