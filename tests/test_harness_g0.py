from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import g0_runner  # noqa: E402

from bootstrap_contract import (  # noqa: E402
    EXPECTED_FILE_SHA256,
    run_tamper_vectors,
    validate_contract,
    validate_lock,
)
from journal import JournalError, append_event, project, read_events, verify_events  # noqa: E402
from restore_drill import RestoreError, _parse_refs, _restore_refs, restore_and_verify  # noqa: E402
from secret_scan import scan  # noqa: E402
from task_boundary import evaluate_allowed_paths  # noqa: E402
from g0_runner import G0_GATE_SPECS, G0Error, _EvidenceDirectoryGuard, _StagingDirectoryGuard, _assert_safe_evidence_target, _commit_staged_evidence_file, _is_reparse_point, _load_prior_automation_ownership, parse_junit, run_lanes, validate_lane_receipts  # noqa: E402
from source_provenance import evaluate_source_provenance  # noqa: E402
from g0_truth import verify_adjudication  # noqa: E402


CONTRACT = Path(r"D:\科研软件制作\开发指导.bootstrap.json")
LOCK = ROOT / "harness" / "phase-contract.lock"


def test_allowed_paths_reports_sorted_changes_and_outside_violations() -> None:
    result = evaluate_allowed_paths(
        before={"harness/evidence/G0/a.json": "a", "backend/main.py": "b"},
        after={"harness/evidence/G0/a.json": "changed-a", "backend/main.py": "changed-b"},
        allowed=["harness/**"],
    )

    assert result == {
        "verdict": "FAIL",
        "changed_paths": ["backend/main.py", "harness/evidence/G0/a.json"],
        "violations": ["backend/main.py"],
        "numerator": 1,
        "denominator": 2,
    }


def test_allowed_paths_passes_for_changed_and_added_descendants() -> None:
    result = evaluate_allowed_paths(
        before={"harness/evidence/G0/a.json": "a"},
        after={"harness/evidence/G0/a.json": "changed", "harness/reports/new.json": "new"},
        allowed=["harness/**"],
    )

    assert result["verdict"] == "PASS"
    assert result["numerator"] == result["denominator"] == 2


@pytest.mark.parametrize(
    ("before", "after", "allowed"),
    [
        ({"/absolute.txt": "a"}, {"/absolute.txt": "b"}, ["harness/**"]),
        ({"backend/../secret.txt": "a"}, {"backend/../secret.txt": "b"}, ["harness/**"]),
        ({"backend/./main.py": "a"}, {"backend/./main.py": "b"}, ["harness/**"]),
        ({"": "a"}, {"": "b"}, ["harness/**"]),
        ({"harness/a.json": "a"}, {"harness/a.json": "b"}, [""]),
    ],
)
def test_allowed_paths_returns_invalid_for_illegal_paths_or_patterns(
    before: dict[str, str], after: dict[str, str], allowed: list[str]
) -> None:
    assert evaluate_allowed_paths(before, after, allowed)["verdict"] == "INVALID"


def test_allowed_paths_returns_invalid_when_nothing_changed() -> None:
    result = evaluate_allowed_paths(
        before={"harness/evidence/G0/a.json": "same"},
        after={"harness/evidence/G0/a.json": "same"},
        allowed=["harness/**"],
    )

    assert result["verdict"] == "INVALID"
    assert result["changed_paths"] == []
    assert result["denominator"] == 0


def test_source_provenance_blocks_missing_decision_receipt() -> None:
    result = evaluate_source_provenance(
        [
            {
                "source_repository": "example/repo",
                "upstream_commit": "abc123",
                "source_path": "module.py",
                "license_expression": "MIT",
                "reuse_mode": "direct_reuse",
                "decision": "approved",
                "obligations": [],
                "resolved_obligations": [],
                "license_decision_receipt": None,
            }
        ]
    )

    assert result["verdict"] == "BLOCKED"
    assert result["reasons"] == ["missing_license_decision_receipt:example/repo@abc123:module.py"]


def test_source_provenance_blocks_incompatible_direct_reuse() -> None:
    result = evaluate_source_provenance(
        [
            {
                "source_repository": "example/repo",
                "upstream_commit": "abc123",
                "source_path": "module.py",
                "license_expression": "UNKNOWN",
                "reuse_mode": "direct_reuse",
                "decision": "approved",
                "obligations": [],
                "resolved_obligations": [],
                "license_decision_receipt": {"canonical_sha256": "a" * 64},
            }
        ]
    )

    assert result["verdict"] == "BLOCKED"
    assert result["reasons"] == ["incompatible_direct_reuse:example/repo@abc123:module.py:UNKNOWN"]


