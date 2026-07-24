from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json, canonical_json, read_json, sha256_file
from source_provenance import evaluate_source_provenance
from task_boundary import evaluate_allowed_paths


EXPECTED_FILE_SHA256 = "a843e10612a602e8226cfc89f5976811e4e0094b41dfa5f60f65dfd5db51cdf8"
EXPECTED_REQUIREMENTS = 207
EXPECTED_TAMPER_VECTORS = 12
EXPECTED_MERKLE_ROOT = "6e2a54e318865379781909a43ac2d0c5ff6878342c57415770899afce675b6d0"
CANDIDATE_LOCK_FILENAME = "harness/phase-contract.candidate.lock"
CANDIDATE_MANIFEST_FILENAME = "harness/phase-contract.candidate.manifest.json"
G0_REPORT_SET_FILENAME = "harness/evidence/G0/g0-report-set.json"
CANDIDATE_ROLE = "candidate_phase_contract"
CANDIDATE_STATUS = "PENDING_INDEPENDENT_ADJUDICATION"
G0_TRUTH_PATH = "harness/scripts/g0_truth.py"
VALID_GATE_STATUSES = {
    "PASS",
    "WARN",
    "FAIL",
    "BLOCKED",
    "ERROR",
    "MISSING",
    "STALE",
    "NEEDS_REVIEW",
    "INVALID",
    "NOT_APPLICABLE",
    "PENDING",
}


class ContractError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _requirement_merkle(requirements: list[dict[str, Any]]) -> str:
    records = [f"{item['id']}:{item['sha256']}" for item in requirements]
    return hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()


def validate_contract(contract: dict[str, Any], *, file_hash: str | None = None) -> dict[str, Any]:
    if file_hash is not None and file_hash.lower() != EXPECTED_FILE_SHA256:
        return {"verdict": "BLOCKED", "reason": "contract_file_hash_mismatch"}
    try:
        _require(contract.get("schema_version") == "1.0", "schema_version")
        requirements = contract.get("requirements")
        vectors = contract.get("tamper_vectors")
        _require(isinstance(requirements, list), "requirements_not_array")
        _require(isinstance(vectors, list), "tamper_vectors_not_array")
        _require(len(requirements) == EXPECTED_REQUIREMENTS, "requirement_count")
        _require(len(vectors) == EXPECTED_TAMPER_VECTORS, "tamper_vector_count")
        ids: list[str] = []
        by_kind: Counter[str] = Counter()
        for item in requirements:
            _require(isinstance(item, dict), "requirement_not_object")
            _require(
                set(item) == {"id", "kind", "section", "source_line", "text", "sha256"},
                "requirement_fields",
            )
            requirement_id = item["id"]
            _require(bool(re.fullmatch(r"REQ-[A-Z0-9.-]+", requirement_id)), "requirement_id")
            _require(isinstance(item["text"], str) and item["text"], "requirement_text")
            actual_text_hash = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
            _require(actual_text_hash == item["sha256"], f"requirement_text_hash:{requirement_id}")
            ids.append(requirement_id)
            by_kind[item["kind"]] += 1
        _require(len(ids) == len(set(ids)), "duplicate_requirement_id")
        _require(_requirement_merkle(requirements) == EXPECTED_MERKLE_ROOT, "merkle_root")
        _require(contract.get("requirements_merkle_root") == EXPECTED_MERKLE_ROOT, "declared_merkle_root")
        expected_counts = contract.get("expected_counts", {})
        _require(expected_counts.get("total") == len(requirements), "expected_total")
        _require(dict(by_kind) == expected_counts.get("by_kind"), "expected_by_kind")
        vector_ids = [item.get("id") for item in vectors]
        _require(len(vector_ids) == len(set(vector_ids)), "duplicate_tamper_vector")
    except (ContractError, KeyError, TypeError) as exc:
        return {"verdict": "INVALID", "reason": str(exc)}
    return {
        "verdict": "PASS",
        "requirements": len(requirements),
        "tamper_vectors": len(vectors),
        "merkle_root": EXPECTED_MERKLE_ROOT,
    }


def _assurance_class(item: dict[str, Any]) -> str:
    section = item["section"]
    if section in {"SCIENCE", "WRITING", "ADOPTION"} or section == "G10":
        return "external_validation"
    if section == "G11":
        return "release_qualification"
    return "engineering_assurance"


