from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_contract import (
    EXPECTED_FILE_SHA256,
    validate_contract,
    validate_gate_report,
    validate_lock,
)

from common import atomic_write_json, read_json, sha256_file


def verify_root(contract_path: Path, lock_path: Path) -> dict[str, Any]:
    actual_hash = sha256_file(contract_path)
    contract = read_json(contract_path)
    root = validate_contract(contract, file_hash=actual_hash)
    if root["verdict"] != "PASS":
        return root
    lock = validate_lock(read_json(lock_path), contract)
    if lock["verdict"] != "PASS":
        return lock
    return {
        "verdict": "PASS",
        "root_sha256_expected": EXPECTED_FILE_SHA256,
        "root_sha256_actual": actual_hash,
        "requirements_numerator": lock["coverage_numerator"],
        "requirements_denominator": lock["coverage_denominator"],
    }


def verify_gate(lock_path: Path, gate_id: str, report_path: Path) -> dict[str, Any]:
    lock = read_json(lock_path)
    gate = next((item for item in lock.get("gates", []) if item.get("id") == gate_id), None)
    if gate is None:
        return {"verdict": "INVALID", "reason": "unknown_gate"}
    report = read_json(report_path)
    if report.get("gate_id") != gate_id:
        return {"verdict": "INVALID", "reason": "gate_id_mismatch"}
    if report.get("requirement_sha256") != gate["requirement_sha256"]:
        return {"verdict": "STALE", "reason": "requirement_hash_mismatch"}
    if report.get("runner_sha256") != gate["runner"]["sha256"]:
        return {"verdict": "STALE", "reason": "runner_hash_mismatch"}
    result = validate_gate_report(report)
    if result["verdict"] != "PASS":
        return result
    artifacts = report.get("artifacts", [])
    if not artifacts:
        return {"verdict": "INVALID", "reason": "empty_artifacts"}
    for artifact in artifacts:
        path = Path(artifact["path"])
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            return {"verdict": "FAIL", "reason": f"artifact_mismatch:{path}"}
    return {"verdict": "PASS", "gate_id": gate_id, "artifacts": len(artifacts)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("root", "gate", "report"))
    parser.add_argument("--contract", type=Path, default=Path(r"D:\科研软件制作\开发指导.bootstrap.json"))
    parser.add_argument("--lock", type=Path, default=Path("harness/phase-contract.lock"))
    parser.add_argument("--gate-id")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "root":
        result = verify_root(args.contract, args.lock)
    elif args.command == "gate":
        if not args.gate_id or not args.report:
            parser.error("gate requires --gate-id and --report")
        result = verify_gate(args.lock, args.gate_id, args.report)
    else:
        if not args.report:
            parser.error("report requires --report")
        result = validate_gate_report(read_json(args.report))
    if args.output:
        atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