def test_source_provenance_accepts_compatible_resolved_source() -> None:
    result = evaluate_source_provenance(
        [
            {
                "source_repository": "example/repo",
                "upstream_commit": "abc123",
                "source_path": "module.py",
                "license_expression": "Apache-2.0",
                "reuse_mode": "direct_reuse",
                "decision": "approved",
                "obligations": ["NOTICE"],
                "resolved_obligations": ["NOTICE"],
                "license_decision_receipt": {"canonical_sha256": "a" * 64},
            }
        ]
    )

    assert result == {"verdict": "PASS", "reasons": [], "numerator": 1, "denominator": 1}


def test_source_provenance_rejects_empty_corpus() -> None:
    assert evaluate_source_provenance([]) == {
        "verdict": "INVALID",
        "reasons": ["source_provenance_empty"],
        "numerator": 0,
        "denominator": 0,
    }


def test_g0_truth_blocks_when_protected_trust_material_is_missing(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"{}\n")
    protected_root = tmp_path / "protected"
    protected_root.mkdir()

    result = verify_adjudication(
        receipt,
        root=tmp_path,
        protected_root=protected_root,
        config_path=protected_root / "config.json",
        gate_id="GATE-REQ-G0.1",
    )

    assert result == {"verdict": "BLOCKED", "reason": "protected_config_path"}


def test_g0_truth_blocks_unsigned_receipt_when_trust_config_is_unavailable(tmp_path: Path) -> None:
    result = verify_adjudication(
        tmp_path / "missing-receipt.json",
        root=tmp_path,
        protected_root=tmp_path,
        config_path=tmp_path / "missing-config.json",
        gate_id="GATE-REQ-G0.1",
    )

    assert result == {"verdict": "BLOCKED", "reason": "receipt_unreadable"}


def test_bootstrap_and_phase_lock_have_exact_bidirectional_coverage() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert validate_contract(contract, file_hash=EXPECTED_FILE_SHA256)["verdict"] == "PASS"
    result = validate_lock(json.loads(LOCK.read_text(encoding="utf-8")), contract)
    assert result == {
        "verdict": "PASS",
        "requirements": 207,
        "gates": 207,
        "coverage_numerator": 207,
        "coverage_denominator": 207,
    }


def test_all_bootstrap_tamper_vectors_reject_the_mutation() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    result = run_tamper_vectors(contract, lock)
    assert result["verdict"] == "PASS"
    assert result["numerator"] == result["denominator"] == 12


def test_tv_011_and_tv_012_execute_real_checkers() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    result = run_tamper_vectors(contract, lock)
    cases = {case["id"]: case for case in result["cases"]}

    assert cases["TV-011"]["actual"] == "FAIL"
    assert cases["TV-011"]["checker"]["name"] == "evaluate_allowed_paths"
    assert cases["TV-011"]["checker"]["input_sha256"]
    assert cases["TV-012"]["actual"] == "BLOCKED"
    assert cases["TV-012"]["checker"]["name"] == "evaluate_source_provenance"
    assert cases["TV-012"]["checker"]["input_sha256"]


def test_tamper_runner_does_not_hardcode_tv_011_or_tv_012_verdicts() -> None:
    source = (SCRIPTS / "bootstrap_contract.py").read_text(encoding="utf-8")
    assert 'outcomes["TV-011"] = "FAIL"' not in source
    assert 'outcomes["TV-012"] = "BLOCKED"' not in source


def test_g0_gate_specs_cover_every_g0_requirement_exactly() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    expected = {item["id"] for item in contract["requirements"] if item["id"].startswith("REQ-G0")}
    assert set(G0_GATE_SPECS) == expected
    assert all(spec["checks"] and spec["artifacts"] for spec in G0_GATE_SPECS.values())