def _required_for(assurance_class: str) -> list[str]:
    if assurance_class == "engineering_assurance":
        return ["engineering", "release", "goal"]
    if assurance_class == "external_validation":
        return ["promotion", "release", "goal"]
    return ["release", "goal"]


def instantiate_lock(contract: dict[str, Any], runner_path: Path) -> dict[str, Any]:
    result = validate_contract(contract, file_hash=EXPECTED_FILE_SHA256)
    if result["verdict"] != "PASS":
        raise ContractError(f"cannot instantiate invalid contract: {result}")
    runner_hash = sha256_file(runner_path)
    mappings: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for item in contract["requirements"]:
        gate_id = f"GATE-{item['id']}"
        assurance_class = _assurance_class(item)
        mappings.append({"requirement_id": item["id"], "gate_ids": [gate_id]})
        gates.append(
            {
                "id": gate_id,
                "requirement_ids": [item["id"]],
                "requirement_sha256": item["sha256"],
                "section": item["section"],
                "kind": item["kind"],
                "assurance_class": assurance_class,
                "required_for": _required_for(assurance_class),
                "runner": {
                    "path": "harness/scripts/verify_truth.py",
                    "sha256": runner_hash,
                    "command": [
                        "python",
                        "harness/scripts/verify_truth.py",
                        "gate",
                        "--gate-id",
                        gate_id,
                    ],
                },
                "input_manifest": "required: evidence/<phase>/artifact-manifest.json with SHA256",
                "oracle": {"requirement_text_sha256": item["sha256"], "allowed_verdict": "PASS"},
                "metric": {
                    "name": "binary_requirement_proof",
                    "numerator": "verified positive cases",
                    "denominator": "locked positive and negative cases",
                    "abstention": "reported separately",
                    "strata": "declared by capability scope",
                },
                "threshold": {"verdict": "PASS", "abstention": 0, "denominator_min": 1},
                "non_vacuity": {
                    "positive_control_required": True,
                    "negative_control_required_when_applicable": True,
                    "empty_corpus": "INVALID",
                },
                "initial_state": "PENDING",
            }
        )
    return {
        "schema_version": "1.0",
        "role": "frozen_phase_contract",
        "bootstrap": {
            "path": r"D:\科研软件制作\开发指导.bootstrap.json",
            "sha256": EXPECTED_FILE_SHA256,
            "requirements": EXPECTED_REQUIREMENTS,
            "tamper_vectors": EXPECTED_TAMPER_VECTORS,
            "merkle_root": EXPECTED_MERKLE_ROOT,
        },
        "mappings": mappings,
        "gates": gates,
    }



def _canonical_raw_file(path: Path, value: dict[str, Any]) -> str:
    atomic_write_json(path, value)
    return sha256_file(path)


