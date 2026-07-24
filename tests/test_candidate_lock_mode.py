from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness" / "scripts"))

from bootstrap_contract import (  # noqa: E402
    CANDIDATE_LOCK_FILENAME,
    CANDIDATE_MANIFEST_FILENAME,
    G0_REPORT_SET_FILENAME,
    ContractError,
    G0_TRUTH_PATH,
    generate_candidate_lock,
    validate_candidate_lock,
)
from common import canonical_json  # noqa: E402

CONTRACT = Path(r"D:\科研软件制作\开发指导.bootstrap.json")
AUTHORITATIVE_LOCK = ROOT / "harness" / "phase-contract.lock"


def _candidate_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    scripts = root / "harness" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(AUTHORITATIVE_LOCK, root / "harness" / "phase-contract.lock")
    shutil.copyfile(ROOT / G0_TRUTH_PATH, root / G0_TRUTH_PATH)
    shutil.copyfile(ROOT / "harness" / "scripts" / "verify_truth.py", root / "harness" / "scripts" / "verify_truth.py")
    return root


def _generate(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = _candidate_root(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    candidate = generate_candidate_lock(contract, root=root)
    return root, candidate


def test_candidate_accepts_explicit_bootstrap_and_authoritative_paths(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path)
    bootstrap = tmp_path / "bootstrap.json"
    authoritative = tmp_path / "authoritative.json"
    shutil.copyfile(CONTRACT, bootstrap)
    shutil.copyfile(root / "harness" / "phase-contract.lock", authoritative)
    contract = json.loads(bootstrap.read_text(encoding="utf-8"))
    candidate = generate_candidate_lock(
        contract,
        root=root,
        bootstrap_path=bootstrap,
        authoritative_lock_path=authoritative,
    )
    assert validate_candidate_lock(
        candidate,
        contract,
        root=root,
        bootstrap_path=bootstrap,
        authoritative_lock_path=authoritative,
    ) ["verdict"] == "CANDIDATE"


def test_candidate_generation_writes_canonical_manifest_and_g0_report_set(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    manifest_path = root / CANDIDATE_MANIFEST_FILENAME
    report_set_path = root / G0_REPORT_SET_FILENAME
    assert manifest_path.read_bytes() == canonical_json(json.loads(manifest_path.read_text(encoding="utf-8"))) + b"\n"
    assert candidate["candidate_manifest"] == {
        "path": CANDIDATE_MANIFEST_FILENAME,
        "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    report_set = json.loads(report_set_path.read_text(encoding="utf-8"))
    assert report_set_path.read_bytes() == canonical_json(report_set) + b"\n"
    assert report_set["schema_version"] == "1.0"
    assert [entry["gate_id"] for entry in report_set["gate_reports"]] == sorted(
        entry["gate_id"] for entry in report_set["gate_reports"]
    )
    assert candidate["g0_report_set"] == {
        "path": G0_REPORT_SET_FILENAME,
        "sha256": hashlib.sha256(report_set_path.read_bytes()).hexdigest(),
    }


def test_candidate_validation_rejects_raw_manifest_and_report_set_tampering(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for path in (root / CANDIDATE_MANIFEST_FILENAME, root / G0_REPORT_SET_FILENAME):
        path.write_bytes(path.read_bytes() + b" ")
        assert validate_candidate_lock(candidate, contract, root=root)["verdict"] == "STALE"
        _generate(tmp_path)


def test_candidate_generation_is_non_destructive_and_pins_g0_truth(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    authoritative = json.loads((root / "harness" / "phase-contract.lock").read_text(encoding="utf-8"))
    assert (root / CANDIDATE_LOCK_FILENAME).is_file()
    assert candidate["status"] == "CANDIDATE"
    assert candidate["candidate_manifest"]["path"] == CANDIDATE_MANIFEST_FILENAME
    expected_non_g0 = [gate for gate in authoritative["gates"] if gate["section"] != "G0"]
    actual_non_g0 = [gate for gate in candidate["gates"] if gate["section"] != "G0"]
    assert actual_non_g0 == expected_non_g0


def test_candidate_validation_rejects_g0_command_and_hash_mutations(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    g0_index = next(i for i, gate in enumerate(candidate["gates"]) if gate["section"] == "G0")
    for field, value in (("command", ["python", "evil.py"]), ("sha256", "0" * 64)):
        mutated = copy.deepcopy(candidate)
        mutated["gates"][g0_index]["runner"][field] = value
        assert validate_candidate_lock(mutated, contract, root=root)["verdict"] != "CANDIDATE"


def test_candidate_validation_rejects_manifest_lock_hash_and_non_g0_mutations(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    stale = copy.deepcopy(candidate)
    manifest_path = root / CANDIDATE_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lock_sha256"] = "0" * 64
    manifest_path.write_bytes(canonical_json(manifest) + b"\n")
    assert validate_candidate_lock(stale, contract, root=root)["verdict"] == "STALE"

    mutated = copy.deepcopy(candidate)
    gate = next(gate for gate in mutated["gates"] if gate["section"] != "G0")
    gate["threshold"]["denominator_min"] = 2
    assert validate_candidate_lock(mutated, contract, root=root)["verdict"] != "CANDIDATE"


def test_candidate_path_is_fixed_and_authoritative_lock_cannot_be_overwritten(tmp_path: Path) -> None:
    root = _candidate_root(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    authoritative = root / "harness" / "phase-contract.lock"
    before = authoritative.read_bytes()
    with pytest.raises(ContractError, match="candidate_lock_path"):
        generate_candidate_lock(contract, root=root, lock_path=authoritative)
    assert authoritative.read_bytes() == before


def test_candidate_validation_rejects_stale_manifest_and_unsigned_acceptance(tmp_path: Path) -> None:
    root, candidate = _generate(tmp_path)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    result = validate_candidate_lock(candidate, contract, root=root)
    assert result["verdict"] == "CANDIDATE", result

    stale = copy.deepcopy(candidate)
    stale["candidate_manifest"]["sha256"] = "0" * 64
    assert validate_candidate_lock(stale, contract, root=root)["verdict"] == "STALE"

    accepted = copy.deepcopy(candidate)
    accepted["status"] = "FROZEN"
    assert validate_candidate_lock(accepted, contract, root=root)["verdict"] == "BLOCKED"