def test_prior_automation_ownership_requires_external_attestation_not_exact_hashes(tmp_path: Path) -> None:
    owned = tmp_path / "tests" / "prior_g0_test.py"
    owned.parent.mkdir(parents=True)
    owned.write_text("assert True\n", encoding="utf-8")
    manifest = tmp_path / "harness" / "baseline" / "prior-automation-ownership.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "g0_exact_prior_automation_ownership",
                "entries": [
                    {
                        "path": "tests/prior_g0_test.py",
                        "sha256": _sha256(owned),
                        "owner": "self_attested_legacy_owner",
                        "role": "g0_contract_test",
                        "observed_utc": "2026-07-17T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records, receipt = _load_prior_automation_ownership(tmp_path)

    assert records == {}
    assert receipt["legacy_manifest_status"] == "observed_untrusted"
    assert receipt["external_validation"] == "pending"
    assert receipt["observed_declared_paths"] == ["tests/prior_g0_test.py"]
    assert receipt["errors"] == ["prior_automation_ownership_external_attestation_required"]
    assert len(receipt["unblock_conditions"]) == 3

    owned.write_text("assert False\n", encoding="utf-8")
    records, drifted_receipt = _load_prior_automation_ownership(tmp_path)
    assert records == {}
    assert drifted_receipt["errors"] == ["prior_automation_ownership_external_attestation_required"]


def test_junit_metrics_preserve_nonempty_denominator_and_skips(tmp_path: Path) -> None:
    junit = tmp_path / "lane.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="1" time="1.25" /></testsuites>',
        encoding="utf-8",
    )
    assert parse_junit(junit) == {
        "tests": 3,
        "failures": 0,
        "errors": 0,
        "skipped": 1,
        "time": 1.25,
    }


def _single_lane_summary(junit: Path, digest: str | None, *, declared_exists: bool = True) -> dict[str, object]:
    return {"lanes": {"unit": {"junit": str(junit), "junit_exists": declared_exists, "junit_sha256": digest}}}



def _create_test_junction(link: Path, target: Path) -> None:
    escaped_link = str(link).replace("'", "''")
    escaped_target = str(target).replace("'", "''")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path '" + escaped_link + "' -Target '" + escaped_target + "' | Out-Null",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    assert completed.returncode == 0, {"stdout": completed.stdout, "stderr": completed.stderr, "command": command}
    assert link.exists()



def _create_dangling_test_junction(link: Path, target: Path) -> None:
    target.mkdir()
    _create_test_junction(link, target)
    target.rmdir()
    assert link.exists() is False
    assert _is_reparse_point(link) is True



def test_lane_receipt_validation_fails_closed_for_missing_junit_digest(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    junit = evidence / "lane-unit.xml"
    junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    result = validate_lane_receipts(_single_lane_summary(junit, None), evidence_dir=evidence, workspace_root=tmp_path, required_lanes=("unit",))
    assert result["verdict"] == "FAIL"
    assert result["lanes"]["unit"]["errors"] == ["junit_sha256_missing_or_invalid"]


def test_lane_receipt_validation_fails_closed_for_digest_mismatch(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    junit = evidence / "lane-unit.xml"
    junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    result = validate_lane_receipts(_single_lane_summary(junit, "0" * 64), evidence_dir=evidence, workspace_root=tmp_path, required_lanes=("unit",))
    assert result["lanes"]["unit"]["errors"] == ["junit_sha256_mismatch"]


def test_lane_receipt_validation_fails_closed_for_outside_and_noncanonical_paths(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside.xml"
    outside.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    other = evidence / "unrelated.xml"
    other.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    outside_result = validate_lane_receipts(_single_lane_summary(outside, hashlib.sha256(outside.read_bytes()).hexdigest()), evidence_dir=evidence, workspace_root=tmp_path, required_lanes=("unit",))
    other_result = validate_lane_receipts(_single_lane_summary(other, hashlib.sha256(other.read_bytes()).hexdigest()), evidence_dir=evidence, workspace_root=tmp_path, required_lanes=("unit",))
    assert outside_result["lanes"]["unit"]["errors"] == ["junit_path_outside_evidence"]
    assert other_result["lanes"]["unit"]["errors"] == ["junit_path_not_canonical_for_lane"]


def test_lane_receipt_validation_fails_closed_for_missing_file_and_evidence_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    missing = evidence / "lane-unit.xml"
    missing_result = validate_lane_receipts(_single_lane_summary(missing, "0" * 64), evidence_dir=evidence, workspace_root=workspace, required_lanes=("unit",))
    foreign = tmp_path / "foreign-evidence"
    foreign.mkdir()
    foreign_junit = foreign / "lane-unit.xml"
    foreign_junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    foreign_result = validate_lane_receipts(_single_lane_summary(foreign_junit, hashlib.sha256(foreign_junit.read_bytes()).hexdigest()), evidence_dir=foreign, workspace_root=workspace, required_lanes=("unit",))
    assert missing_result["lanes"]["unit"]["errors"] == ["junit_file_missing"]
    assert foreign_result["lanes"]["unit"]["errors"] == ["evidence_dir_outside_workspace"]


def test_lane_receipt_validation_rejects_hardlinked_canonical_junit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    source = workspace / "source.xml"
    source.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    junit = evidence / "lane-unit.xml"
    os.link(source, junit)

    assert junit.stat().st_nlink >= 2
    result = validate_lane_receipts(
        _single_lane_summary(junit, hashlib.sha256(junit.read_bytes()).hexdigest()),
        evidence_dir=evidence,
        workspace_root=workspace,
        required_lanes=("unit",),
    )

    assert result["verdict"] == "FAIL"
    assert result["lanes"]["unit"]["errors"] == ["junit_hardlink_not_allowed"]



def test_run_lanes_rejects_hardlinked_staged_junit_before_evidence_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    calls: list[list[str]] = []
    observation: dict[str, object] = {}

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            assert timeout == 3600
            calls.append(command)
            staged = Path(command[command.index("--junitxml") + 1])
            forged = staged.parent.parent / f"{staged.parent.name}-forged-valid-junit.xml"
            forged.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" time="0.01" />', encoding="utf-8")
            os.link(forged, staged)
            observation.update(
                {
                    "forged": forged,
                    "staged_lstat_nlink": staged.lstat().st_nlink,
                    "forged_lstat_nlink": forged.lstat().st_nlink,
                    "staged_is_reparse": _is_reparse_point(staged),
                    "forged_bytes": forged.read_bytes(),
                }
            )
            return {"returncode": 0, "stdout": "forged child", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    try:
        with pytest.raises(G0Error, match="lane_staged_source_hardlink_not_allowed"):
            asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))
    finally:
        forged = observation.get("forged")
        if isinstance(forged, Path) and forged.exists():
            forged.unlink()

    assert len(calls) == 1
    assert observation["staged_lstat_nlink"] == observation["forged_lstat_nlink"] == 2
    assert observation["staged_is_reparse"] is False
    assert list(evidence.iterdir()) == []


def test_run_lanes_rejects_staging_inside_workspace_before_supervisor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    workspace_temp = workspace / "controlled-temp"
    workspace_temp.mkdir()
    constructors = 0
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            nonlocal constructors
            constructors += 1
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

    monkeypatch.setattr(g0_runner.tempfile, "tempdir", str(workspace_temp))
    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="lane_staging_inside_workspace_not_allowed"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))

    assert constructors == 0
    assert calls == []
    assert list(evidence.iterdir()) == []


def test_run_lanes_rejects_external_evidence_before_any_supervisor_or_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external_evidence = tmp_path / "external-evidence"
    external_evidence.mkdir()
    constructors = 0
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            nonlocal constructors
            constructors += 1
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="evidence_dir_outside_workspace"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", external_evidence, ["unit"]))

    assert constructors == 0
    assert calls == []
    assert list(external_evidence.iterdir()) == []


def test_run_lanes_rejects_reparse_evidence_before_any_supervisor_or_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    evidence = workspace / "evidence"
    _create_test_junction(evidence, external)
    constructors = 0
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            nonlocal constructors
            constructors += 1
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="evidence_dir_reparse_point_not_allowed"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))

    assert constructors == 0
    assert calls == []
    assert list(external.iterdir()) == []


