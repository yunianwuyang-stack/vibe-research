from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import psutil
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.v2.scripts.lanes import (
    LANE_PRIORITY,
    LaneConfigurationError,
    chunk_nodeids,
    run_lanes,
    windows_command_length,
)
from harness.v2.scripts.supervisor import SupervisorConfig, run_supervised


MARKERS = """
[pytest]
testpaths = tests
markers =
    unit: unit
    contract: contract
    integration: integration
    live_provider: live provider
    desktop: desktop
    release: release
    private_eval: private evaluation
""".strip()


def _workspace(tmp_path: Path, source: str) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    tests = workspace / "tests"
    tests.mkdir(parents=True)
    (workspace / "pytest.ini").write_text(MARKERS + "\n", encoding="utf-8")
    (tests / "test_fixture.py").write_text(source, encoding="utf-8")
    return workspace, tmp_path / "evidence"


def _run(workspace: Path, evidence: Path, **overrides):
    options = {
        "chunk_max_items": 2,
        "collect_deadline_seconds": 15.0,
        "lane_deadline_seconds": 8.0,
        "heartbeat_seconds": 0.05,
        "graceful_shutdown_seconds": 0.05,
        "stdout_limit_bytes": 512 * 1024,
        "stderr_limit_bytes": 512 * 1024,
    }
    options.update(overrides)
    return run_lanes(workspace, evidence, **options)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _capability_preflight(
    tmp_path: Path,
    workspace: Path,
    source_snapshot_sha256: str,
    *,
    capability: str = "gpu",
) -> Path:
    directory = tmp_path / "preflight"
    directory.mkdir(exist_ok=True)
    supervisor_path = directory / "supervisor.json"
    run_supervised(
        SupervisorConfig(
            argv=[sys.executable, "-c", "print('capability-disabled')"],
            cwd=workspace,
            allowed_cwd_roots=[workspace],
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            allowed_env_keys=["PYTHONDONTWRITEBYTECODE"],
            deadline_seconds=5,
            heartbeat_seconds=0.05,
        ),
        receipt_path=supervisor_path,
    )
    receipt_path = directory / "capability.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schema": "harness-v2-capability-preflight-receipt/1",
                "verdict": "VERIFIED_PASS",
                "workspace_root": str(workspace.resolve()),
                "source_snapshot_sha256": source_snapshot_sha256,
                "disabled_capabilities": [
                    {"id": capability, "status": "disabled"}
                ],
                "supervisor_receipt": {
                    "path": str(supervisor_path),
                    "sha256": _sha256(supervisor_path),
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt_path


def test_real_dynamic_collection_marker_priority_chunking_and_new_test(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
import pytest

@pytest.mark.unit
def test_unit():
    pass

@pytest.mark.contract
@pytest.mark.integration
def test_risk_priority():
    pass

@pytest.mark.unit
@pytest.mark.live_provider
def test_highest_priority():
    pass

def test_unmarked():
    pass
""".strip()
        + "\n",
    )
    first = _run(workspace, evidence, chunk_max_items=1)

    assert first["verdict"] == "PASS"
    assert first["initial_collection"]["item_count"] == 4
    assert first["lane_priority"] == list(LANE_PRIORITY)
    assert first["lanes"]["live_provider"]["nodeid_count"] == 1
    assert first["lanes"]["integration"]["nodeid_count"] == 1
    assert first["lanes"]["contract"]["nodeid_count"] == 0
    assert first["lanes"]["unit"]["nodeid_count"] == 1
    assert first["lanes"]["unmarked"]["nodeid_count"] == 1
    assert first["coverage"]["full_coverage"] is True
    assert first["coverage"]["no_duplicates"] is True
    flattened = [nodeid for command in first["commands"] for nodeid in command["nodeids"]]
    collected = [item["nodeid"] for item in first["initial_collection"]["items"]]
    assert sorted(flattened) == sorted(collected)
    assert len(flattened) == len(set(flattened)) == 4
    assert all(command["nodeid_count"] == 1 for command in first["commands"])
    assert all(command["raw_stream_artifacts_valid"] for command in first["commands"])
    assert all(command["junit_valid"] for command in first["commands"])
    assert not (workspace / ".pytest_cache").exists()
    assert not list(workspace.rglob("__pycache__"))

    (workspace / "tests" / "test_added.py").write_text(
        "import pytest\n@pytest.mark.desktop\ndef test_added_dynamically():\n    pass\n",
        encoding="utf-8",
    )
    second = _run(workspace, evidence, chunk_max_items=1, resume=True)

    assert second["verdict"] == "PASS"
    assert second["initial_collection"]["item_count"] == 5
    assert second["collect_sha256"] != first["collect_sha256"]
    assert second["lanes"]["desktop"]["nodeid_count"] == 1
    assert second["commands_executed"] == 5
    assert second["commands_resumed"] == 0


def test_redacted_stream_artifact_is_bound_without_persisting_secret(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
import pytest

@pytest.mark.parametrize("value", ["Bearer ABCDEFGHI"], ids=["Bearer ABCDEFGHI"])
def test_secret_like_parameter_id(value):
    assert value
""".strip()
        + "\n",
    )

    manifest = _run(workspace, evidence)
    record = manifest["commands"][0]
    stdout_path = Path(record["artifacts"]["stdout"]["path"])
    receipt = json.loads(
        Path(record["artifacts"]["receipt"]["path"]).read_text(encoding="utf-8")
    )
    persisted = stdout_path.read_text(encoding="utf-8")

    assert manifest["verdict"] == "PASS"
    assert record["raw_stream_artifacts_valid"] is True
    assert "[REDACTED]" in persisted
    assert "ABCDEFGHI" not in persisted
    assert _sha256(stdout_path) == receipt["stdout"]["redacted_sha256"]
    assert receipt["stdout"]["raw_sha256"] != receipt["stdout"]["redacted_sha256"]


@pytest.mark.parametrize(
    "source",
    [
        "def test_broken(:\n    pass\n",
        "# deliberately no tests\n",
    ],
)
def test_collection_error_or_empty_collection_cannot_pass(
    tmp_path: Path, source: str
) -> None:
    workspace, evidence = _workspace(tmp_path, source)
    manifest = _run(workspace, evidence)

    assert manifest["verdict"] == "FAIL"
    assert manifest["initial_collection"]["passed"] is False
    assert manifest["commands_planned"] == 0
    assert manifest["commands_executed"] == 0
    assert manifest["coverage"]["full_coverage"] is False


def test_a_failing_high_risk_lane_does_not_prevent_later_lane_execution(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path
import pytest

@pytest.mark.live_provider
def test_fails_first():
    assert False, "intentional"

@pytest.mark.unit
def test_still_runs():
    Path("continued.txt").write_text("ran", encoding="utf-8")
""".strip()
        + "\n",
    )
    manifest = _run(workspace, evidence, chunk_max_items=1)

    assert manifest["verdict"] == "FAIL"
    assert (workspace / "continued.txt").read_text(encoding="utf-8") == "ran"
    records = {record["lane"]: record for record in manifest["commands"]}
    assert records["live_provider"]["exit_code"] == 1
    assert records["live_provider"]["control_plane_ok"] is True
    assert records["live_provider"]["passed"] is False
    assert records["unit"]["passed"] is True
    assert manifest["commands_executed"] == 2


def test_timeout_cleans_owned_child_and_fails_closed(tmp_path: Path) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest

@pytest.mark.live_provider
def test_timeout_tree():
    child_code = (
        "import signal,time;"
        "signal.signal(signal.SIGINT,signal.SIG_IGN);"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "signal.signal(getattr(signal,'SIGBREAK',signal.SIGTERM),signal.SIG_IGN);"
        "time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", child_code])
    Path("child.pid").write_text(str(child.pid), encoding="ascii")
    time.sleep(60)
""".strip()
        + "\n",
    )
    manifest = _run(
        workspace,
        evidence,
        lane_deadline_seconds=0.65,
        collect_deadline_seconds=10.0,
        heartbeat_seconds=0.03,
    )

    assert manifest["verdict"] == "FAIL"
    record = manifest["commands"][0]
    assert record["termination_reason"] == "TIMED_OUT"
    assert record["orphan_count"] == 0
    assert record["identity_match"] is True
    assert record["control_plane_ok"] is False
    receipt_path = Path(record["artifacts"]["receipt"]["path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert len(receipt["pid_tree"]) >= 2
    child_pid = int((workspace / "child.pid").read_text(encoding="ascii"))
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and psutil.pid_exists(child_pid):
        time.sleep(0.02)
    assert not psutil.pid_exists(child_pid)


def test_resume_requires_all_bindings_and_valid_raw_artifact_hashes(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path
import pytest

@pytest.mark.unit
def test_count_execution():
    path = Path("count.txt")
    value = int(path.read_text(encoding="ascii")) if path.exists() else 0
    path.write_text(str(value + 1), encoding="ascii")
    print("stable output")
""".strip()
        + "\n",
    )
    backend = workspace / "backend"
    backend.mkdir()
    product_source = backend / "product.py"
    product_source.write_text("VALUE = 1\n", encoding="utf-8", newline="\n")
    first = _run(workspace, evidence)
    assert first["verdict"] == "PASS"
    assert (workspace / "count.txt").read_text(encoding="ascii") == "1"

    resumed = _run(workspace, evidence, resume=True)
    assert resumed["verdict"] == "PASS"
    assert resumed["commands_executed"] == 0
    assert resumed["commands_resumed"] == 1
    assert resumed["commands"][0]["resume_status"] == "skipped_valid_receipt"
    assert (workspace / "count.txt").read_text(encoding="ascii") == "1"

    product_source.write_text("VALUE = 2\n", encoding="utf-8", newline="\n")
    source_rerun = _run(workspace, evidence, resume=True)
    assert source_rerun["verdict"] == "PASS"
    assert source_rerun["commands_executed"] == 1
    assert source_rerun["commands_resumed"] == 0
    assert (workspace / "count.txt").read_text(encoding="ascii") == "2"

    stdout_path = Path(source_rerun["commands"][0]["artifacts"]["stdout"]["path"])
    stdout_path.write_bytes(stdout_path.read_bytes() + b"tampered")
    assert (
        _sha256(stdout_path)
        != source_rerun["commands"][0]["artifacts"]["stdout"]["sha256"]
    )

    rerun = _run(workspace, evidence, resume=True)
    assert rerun["verdict"] == "PASS"
    assert rerun["commands_executed"] == 1
    assert rerun["commands_resumed"] == 0
    assert (workspace / "count.txt").read_text(encoding="ascii") == "3"


def test_snapshot_covers_product_locks_config_and_harness_and_detects_run_drift(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path
import pytest

@pytest.mark.unit
def test_mutates_product_source():
    Path("backend/product.py").write_text("VALUE = 2\\n", encoding="utf-8")
""".strip()
        + "\n",
    )
    files = {
        "backend/product.py": "VALUE = 1\n",
        "frontend/src/app.ts": "export const value = 1;\n",
        "scripts/check.ps1": "Write-Output ok\n",
        "tools/check.py": "VALUE = 1\n",
        "build/installer.nsh": "; installer\n",
        "harness/v2/scripts/checker.py": "VALUE = 1\n",
        "package-lock.json": "{}\n",
        "pyproject.toml": "[tool.example]\nvalue = 1\n",
        "requirements-prod.txt": "pytest==8.3.5\n",
    }
    for relative, content in files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    manifest = _run(workspace, evidence)
    indexed = {
        item["path"]: item["category"] for item in manifest["input_snapshot"]["files"]
    }
    assert manifest["verdict"] == "FAIL"
    assert manifest["unexpected_collection_drift"] is True
    assert manifest["collection_drift"]["initial_input_sha256"] != manifest[
        "collection_drift"
    ]["final_input_sha256"]
    assert indexed["backend/product.py"] == "product_source"
    assert indexed["frontend/src/app.ts"] == "product_source"
    assert indexed["package-lock.json"] == "dependency_lock"
    assert indexed["requirements-prod.txt"] == "dependency_lock"
    assert indexed["pyproject.toml"] == "key_config"
    assert indexed["harness/v2/scripts/checker.py"] == "harness_checker"


def test_default_skip_is_not_qualification_success(tmp_path: Path) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        "import pytest\n@pytest.mark.skip(reason='disabled')\ndef test_skip(): pass\n",
    )
    manifest = _run(workspace, evidence)
    record = manifest["commands"][0]

    assert manifest["verdict"] == "FAIL"
    assert record["outcomes_valid"] is True
    assert record["observed_skips"] == ["tests/test_fixture.py::test_skip"]
    assert record["unexpected_skips"] == ["tests/test_fixture.py::test_skip"]
    assert record["passed"] is False


@pytest.mark.parametrize(
    ("assertion", "field"),
    [("False", "xfailed_count"), ("True", "xpassed_count")],
)
def test_xfail_and_xpass_are_never_qualification_success(
    tmp_path: Path, assertion: str, field: str
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        (
            "import pytest\n"
            "@pytest.mark.xfail(reason='known')\n"
            f"def test_xstatus(): assert {assertion}\n"
        ),
    )
    manifest = _run(workspace, evidence)
    record = manifest["commands"][0]

    assert manifest["verdict"] == "FAIL"
    assert record[field] == 1
    assert record["unexpected_xfail_count"] == 1
    assert record["passed"] is False


def test_expected_skip_requires_current_bound_preflight(tmp_path: Path) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        "import pytest\n@pytest.mark.skip(reason='no gpu')\ndef test_disabled(): pass\n",
    )
    nodeid = "tests/test_fixture.py::test_disabled"
    baseline = _run(workspace, evidence)
    preflight = _capability_preflight(
        tmp_path, workspace, baseline["source_snapshot_sha256"]
    )

    qualified = _run(
        workspace,
        evidence,
        expected_skips={"gpu": [nodeid]},
        preflight_receipt_path=preflight,
    )
    assert qualified["verdict"] == "PASS"
    assert qualified["commands"][0]["expected_skips"] == [nodeid]
    assert qualified["commands"][0]["skip_policy_valid"] is True

    payload = json.loads(preflight.read_text(encoding="utf-8"))
    payload["source_snapshot_sha256"] = "0" * 64
    preflight.write_text(json.dumps(payload) + "\n", encoding="utf-8", newline="\n")
    stale = _run(
        workspace,
        evidence,
        expected_skips={"gpu": [nodeid]},
        preflight_receipt_path=preflight,
    )
    assert stale["verdict"] == "FAIL"
    assert "preflight_source_snapshot_stale" in stale["skip_policy"]["errors"]

    preflight = _capability_preflight(
        tmp_path, workspace, baseline["source_snapshot_sha256"]
    )
    supervisor_path = Path(
        json.loads(preflight.read_text(encoding="utf-8"))["supervisor_receipt"]["path"]
    )
    supervisor_path.write_bytes(supervisor_path.read_bytes() + b"tampered")
    tampered = _run(
        workspace,
        evidence,
        expected_skips={"gpu": [nodeid]},
        preflight_receipt_path=preflight,
    )
    assert tampered["verdict"] == "FAIL"
    assert "preflight_supervisor_binding_invalid" in tampered["skip_policy"]["errors"]

    with pytest.raises(LaneConfigurationError):
        _run(
            workspace,
            evidence,
            expected_skips={"gpu": [nodeid]},
            preflight_receipt_path=tmp_path / "missing-preflight.json",
        )


def test_dynamic_high_risk_markers_are_downgraded_but_explicit_markers_remain(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        "import pytest\n@pytest.mark.desktop\ndef test_explicit(): pass\n",
    )
    (workspace / "tests" / "test_desktop_named.py").write_text(
        "def test_dynamic_name_only(): pass\n", encoding="utf-8", newline="\n"
    )
    (workspace / "tests" / "conftest.py").write_text(
        """
import pytest

def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.desktop)
""".strip()
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = _run(workspace, evidence)
    items = {
        item["nodeid"]: item for item in manifest["initial_collection"]["items"]
    }

    assert manifest["verdict"] == "PASS"
    assert items["tests/test_fixture.py::test_explicit"]["lane"] == "desktop"
    dynamic = items["tests/test_desktop_named.py::test_dynamic_name_only"]
    assert dynamic["requested_lane"] == "desktop"
    assert dynamic["lane"] == "integration"
    assert dynamic["lane_proof"] == "downgraded_dynamic_high_risk_marker"


def test_lane_evidence_binds_raw_artifacts_and_tamper_forces_resume_rerun(
    tmp_path: Path,
) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path

def test_count():
    path = Path("count.txt")
    value = int(path.read_text()) if path.exists() else 0
    path.write_text(str(value + 1))
""".strip()
        + "\n",
    )
    first = _run(workspace, evidence)
    record = first["commands"][0]
    artifacts = record["artifacts"]
    progress = json.loads(Path(artifacts["progress"]["path"]).read_text(encoding="utf-8"))
    lane_evidence = json.loads(
        Path(artifacts["evidence_manifest"]["path"]).read_text(encoding="utf-8")
    )

    assert progress["state"] == "FINALIZED"
    assert progress["receipt_sha256"] == _sha256(Path(artifacts["receipt"]["path"]))
    assert lane_evidence["supervisor_binding"]["finalized_receipt_hash_bound"] is True
    assert set(lane_evidence["artifacts"]) == {
        "receipt",
        "progress",
        "junit",
        "durations",
        "stdout",
        "stderr",
        "outcomes",
    }

    evidence_path = Path(artifacts["evidence_manifest"]["path"])
    evidence_path.write_bytes(evidence_path.read_bytes() + b" ")
    second = _run(workspace, evidence, resume=True)
    assert second["commands_executed"] == 1
    assert (workspace / "count.txt").read_text() == "2"

    progress_path = Path(second["commands"][0]["artifacts"]["progress"]["path"])
    progress_path.write_bytes(progress_path.read_bytes() + b" ")
    third = _run(workspace, evidence, resume=True)
    assert third["commands_executed"] == 1
    assert (workspace / "count.txt").read_text() == "3"


def test_outcome_plugin_tamper_during_lane_fails_closed(tmp_path: Path) -> None:
    workspace, evidence = _workspace(
        tmp_path,
        """
from pathlib import Path
import sys
import pytest

@pytest.mark.live_provider
def test_tamper_plugin():
    Path(sys.modules["__main__"].__file__).write_text("raise SystemExit(0)\\n", encoding="utf-8")

@pytest.mark.unit
def test_later_lane():
    Path("later.txt").write_text("ran")
""".strip()
        + "\n",
    )
    manifest = _run(workspace, evidence, chunk_max_items=1)

    assert manifest["verdict"] == "FAIL"
    assert manifest["commands"][0]["outcome_plugin_valid"] is False
    assert not (workspace / "later.txt").exists()


def test_windows_chunk_helper_honors_item_and_rendered_command_bounds() -> None:
    nodeids = [f"tests/test_long.py::test_{index}_" + "x" * 20 for index in range(7)]
    base = ["C:\\Python\\python.exe", "-m", "pytest"]
    limit = windows_command_length([*base, "--", *nodeids[:2]])
    chunks = chunk_nodeids(
        nodeids,
        base_argv=base,
        max_items=3,
        windows_limit=limit,
        is_windows=True,
    )

    assert [nodeid for chunk in chunks for nodeid in chunk] == nodeids
    assert all(len(chunk) <= 2 for chunk in chunks)
    assert all(
        windows_command_length([*base, "--", *chunk]) <= limit for chunk in chunks
    )