def _expected_g0_report_set(candidate: dict[str, Any], root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for gate in sorted(candidate["gates"], key=lambda item: item["id"]):
        if gate["section"] != "G0":
            continue
        path = f"harness/evidence/G0/{gate['id']}.json"
        report = root / path
        entries.append({"gate_id": gate["id"], "path": path, "sha256": sha256_file(report) if report.is_file() else None})
    return {"schema_version": "1.0", "gate_reports": entries}


def _candidate_base(
    contract: dict[str, Any], root: Path, *, authoritative_lock_path: Path | None = None
) -> dict[str, Any]:
    authoritative = authoritative_lock_path or root / "harness" / "phase-contract.lock"
    if not authoritative.is_file():
        raise ContractError("authoritative_lock_missing")
    if validate_contract(contract, file_hash=EXPECTED_FILE_SHA256)["verdict"] != "PASS":
        raise ContractError("invalid_contract")
    candidate = copy.deepcopy(read_json(authoritative))
    candidate["role"] = CANDIDATE_ROLE
    candidate["status"] = "CANDIDATE"
    candidate["adjudication_status"] = CANDIDATE_STATUS
    truth = root / G0_TRUTH_PATH
    for gate in candidate["gates"]:
        if gate["section"] == "G0":
            gate["runner"] = {
                "path": G0_TRUTH_PATH,
                "sha256": sha256_file(truth),
                "command": ["python", G0_TRUTH_PATH, "--gate-id", gate["id"]],
            }
    return candidate


def generate_candidate_lock(
    contract: dict[str, Any],
    *,
    root: Path,
    lock_path: Path | None = None,
    bootstrap_path: Path | None = None,
    authoritative_lock_path: Path | None = None,
) -> dict[str, Any]:
    bootstrap_path = bootstrap_path or Path(r"D:\科研软件制作\开发指导.bootstrap.json")
    if not bootstrap_path.is_file() or sha256_file(bootstrap_path) != EXPECTED_FILE_SHA256:
        raise ContractError("bootstrap_path_or_hash")
    expected_path = root / CANDIDATE_LOCK_FILENAME
    if lock_path is not None and lock_path.resolve() != expected_path.resolve():
        raise ContractError("candidate_lock_path")
    candidate = _candidate_base(contract, root, authoritative_lock_path=authoritative_lock_path)
    lock_path = expected_path
    manifest = {
        "schema_version": "1.0",
        "role": CANDIDATE_ROLE,
        "status": CANDIDATE_STATUS,
        "lock_sha256": "",
    }
    candidate["candidate_manifest"] = {
        "path": CANDIDATE_MANIFEST_FILENAME,
        "sha256": "",
    }
    candidate["g0_report_set"] = {
        "path": G0_REPORT_SET_FILENAME,
        "sha256": "",
    }
    unsigned = copy.deepcopy(candidate)
    unsigned.pop("candidate_manifest")
    unsigned.pop("g0_report_set")
    manifest["lock_sha256"] = hashlib.sha256(canonical_json(unsigned)).hexdigest()
    candidate["candidate_manifest"]["sha256"] = _canonical_raw_file(root / CANDIDATE_MANIFEST_FILENAME, manifest)
    candidate["g0_report_set"]["sha256"] = _canonical_raw_file(
        root / G0_REPORT_SET_FILENAME, _expected_g0_report_set(candidate, root)
    )
    atomic_write_json(lock_path, candidate)
    return candidate


def _read_canonical_raw(path: Path) -> tuple[dict[str, Any], str] | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if raw != canonical_json(value) + b"\n":
        return None
    return value, hashlib.sha256(raw).hexdigest()


def validate_candidate_lock(
    candidate: dict[str, Any],
    contract: dict[str, Any],
    *,
    root: Path,
    bootstrap_path: Path | None = None,
    authoritative_lock_path: Path | None = None,
) -> dict[str, Any]:
    bootstrap_path = bootstrap_path or Path(r"D:\科研软件制作\开发指导.bootstrap.json")
    authoritative_lock_path = authoritative_lock_path or root / "harness" / "phase-contract.lock"
    if not bootstrap_path.is_file() or sha256_file(bootstrap_path) != EXPECTED_FILE_SHA256:
        return {"verdict": "BLOCKED", "reason": "bootstrap_path_or_hash"}
    if not authoritative_lock_path.is_file():
        return {"verdict": "BLOCKED", "reason": "authoritative_lock_missing"}
    if candidate.get("role") != CANDIDATE_ROLE or candidate.get("status") != "CANDIDATE":
        return {"verdict": "BLOCKED", "reason": "candidate_not_pending"}
    if candidate.get("adjudication_status") != CANDIDATE_STATUS:
        return {"verdict": "BLOCKED", "reason": "candidate_adjudication_status"}
    manifest = candidate.get("candidate_manifest", {})
    manifest_file = _read_canonical_raw(root / CANDIDATE_MANIFEST_FILENAME)
    if manifest.get("path") != CANDIDATE_MANIFEST_FILENAME or manifest_file is None:
        return {"verdict": "STALE", "reason": "candidate_manifest_missing_or_noncanonical"}
    manifest_content, manifest_hash = manifest_file
    if manifest.get("sha256") != manifest_hash:
        return {"verdict": "STALE", "reason": "candidate_manifest_hash"}
    report_set = candidate.get("g0_report_set", {})
    report_set_file = _read_canonical_raw(root / G0_REPORT_SET_FILENAME)
    if report_set.get("path") != G0_REPORT_SET_FILENAME or report_set_file is None:
        return {"verdict": "STALE", "reason": "g0_report_set_missing_or_noncanonical"}
    report_set_content, report_set_hash = report_set_file
    if report_set.get("sha256") != report_set_hash:
        return {"verdict": "STALE", "reason": "g0_report_set_hash"}
    lock_result = validate_lock(candidate, contract)
    if lock_result["verdict"] != "PASS":
        return lock_result
    expected = _candidate_base(contract, root, authoritative_lock_path=authoritative_lock_path)
    for key in ("schema_version", "bootstrap", "mappings", "gates"):
        if candidate.get(key) != expected.get(key):
            return {"verdict": "STALE", "reason": f"candidate_{key}_drift"}
    unsigned = copy.deepcopy(candidate)
    unsigned.pop("candidate_manifest", None)
    unsigned.pop("g0_report_set", None)
    if manifest_content != {
        "role": CANDIDATE_ROLE,
        "schema_version": "1.0",
        "status": CANDIDATE_STATUS,
        "lock_sha256": hashlib.sha256(canonical_json(unsigned)).hexdigest(),
    }:
        return {"verdict": "STALE", "reason": "candidate_manifest_lock_hash"}
    if report_set_content != _expected_g0_report_set(candidate, root):
        return {"verdict": "STALE", "reason": "g0_report_set_content"}
    return {"verdict": "CANDIDATE"}


def validate_lock(lock: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    try:
        requirement_ids = {item["id"] for item in contract["requirements"]}
        mappings = lock.get("mappings")
        gates = lock.get("gates")
        _require(isinstance(mappings, list) and isinstance(gates, list), "lock_arrays")
        gate_ids = [gate.get("id") for gate in gates]
        _require(len(gate_ids) == len(set(gate_ids)), "duplicate_gate_id")
        gate_set = set(gate_ids)
        mapped: list[str] = []
        for mapping in mappings:
            requirement_id = mapping.get("requirement_id")
            cited = mapping.get("gate_ids")
            _require(requirement_id in requirement_ids, "mapping_unknown_requirement")
            _require(isinstance(cited, list) and cited, f"zero_gates:{requirement_id}")
            _require(set(cited) <= gate_set, f"mapping_unknown_gate:{requirement_id}")
            mapped.append(requirement_id)
        _require(len(mapped) == len(set(mapped)), "duplicate_requirement_mapping")
        _require(set(mapped) == requirement_ids, "requirement_coverage")
        for gate in gates:
            cited = gate.get("requirement_ids")
            _require(isinstance(cited, list) and cited, f"gate_without_requirement:{gate.get('id')}")
            _require(set(cited) <= requirement_ids, f"gate_unknown_requirement:{gate.get('id')}")
            threshold = gate.get("threshold", {})
            _require(int(threshold.get("denominator_min", 0)) > 0, "empty_required_corpus")
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        return {"verdict": "INVALID", "reason": str(exc)}
    return {
        "verdict": "PASS",
        "requirements": len(requirement_ids),
        "gates": len(gates),
        "coverage_numerator": len(mapped),
        "coverage_denominator": len(requirement_ids),
    }


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _safe_report_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and not any(part in {"", ".", ".."} for part in path.parts)


def validate_gate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate the non-vacuous, signature-bindable G0 gate-report schema."""
    required_fields = {
        "schema_version", "gate_id", "requirement_ids", "requirement_sha256", "runner_sha256",
        "phase", "verdict", "required", "metrics", "runner_receipt", "root_contract_receipt",
        "root_contract_sha256", "input_artifacts", "input_manifest_sha256", "output_manifest",
        "output_manifest_sha256", "checks", "artifacts", "external_validation", "release_qualification",
    }
    if not isinstance(report, dict) or set(report) != required_fields:
        return {"verdict": "INVALID", "reason": "gate_report_fields"}
    status = report.get("verdict")
    if status not in VALID_GATE_STATUSES:
        return {"verdict": "INVALID", "reason": "unknown_gate_status"}
    if report.get("schema_version") != "1.0" or report.get("phase") != "G0" or not isinstance(report.get("gate_id"), str) or not report["gate_id"]:
        return {"verdict": "INVALID", "reason": "gate_report_identity"}
    requirement_ids = report.get("requirement_ids")
    if not isinstance(requirement_ids, list) or not requirement_ids or any(not isinstance(item, str) or not item for item in requirement_ids) or len(requirement_ids) != len(set(requirement_ids)):
        return {"verdict": "INVALID", "reason": "gate_report_requirements"}
    if not _valid_sha256(report.get("requirement_sha256")) or not _valid_sha256(report.get("runner_sha256")) or not _valid_sha256(report.get("root_contract_sha256")):
        return {"verdict": "INVALID", "reason": "gate_report_hashes"}
    if not isinstance(report.get("required"), bool) or not _safe_report_relative_path(report.get("runner_receipt")) or not _safe_report_relative_path(report.get("root_contract_receipt")):
        return {"verdict": "INVALID", "reason": "gate_report_receipt_paths"}
    metrics = report.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != {"numerator", "denominator", "strata", "abstentions"}:
        return {"verdict": "INVALID", "reason": "gate_report_metrics"}
    numerator, denominator, abstentions = metrics.get("numerator"), metrics.get("denominator"), metrics.get("abstentions")
    strata = metrics.get("strata")
    if type(numerator) is not int or type(denominator) is not int or type(abstentions) is not int or denominator <= 0 or numerator < 0 or numerator > denominator or abstentions < 0:
        return {"verdict": "INVALID", "reason": "empty_required_corpus_or_denominator"}
    if not isinstance(strata, list) or not strata or any(not isinstance(item, str) or not item for item in strata) or len(strata) != len(set(strata)):
        return {"verdict": "INVALID", "reason": "gate_report_strata"}
    checks = report.get("checks")
    if not isinstance(checks, dict) or not checks or any(not isinstance(key, str) or not key or value not in VALID_GATE_STATUSES for key, value in checks.items()):
        return {"verdict": "INVALID", "reason": "gate_report_checks"}
    def validate_artifacts(value: Any, name: str) -> str | None:
        if not isinstance(value, list) or not value:
            return name
        for item in value:
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
                return name
            if not isinstance(item["path"], str) or not item["path"] or not _valid_sha256(item["sha256"]) or type(item["size"]) is not int or item["size"] < 0:
                return name
        return None
    artifact_error = validate_artifacts(report.get("input_artifacts"), "gate_report_input_artifacts") or validate_artifacts(report.get("artifacts"), "gate_report_artifacts")
    if artifact_error:
        return {"verdict": "INVALID", "reason": artifact_error}
    if not _valid_sha256(report.get("input_manifest_sha256")) or not _valid_sha256(report.get("output_manifest_sha256")):
        return {"verdict": "INVALID", "reason": "gate_report_manifest_hashes"}
    output_manifest = report.get("output_manifest")
    if not isinstance(output_manifest, dict) or set(output_manifest) != {"checks", "metrics", "verdict"} or output_manifest != {"checks": checks, "metrics": metrics, "verdict": status}:
        return {"verdict": "INVALID", "reason": "gate_report_output_manifest"}
    if not isinstance(report.get("external_validation"), str) or not report["external_validation"] or not isinstance(report.get("release_qualification"), str) or not report["release_qualification"]:
        return {"verdict": "INVALID", "reason": "gate_report_qualification_fields"}
    if report["external_validation"] == "pending" and report["release_qualification"] == "accepted":
        return {"verdict": "INVALID", "reason": "external_pending_used_as_release_pass"}
    if status == "PASS" and (numerator != denominator or abstentions != 0 or any(value != "PASS" for value in checks.values())):
        return {"verdict": "INVALID", "reason": "pass_without_all_checks_or_nonvacuous_metrics"}
    return {"verdict": status}


def run_tamper_vectors(contract: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    outcomes: dict[str, dict[str, Any]] = {}

    def record(vector_id: str, actual: str, checker: dict[str, Any] | None = None) -> None:
        entry: dict[str, Any] = {"actual": actual}
        if checker is not None:
            entry["checker"] = checker
        outcomes[vector_id] = entry

    record("TV-001", validate_contract(contract, file_hash="0" * 64)["verdict"])

    mutated = copy.deepcopy(contract)
    mutated["requirements"].pop()
    record("TV-002", validate_contract(mutated)["verdict"])

    mutated = copy.deepcopy(contract)
    mutated["requirements"][1]["id"] = mutated["requirements"][0]["id"]
    record("TV-003", validate_contract(mutated)["verdict"])

    mutated = copy.deepcopy(contract)
    mutated["requirements"][0]["text"] += "tamper"
    record("TV-004", validate_contract(mutated)["verdict"])

    mutated = copy.deepcopy(contract)
    mutated["requirements"][0]["text"] += "tamper"
    mutated["requirements"][0]["sha256"] = hashlib.sha256(
        mutated["requirements"][0]["text"].encode("utf-8")
    ).hexdigest()
    record("TV-005", validate_contract(mutated)["verdict"])

    mutated_lock = copy.deepcopy(lock)
    mutated_lock["mappings"][0]["gate_ids"] = []
    record("TV-006", validate_lock(mutated_lock, contract)["verdict"])

    record(
        "TV-007",
        validate_gate_report({"verdict": "PASS", "runner_receipt": "x", "required": True, "metrics": {"denominator": 0}})["verdict"],
    )
    record(
        "TV-008",
        validate_gate_report({"verdict": "PASS", "required": True, "metrics": {"denominator": 1}})["verdict"],
    )
    record(
        "TV-009",
        validate_gate_report({"verdict": "GREEN", "required": True, "metrics": {"denominator": 1}})["verdict"],
    )
    record(
        "TV-010",
        validate_gate_report(
            {
                "verdict": "PASS",
                "runner_receipt": "x",
                "required": True,
                "metrics": {"denominator": 1},
                "external_validation": "pending",
                "release_qualification": "accepted",
            }
        )["verdict"],
    )

    boundary_input = {
        "before": {"harness/evidence/G0/inside.json": "before", "backend/main.py": "before"},
        "after": {"harness/evidence/G0/inside.json": "after", "backend/main.py": "after"},
        "allowed": ["harness/**"],
    }
    boundary_result = evaluate_allowed_paths(**boundary_input)
    record(
        "TV-011",
        str(boundary_result["verdict"]),
        {
            "name": "evaluate_allowed_paths",
            "input_sha256": hashlib.sha256(canonical_json(boundary_input)).hexdigest(),
            "denominator": boundary_result["denominator"],
        },
    )

    provenance_input = [
        {
            "source_repository": "tamper/repository",
            "upstream_commit": "0000000",
            "source_path": "forbidden.py",
            "license_expression": "UNKNOWN",
            "reuse_mode": "direct_reuse",
            "decision": "approved",
            "obligations": [],
            "resolved_obligations": [],
            "license_decision_receipt": None,
        }
    ]
    provenance_result = evaluate_source_provenance(provenance_input)
    record(
        "TV-012",
        str(provenance_result["verdict"]),
        {
            "name": "evaluate_source_provenance",
            "input_sha256": hashlib.sha256(canonical_json(provenance_input)).hexdigest(),
            "denominator": provenance_result["denominator"],
        },
    )

    expected = {item["id"]: item["expected"] for item in contract["tamper_vectors"]}
    cases = [
        {
            "id": vector_id,
            "expected": expected[vector_id],
            **outcome,
            "pass": outcome["actual"] == expected[vector_id],
        }
        for vector_id, outcome in sorted(outcomes.items())
    ]
    return {
        "verdict": "PASS" if all(case["pass"] for case in cases) else "FAIL",
        "numerator": sum(case["pass"] for case in cases),
        "denominator": len(cases),
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "instantiate", "verify-lock", "tamper-test"))
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--os-hash")
    args = parser.parse_args()

    contract = read_json(args.contract)
    if args.command == "verify":
        actual_hash = args.os_hash or sha256_file(args.contract)
        result = validate_contract(contract, file_hash=actual_hash)
    elif args.command == "instantiate":
        if not args.lock or not args.runner:
            parser.error("instantiate requires --lock and --runner")
        result = instantiate_lock(contract, args.runner)
        atomic_write_json(args.lock, result)
        result = validate_lock(result, contract)
    elif args.command == "verify-lock":
        if not args.lock:
            parser.error("verify-lock requires --lock")
        result = validate_lock(read_json(args.lock), contract)
    else:
        if not args.lock:
            parser.error("tamper-test requires --lock")
        result = run_tamper_vectors(contract, read_json(args.lock))
    if args.output:
        atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