def test_run_lanes_rejects_evidence_swap_after_supervisor_construction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    constructors = 0
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            nonlocal constructors
            constructors += 1
            evidence.rmdir()
            _create_test_junction(evidence, external)
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            return {"returncode": 0, "stdout": "unexpected", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="evidence_dir_reparse_point_not_allowed"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))

    assert constructors == 1
    assert calls == []
    assert list(external.iterdir()) == []


def test_run_lanes_stages_child_output_before_rejecting_mid_run_evidence_swap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            staged_junit = Path(command[command.index("--junitxml") + 1])
            assert not str(staged_junit).startswith(str(evidence))
            staged_junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
            evidence.rmdir()
            _create_test_junction(evidence, external)
            return {"returncode": 0, "stdout": "staged", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="evidence_dir_reparse_point_not_allowed"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))

    assert len(calls) == 1
    assert list(external.iterdir()) == []


def test_evidence_target_rejects_real_dangling_junction_before_copy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    dangling_target = tmp_path / "external-target"
    destination = evidence / "lane-unit.xml"
    _create_dangling_test_junction(destination, dangling_target)
    guard = _EvidenceDirectoryGuard(evidence, workspace)

    with pytest.raises(G0Error, match="evidence_target_reparse_point_not_allowed"):
        _assert_safe_evidence_target(destination, guard)

    assert dangling_target.exists() is False


