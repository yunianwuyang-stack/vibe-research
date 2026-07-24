import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.v2.scripts.p0_bootstrap import budget_violations
from harness.v2.scripts.task_events import append_event, read_events, summarize_events


def test_hash_chained_events_derive_budget_counters(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("evidence", encoding="utf-8")
    ledger = tmp_path / "task.jsonl"

    append_event(ledger, "P0.1-requirements-coverage", "patch", "apply_patch", tmp_path, ["artifact.txt"])
    append_event(ledger, "P0.1-requirements-coverage", "write_or_exec", "validate", tmp_path, [])

    summary = summarize_events(ledger, "P0.1-requirements-coverage")
    assert summary == {
        "event_count": 2,
        "total_tool_calls": 2,
        "read_only_tool_calls": 0,
        "write_or_exec_tool_calls": 2,
        "first_patch_tool_call": 1,
        "last_event_hash": summary["last_event_hash"],
    }
    assert not budget_violations(summary)


def test_tampered_event_ledger_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("evidence", encoding="utf-8")
    ledger = tmp_path / "task.jsonl"
    append_event(ledger, "P0.1-requirements-coverage", "patch", "apply_patch", tmp_path, ["artifact.txt"])

    event = json.loads(ledger.read_text(encoding="utf-8"))
    event["kind"] = "read_only"
    ledger.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        read_events(ledger, "P0.1-requirements-coverage")


def test_stale_patch_artifact_fails_closed_before_projection(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("accepted preimage", encoding="utf-8")
    ledger = tmp_path / "task.jsonl"
    append_event(ledger, "P0.5-stale-ledger-detection", "patch", "apply_patch", tmp_path, ["artifact.txt"])
    artifact.write_text("changed after event", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        summarize_events(ledger, "P0.5-stale-ledger-detection", tmp_path)


def test_checkpoint_event_is_replayable_after_real_child_exit(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("durable evidence", encoding="utf-8")
    ledger = tmp_path / "task.jsonl"
    workspace = Path(__file__).resolve().parents[2]
    code = (
        "import os; from pathlib import Path; "
        "from harness.v2.scripts.task_events import append_event; "
        f"append_event(Path({str(ledger)!r}), 'P0.2-checkpoint-durability', 'patch', 'apply_patch', Path({str(tmp_path)!r}), ['artifact.txt']); "
        "os._exit(0)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    summary = summarize_events(ledger, "P0.2-checkpoint-durability")
    assert summary["event_count"] == 1
    assert summary["first_patch_tool_call"] == 1