def test_commit_rejects_descendant_junction_before_external_copy(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    descendant = evidence / "child"
    _create_test_junction(descendant, external)
    staging = tmp_path / "external-staging"
    staging.mkdir()
    staged = staging / "staged.xml"
    staged.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    guard = _EvidenceDirectoryGuard(evidence, workspace)
    staging_guard = _StagingDirectoryGuard(staging, guard)

    with pytest.raises(G0Error, match="evidence_target_parent_not_canonical"):
        _commit_staged_evidence_file(staged, descendant / "report.xml", guard, staging_guard)

    assert list(external.iterdir()) == []


def test_commit_atomically_replaces_destination_hardlink_without_writing_outside(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    staging = tmp_path / "external-staging"
    staging.mkdir()
    source = staging / "source.xml"
    source.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
    destination = evidence / "lane-unit.xml"
    destination.write_text("normal-existing-destination", encoding="utf-8")
    outside = tmp_path / "outside-victim.xml"
    outside_original = b"outside-victim-original-bytes"
    outside.write_bytes(outside_original)
    guard = _EvidenceDirectoryGuard(evidence, workspace)
    staging_guard = _StagingDirectoryGuard(staging, guard)
    observation: dict[str, object] = {}
    original_replace = g0_runner.os.replace

    def replace_after_destination_hardlink_swap(source_path: str | os.PathLike[str], destination_path: str | os.PathLike[str]) -> None:
        assert Path(destination_path) == destination
        destination.unlink()
        os.link(outside, destination)
        observation["replace_called"] = True
        observation["destination_nlink_before_replace"] = destination.lstat().st_nlink
        observation["outside_nlink_before_replace"] = outside.lstat().st_nlink
        original_replace(source_path, destination_path)
        observation["outside_after_replace"] = outside.read_bytes()

    monkeypatch.setattr(g0_runner.os, "replace", replace_after_destination_hardlink_swap)
    committed = _commit_staged_evidence_file(source, destination, guard, staging_guard)

    assert committed is True
    assert observation["replace_called"] is True
    assert observation["destination_nlink_before_replace"] == observation["outside_nlink_before_replace"] == 2
    assert observation["outside_after_replace"] == outside_original
    assert outside.read_bytes() == outside_original
    assert destination.read_bytes() == source.read_bytes()
    assert destination.lstat().st_nlink == 1
    assert _is_reparse_point(destination) is False


def test_run_lanes_rejects_dangling_junction_target_before_evidence_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "evidence"
    evidence.mkdir()
    dangling_target = tmp_path / "external-target"
    destination = evidence / "lane-unit.xml"
    _create_dangling_test_junction(destination, dangling_target)
    calls: list[list[str]] = []

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            calls.append(command)
            staged_junit = Path(command[command.index("--junitxml") + 1])
            staged_junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
            return {"returncode": 0, "stdout": "staged", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    with pytest.raises(G0Error, match="evidence_target_reparse_point_not_allowed"):
        asyncio.run(run_lanes(workspace, workspace / "python.exe", evidence, ["unit"]))

    assert len(calls) == 1
    assert dangling_target.exists() is False
    assert not (evidence / "lane-unit.stdout.txt").exists()
    assert not (evidence / "lane-unit.stderr.txt").exists()


def test_run_lanes_binds_and_validates_junit_digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    class FakeSupervisor:
        def __init__(self, _root: Path, _names: set[str]) -> None:
            self._processes: dict[str, object] = {}

        async def run(self, _name: str, command: list[str], _cwd: Path, timeout: int) -> dict[str, object]:
            assert timeout == 3600
            junit = Path(command[command.index("--junitxml") + 1])
            junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0" />', encoding="utf-8")
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr("g0_runner.ProcessSupervisor", FakeSupervisor)
    result = asyncio.run(run_lanes(tmp_path, tmp_path / "python.exe", evidence, ["unit"]))
    lane = result["lanes"]["unit"]

    assert lane["junit_sha256"] == hashlib.sha256(Path(lane["junit"]).read_bytes()).hexdigest()
    assert result["receipt_validation"]["verdict"] == "PASS"
    assert result["verdict"] == "PASS"


def test_journal_rebuilds_state_and_rejects_truncation_or_tampering(tmp_path: Path) -> None:
    journal = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    append_event(journal, state, "phase_state", {"phase_id": "G0", "state": "in_progress"}, "g0:start")
    append_event(journal, state, "finding_state", {"finding_id": "F-1", "state": "open"}, "f1:open")
    events = read_events(journal)
    assert verify_events(events)["events"] == 2
    assert json.loads(state.read_text(encoding="utf-8")) == project(events)

    truncated = tmp_path / "truncated.jsonl"
    truncated.write_bytes(journal.read_bytes()[:-1])
    with pytest.raises(JournalError, match="truncated_tail"):
        read_events(truncated)

    tampered = tmp_path / "tampered.jsonl"
    lines = journal.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["payload"]["state"] = "accepted"
    lines[0] = json.dumps(event, sort_keys=True)
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(JournalError, match="event_hash"):
        verify_events(read_events(tampered))


def test_secret_scan_excludes_bundled_runtime_but_scans_product_files(tmp_path: Path) -> None:
    runtime_file = tmp_path / "runtime" / "fixture.txt"
    product_file = tmp_path / "backend" / "config.txt"
    runtime_file.parent.mkdir(parents=True)
    product_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(b"sk-" + b"x" * 20)
    product_file.write_bytes(b"sk-" + b"y" * 20)

    result = scan(tmp_path)

    assert result["high_risk_findings"] == 1
    assert result["findings"][0]["path"] == "backend/config.txt"


def test_baseline_is_a_real_copy_not_a_hardlink() -> None:
    baseline = Path(r"D:\科研软件制作\Vibe-research源码-Day0Baseline\full-repository")
    source = ROOT / "package.json"
    copied = baseline / "package.json"
    assert copied.is_file()
    assert source.read_bytes() == copied.read_bytes()
    source_links = subprocess.check_output(
        ["fsutil", "hardlink", "list", str(source)], text=True, encoding="utf-8", errors="replace"
    ).splitlines()
    copied_links = subprocess.check_output(
        ["fsutil", "hardlink", "list", str(copied)], text=True, encoding="utf-8", errors="replace"
    ).splitlines()
    assert len(source_links) == len(copied_links) == 1
    assert Path(source_links[0]).resolve() != Path(copied_links[0]).resolve()


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_entry(path: str, source: str, snapshot_path: str | None, content: Path | None) -> dict[str, object]:
    if content is None:
        return {"path": path, "source": source, "snapshotPath": None, "size": None, "sha256": None}
    return {
        "path": path,
        "source": source,
        "snapshotPath": snapshot_path,
        "size": content.stat().st_size,
        "sha256": _sha256(content),
    }


def _make_restore_fixture(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet", "--initial-branch=restore-test")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Restore Test")
    tracked = source / "tracked.txt"
    deleted = source / "deleted.txt"
    clean = source / "clean-lf.txt"
    tracked.write_text("base\n", encoding="utf-8")
    deleted.write_text("remove me\n", encoding="utf-8")
    clean.write_bytes(b"clean canonical bytes\n")
    _git(source, "add", ".")
    _git(source, "commit", "--quiet", "-m", "initial")

    tracked.write_text("modified\n", encoding="utf-8")
    deleted.unlink()
    untracked = source / "untracked" / "nested.txt"
    untracked.parent.mkdir()
    untracked.write_text("untracked\n", encoding="utf-8")

    baseline = tmp_path / "baseline"
    metadata = baseline / "git-metadata"
    worktree = baseline / "worktree"
    metadata.mkdir(parents=True)
    worktree.mkdir()
    _git(source, "bundle", "create", str(metadata / "repository.bundle"), "--all")
    (metadata / "branch.txt").write_bytes(_git(source, "branch", "--show-current"))
    shutil.copyfile(source / ".git" / "HEAD", metadata / "HEAD")
    (metadata / "head-commit.txt").write_bytes(_git(source, "rev-parse", "HEAD"))
    shutil.copyfile(source / ".git" / "index", metadata / "index")
    (metadata / "refs-before.txt").write_bytes(_git(source, "for-each-ref", "--format=%(refname) %(objectname)"))
    (metadata / "status-before.txt").write_bytes(_git(source, "status", "--porcelain=v2", "--branch"))
    shutil.copyfile(tracked, worktree / "tracked.txt")
    (worktree / "untracked").mkdir()
    shutil.copyfile(untracked, worktree / "untracked" / "nested.txt")

    metadata_entries = [
        ("@git/branch", "git_branch_metadata", "git-metadata/branch.txt"),
        ("@git/HEAD", "git_head_file_copy", "git-metadata/HEAD"),
        ("@git/head-commit", "git_head_metadata", "git-metadata/head-commit.txt"),
        ("@git/index", "git_index_copy", "git-metadata/index"),
        ("@git/refs-before", "git_refs_metadata", "git-metadata/refs-before.txt"),
        ("@git/repository.bundle", "git_recovery_bundle", "git-metadata/repository.bundle"),
        ("@git/status-before", "git_status_metadata", "git-metadata/status-before.txt"),
    ]
    entries = [_snapshot_entry(path, source_kind, snapshot_path, baseline / snapshot_path) for path, source_kind, snapshot_path in metadata_entries]
    entries.extend(
        [
            _snapshot_entry("tracked.txt", "tracked_modified", "worktree/tracked.txt", worktree / "tracked.txt"),
            _snapshot_entry(
                "untracked/nested.txt",
                "untracked",
                "worktree/untracked/nested.txt",
                worktree / "untracked" / "nested.txt",
            ),
            _snapshot_entry("deleted.txt", "tracked_deleted", None, None),
        ]
    )
    (baseline / "manifest.json").write_text(
        json.dumps({"kind": "vibe-research-day0-baseline", "entries": entries}), encoding="utf-8"
    )
    return baseline


def _refresh_manifest_metadata(baseline: Path) -> None:
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        snapshot = entry.get("snapshotPath")
        if snapshot and str(snapshot).startswith("git-metadata/"):
            file_path = baseline / str(snapshot)
            entry["size"] = file_path.stat().st_size
            entry["sha256"] = _sha256(file_path)
    (baseline / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _refresh_baseline_git_metadata(baseline: Path, source: Path, *status_args: str) -> None:
    metadata = baseline / "git-metadata"
    _git(source, "bundle", "create", str(metadata / "repository.bundle"), "--all")
    shutil.copyfile(source / ".git" / "HEAD", metadata / "HEAD")
    (metadata / "head-commit.txt").write_bytes(_git(source, "rev-parse", "HEAD"))
    shutil.copyfile(source / ".git" / "index", metadata / "index")
    (metadata / "refs-before.txt").write_bytes(
        _git(source, "for-each-ref", "--format=%(refname) %(objectname)")
    )
    (metadata / "status-before.txt").write_bytes(
        _git(source, "status", "--porcelain=v2", "--branch", *status_args)
    )
    _refresh_manifest_metadata(baseline)


def test_restore_drill_reconstructs_worktree_and_git_state_byte_exactly(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    target = tmp_path / "restored"

    receipt = restore_and_verify(baseline, target)

    assert receipt["verdict"] == "PASS", json.dumps(receipt, sort_keys=True)
    assert receipt["verification"]["status_byte_exact_match"] is True
    assert receipt["verification"]["refs_byte_exact_match"] is True
    assert receipt["verification"]["index_sha256_match"] is True
    assert receipt["verification"]["index_unchanged_by_materialization"] is True
    assert receipt["verification"]["index_unchanged_by_status"] is True
    assert (target / "tracked.txt").read_text(encoding="utf-8") == "modified\n"
    assert (target / "clean-lf.txt").read_bytes() == b"clean canonical bytes\n"
    assert (target / "untracked" / "nested.txt").read_text(encoding="utf-8") == "untracked\n"
    assert not (target / "deleted.txt").exists()


def test_restore_drill_materializes_clean_filtered_files_from_saved_index(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    source = tmp_path / "source"
    clean = source / "clean-crlf.txt"
    clean.write_bytes(b"first\r\nsecond\r\n")
    (source / ".gitattributes").write_text("clean-crlf.txt text eol=crlf\n", encoding="utf-8")
    _git(source, "add", ".gitattributes", "clean-crlf.txt")
    _git(source, "commit", "--quiet", "-m", "add filtered clean file")
    clean.unlink()
    _git(source, "checkout", "--", "clean-crlf.txt")

    _refresh_baseline_git_metadata(baseline, source)

    target = tmp_path / "restored-filtered"
    receipt = restore_and_verify(baseline, target)

    assert receipt["verdict"] == "PASS", json.dumps(receipt, sort_keys=True)
    assert (target / "clean-crlf.txt").read_bytes() == b"first\r\nsecond\r\n"
    assert receipt["verification"]["index_unchanged_by_status"] is True


def test_restore_drill_uses_validated_snapshot_for_mixed_line_endings(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    source = tmp_path / "source"
    mixed = source / "mixed.txt"
    mixed.write_bytes(b"first\nsecond\r\n")
    _git(source, "add", "mixed.txt")
    _git(source, "commit", "--quiet", "-m", "add mixed line endings")
    full_repository = baseline / "full-repository"
    full_repository.mkdir()
    shutil.copyfile(mixed, full_repository / "mixed.txt")
    _refresh_baseline_git_metadata(baseline, source)

    target = tmp_path / "restored-mixed"
    receipt = restore_and_verify(baseline, target)

    assert receipt["verdict"] == "PASS", json.dumps(receipt, sort_keys=True)
    assert (target / "mixed.txt").read_bytes() == b"first\nsecond\r\n"
    assert receipt["verification"]["materialization_clean_snapshot_fallbacks"] == [
        {
            "path": "mixed.txt",
            "purpose": "clean_mixed_line_endings",
            "sha256": _sha256(mixed),
            "git_object_id": _git(source, "rev-parse", "HEAD:mixed.txt").strip().decode("ascii"),
        }
    ]


def test_restore_drill_preserves_status_only_line_ending_change(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    source = tmp_path / "source"
    status_only = source / "status-only.txt"
    status_only.write_bytes(b"first\nsecond\n")
    _git(source, "add", "status-only.txt")
    _git(source, "commit", "--quiet", "-m", "add status-only file")
    status_only.write_bytes(b"first\r\nsecond\r\n")
    full_repository = baseline / "full-repository"
    full_repository.mkdir()
    shutil.copyfile(status_only, full_repository / "status-only.txt")
    _refresh_baseline_git_metadata(baseline, source)
    assert _git(source, "diff", "--", "status-only.txt") == b""
    assert b"status-only.txt" in (baseline / "git-metadata" / "status-before.txt").read_bytes()

    target = tmp_path / "restored-status-only"
    receipt = restore_and_verify(baseline, target)

    assert receipt["verdict"] == "PASS", json.dumps(receipt, sort_keys=True)
    assert (target / "status-only.txt").read_bytes() == b"first\r\nsecond\r\n"
    assert receipt["verification"]["materialization_expected_status_fallbacks"] == [
        {
            "path": "status-only.txt",
            "purpose": "expected_status_only",
            "sha256": _sha256(status_only),
            "git_object_id": _git(source, "rev-parse", "HEAD:status-only.txt").strip().decode("ascii"),
        }
    ]


def test_restore_drill_replays_per_file_untracked_enumeration(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    source = tmp_path / "source"
    _refresh_baseline_git_metadata(baseline, source, "--untracked-files=all")

    receipt = restore_and_verify(baseline, tmp_path / "restored-untracked-all")

    assert receipt["verdict"] == "PASS", json.dumps(receipt, sort_keys=True)
    assert receipt["verification"]["status_untracked_mode"] == "all"


def test_restore_refs_removes_clone_symbolic_remote_head(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch=restore-test")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "Restore Test")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "--quiet", "-m", "initial")

    expected = _git(repository, "for-each-ref", "--format=%(refname) %(objectname)")
    _git(repository, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/heads/restore-test")
    _restore_refs(repository, _parse_refs(expected))

    assert _git(repository, "for-each-ref", "--format=%(refname) %(objectname)") == expected


def test_restore_drill_rejects_a_tampered_snapshot_before_restoration(tmp_path: Path) -> None:
    baseline = _make_restore_fixture(tmp_path)
    (baseline / "worktree" / "tracked.txt").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RestoreError, match="snapshot_content_mismatch"):
        restore_and_verify(baseline, tmp_path / "restored")
