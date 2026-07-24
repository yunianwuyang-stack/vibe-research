from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from harness.v2.scripts import core
from harness.v2.scripts.supervisor import SupervisorConfig, run_supervised


DEFAULT_REQUIREMENT_IDS = [
    "REQ-P0-02",
    "REQ-P0-03",
    "REQ-DOD-17",
    *(f"REQ-P0-{index:02d}" for index in range(10, 18)),
]

TEST_TASK_IDS = [
    "P0-CORE-TEST",
    "TASK-UPSTREAM",
    "TASK-DOWNSTREAM",
    "TASK-EARLY-DOD",
    "TASK-ROOT",
    "TASK-DEPENDENT",
    "FINDING-FIX-TASK",
]


_DIGEST_PREIMAGES: dict[str, bytes] = {}


def digest(label: str) -> str:
    value = label.encode("utf-8")
    result = core.sha256_bytes(value)
    _DIGEST_PREIMAGES[result] = value
    return result


CHECKER_SOURCE = b"""from __future__ import annotations
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('--input-manifest', required=True)
parser.add_argument('--oracle', required=True)
parser.add_argument('--receipt-id', required=True)
parser.add_argument('--exit-code', type=int, default=0)
args = parser.parse_args()
inputs = json.load(open(args.input_manifest, encoding='utf-8'))
oracle = json.load(open(args.oracle, encoding='utf-8'))
print(json.dumps({'receipt_id': args.receipt_id, 'input_count': len(inputs['bindings']), 'oracle': oracle['oracle']}, sort_keys=True))
raise SystemExit(args.exit_code)
"""


def make_contract(
    task_id: str = "P0-CORE-TEST",
    *,
    requirements: list[str] | None = None,
    route_attempts: int = 2,
    total_attempts: int = 4,
    fallbacks: list[object] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    selected_requirements = requirements or ["REQ-P0-02"]
    return {
        "schema_version": 1,
        "id": task_id,
        "requirement_ids": selected_requirements,
        "objective": "Exercise the real harness state machine.",
        "depends_on": depends_on or [],
        "allowed_paths": ["src/task.txt"],
        "inputs": {
            "manifest": "harness/v2/manifest.json",
            "manifest_sha256": digest("manifest"),
        },
        "source_decision_ids": [],
        "license_scope_hash": digest("license"),
        "reuse_mode": "original_implementation",
        "outputs": ["harness/v2/events.jsonl"],
        "risk": "high_integrity_control_plane",
        "executor": "builder-agent",
        "verifier": "verifier-agent",
        "retry_policy": {
            "max_attempts": route_attempts,
            "max_total_attempts": total_attempts,
            "causal_delta_required": True,
        },
        "fallbacks": fallbacks or [],
        "acceptance_commands": ["python -m pytest tests/test_harness_v2_core.py"],
        "deterministic_checkers": [
            f"CHK-{requirement_id}" for requirement_id in selected_requirements
        ],
        "scientific_checker": {
            "applicable": False,
            "reason": "Control-plane integrity task",
        },
        "non_vacuity": "Positive control and injected mutations must both execute.",
        "real_e2e": "Append, fsync, replay, and atomically project a real temporary journal.",
        "recovery": "Recover a projection from the durable journal after injected failure.",
        "done_evidence": "harness/v2/evidence/P0/P0-CORE-TEST",
    }


def make_receipt(
    journal: core.Journal,
    receipt_id: str,
    task_id: str,
    requirement_ids: list[str],
    *,
    source_hash: str,
    dependencies: list[str] | None = None,
    outcome: str = "VERIFIED_PASS",
    metadata: dict[str, object] | None = None,
    exit_code: int = 0,
    checker_id: str | None = None,
    environment_hash: str | None = None,
) -> dict[str, object]:
    if len(requirement_ids) != 1:
        raise AssertionError("test receipt helper creates one-requirement receipts")
    requirement_id = requirement_ids[0]
    state = journal.rebuild_state()
    task = state["tasks"][task_id]
    authority = journal.load_authority()
    selected_checker = checker_id or f"CHK-{requirement_id}"
    checker_entry = authority["checkers"].get(selected_checker, {})
    implementation_relative = checker_entry.get("implementation_path")
    checker_path = (
        journal.project_root / implementation_relative
        if isinstance(implementation_relative, str)
        else journal.project_root / "missing-checker.py"
    )
    checker_bytes = checker_path.read_bytes() if checker_path.is_file() else b"missing-checker"
    oracle_bytes = f"oracle:{requirement_id}".encode("utf-8")
    checker_hash = core.sha256_bytes(checker_bytes)
    oracle_hash = core.sha256_bytes(oracle_bytes)
    inputs = {
        "requirements_spec_hash": authority["requirements_spec_hash"],
        "source_tree_manifest_hash": source_hash,
        "schema_migration_hash": digest("schema"),
        "dependency_lock_hash": digest("lock"),
        "config_hash": digest("config"),
        "environment_hash": environment_hash or digest("environment"),
        "corpus_hash": digest("corpus"),
        "evaluator_hash": digest("evaluator"),
        "artifact_hash": digest(f"artifact:{receipt_id}"),
        "installer_hash": digest("not-applicable-installer-binding"),
    }
    evidence_dir = journal.evidence_root / receipt_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    bindings: list[dict[str, object]] = []
    for name in core.RECEIPT_INPUT_BINDINGS:
        expected_hash = inputs[name]
        if name == "requirements_spec_hash":
            bindings.append({"name": name, "path": None, "sha256": expected_hash})
            continue
        content = _DIGEST_PREIMAGES.get(expected_hash, str(expected_hash).encode("ascii"))
        binding_path = evidence_dir / f"input-{name}.bin"
        binding_path.write_bytes(content)
        actual_hash = core.sha256_bytes(content)
        inputs[name] = actual_hash
        bindings.append(
            {
                "name": name,
                "path": binding_path.relative_to(journal.project_root).as_posix(),
                "sha256": actual_hash,
            }
        )
    input_manifest_path = evidence_dir / "input-manifest.json"
    input_manifest = {
        "schema": core.INPUT_MANIFEST_SCHEMA,
        "receipt_id": receipt_id,
        "bindings": bindings,
    }
    input_manifest_bytes = (
        json.dumps(input_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    input_manifest_path.write_bytes(input_manifest_bytes)
    input_manifest_hash = core.sha256_bytes(input_manifest_bytes)

    oracle_path = evidence_dir / "oracle.json"
    oracle_path.write_text(
        json.dumps({"oracle": oracle_bytes.decode("utf-8")}, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    oracle_bytes = oracle_path.read_bytes()
    oracle_hash = core.sha256_bytes(oracle_bytes)
    supervisor_path = evidence_dir / "supervisor.json"
    command_argv = [
        sys.executable,
        str(checker_path.resolve()),
        "--input-manifest",
        str(input_manifest_path.resolve()),
        "--oracle",
        str(oracle_path.resolve()),
        "--receipt-id",
        receipt_id,
        "--exit-code",
        str(exit_code),
    ]
    supervisor = run_supervised(
        SupervisorConfig(
            argv=command_argv,
            cwd=journal.project_root,
            allowed_cwd_roots=[journal.project_root],
            env={},
            allowed_env_keys=[],
            deadline_seconds=10,
            heartbeat_seconds=0.05,
        ),
        receipt_path=supervisor_path,
    )
    progress_path = supervisor_path.with_name(supervisor_path.name + ".progress.json")
    supervisor_bytes = supervisor_path.read_bytes()
    progress_bytes = progress_path.read_bytes()
    stdout_bytes = supervisor["stdout"]["redacted_text"].encode("utf-8")
    stderr_bytes = supervisor["stderr"]["redacted_text"].encode("utf-8")
    assert core.sha256_bytes(stdout_bytes) == supervisor["stdout"]["raw_sha256"]
    assert core.sha256_bytes(stderr_bytes) == supervisor["stderr"]["raw_sha256"]
    extra_metadata = dict(metadata or {})
    receipt_kind = str(extra_metadata.pop("receipt_kind", "requirement_verification"))
    receipt_metadata: dict[str, object] = {
        "receipt_kind": receipt_kind,
        "executor_id": task["contract"]["executor"],
        "verifier_id": task["contract"]["verifier"],
    }
    if receipt_kind == "requirement_verification":
        receipt_metadata["attempt_id"] = extra_metadata.pop(
            "attempt_id", task["attempts"][-1]["attempt_id"]
        )
    receipt_metadata.update(extra_metadata)
    checker = {
        "checker_id": selected_checker,
        "checker_hash": checker_hash,
        "oracle_hash": oracle_hash,
        "command_argv": ["python", "checker.py", requirement_id],
        "exit_code": supervisor["exit_code"],
        "stdout_hash": supervisor["stdout"]["raw_sha256"],
        "stderr_hash": supervisor["stderr"]["raw_sha256"],
        "supervisor_receipt_hash": core.sha256_bytes(supervisor_bytes),
        "supervisor_progress_hash": core.sha256_bytes(progress_bytes),
    }
    checker["command_argv"] = supervisor["command"]["argv"]
    derivation = {
        **checker,
        "outcome": outcome,
        "requirement_id": requirement_id,
        "input_manifest_hash": input_manifest_hash,
        "inputs": inputs,
    }
    verdict_bytes = core.canonical_json_bytes(derivation)
    checker["derived_verdict_hash"] = core.sha256_bytes(verdict_bytes)
    raw_artifacts = {
        "checker": ("checker.py", checker_bytes),
        "oracle": ("oracle.json", oracle_bytes),
        "input_manifest": ("input-manifest.json", input_manifest_bytes),
        "supervisor": ("supervisor.json", supervisor_bytes),
        "supervisor_progress": ("supervisor.json.progress.json", progress_bytes),
        "stdout": ("stdout.log", stdout_bytes),
        "stderr": ("stderr.log", stderr_bytes),
        "verdict": ("verdict.json", verdict_bytes),
    }
    artifacts = []
    for role, (name, content) in raw_artifacts.items():
        path = evidence_dir / name
        path.write_bytes(content)
        artifacts.append(
            {
                "role": role,
                "path": path.relative_to(journal.project_root).as_posix(),
                "sha256": core.sha256_bytes(content),
            }
        )
    manifest_path = evidence_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "receipt_id": receipt_id,
        "requirement_id": requirement_id,
        "task_id": task_id,
        "artifacts": artifacts,
    }
    manifest_bytes = core.canonical_json_bytes(manifest) + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    evidence_hash = core.sha256_bytes(manifest_bytes)
    receipt: dict[str, object] = {
        "schema_version": 1,
        "id": receipt_id,
        "task_id": task_id,
        "requirement_ids": requirement_ids,
        "inputs": inputs,
        "dependencies": dependencies or [],
        "outcome": outcome,
        "evidence_hash": evidence_hash,
        "evidence_manifest_path": manifest_path.relative_to(
            journal.project_root
        ).as_posix(),
        "evidence_manifest_hash": evidence_hash,
        "input_manifest_path": input_manifest_path.relative_to(
            journal.project_root
        ).as_posix(),
        "input_manifest_hash": input_manifest_hash,
        "metadata": receipt_metadata,
    }
    if outcome == "VERIFIED_PASS":
        receipt["checker"] = checker
    return receipt


def receipt_derivation(receipt: dict[str, object]) -> dict[str, object]:
    checker = receipt["checker"]
    return {
        "checker_id": checker["checker_id"],
        "checker_hash": checker["checker_hash"],
        "oracle_hash": checker["oracle_hash"],
        "command_argv": checker["command_argv"],
        "exit_code": checker["exit_code"],
        "stdout_hash": checker["stdout_hash"],
        "stderr_hash": checker["stderr_hash"],
        "supervisor_receipt_hash": checker["supervisor_receipt_hash"],
        "supervisor_progress_hash": checker["supervisor_progress_hash"],
        "input_manifest_hash": receipt["input_manifest_hash"],
        "outcome": receipt["outcome"],
        "requirement_id": receipt["requirement_ids"][0],
        "inputs": receipt["inputs"],
    }


def rederive_receipt(receipt: dict[str, object]) -> None:
    receipt["checker"]["derived_verdict_hash"] = core.sha256_json(
        receipt_derivation(receipt)
    )


def tamper_supervisor_and_rebind(
    journal: core.Journal,
    receipt: dict[str, object],
    mutator,
) -> None:
    manifest_path = journal.project_root / receipt["evidence_manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["role"]: item for item in manifest["artifacts"]}
    supervisor_path = journal.project_root / artifacts["supervisor"]["path"]
    progress_path = journal.project_root / artifacts["supervisor_progress"]["path"]
    supervisor = json.loads(supervisor_path.read_text(encoding="utf-8"))
    mutator(supervisor)
    supervisor_bytes = (
        json.dumps(supervisor, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    supervisor_path.write_bytes(supervisor_bytes)
    supervisor_hash = core.sha256_bytes(supervisor_bytes)

    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["receipt_sha256"] = supervisor_hash
    progress_bytes = (
        json.dumps(progress, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    progress_path.write_bytes(progress_bytes)
    progress_hash = core.sha256_bytes(progress_bytes)
    receipt["checker"]["supervisor_receipt_hash"] = supervisor_hash
    receipt["checker"]["supervisor_progress_hash"] = progress_hash
    rederive_receipt(receipt)

    verdict_path = journal.project_root / artifacts["verdict"]["path"]
    verdict_bytes = core.canonical_json_bytes(receipt_derivation(receipt))
    verdict_path.write_bytes(verdict_bytes)
    artifacts["supervisor"]["sha256"] = supervisor_hash
    artifacts["supervisor_progress"]["sha256"] = progress_hash
    artifacts["verdict"]["sha256"] = core.sha256_bytes(verdict_bytes)
    manifest_bytes = core.canonical_json_bytes(manifest) + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    receipt["evidence_hash"] = core.sha256_bytes(manifest_bytes)
    receipt["evidence_manifest_hash"] = receipt["evidence_hash"]


def _invert(mapping: dict[str, list[str]], targets: list[str]) -> dict[str, list[str]]:
    result = {target: [] for target in targets}
    for source, values in mapping.items():
        for value in values:
            result.setdefault(value, []).append(source)
    return {key: sorted(values) for key, values in sorted(result.items())}


def write_authority(
    project_root: Path,
    *,
    dependencies: dict[str, list[str]] | None = None,
    checker_status: str = "implemented",
    completion_suffix: str = "",
) -> tuple[Path, Path]:
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "src").mkdir(parents=True, exist_ok=True)
    task_input = project_root / "src" / "task.txt"
    if not task_input.exists():
        task_input.write_text("task input v1\n", encoding="utf-8", newline="\n")
    (project_root / "evidence").mkdir(parents=True, exist_ok=True)
    checker_root = project_root / "checkers"
    checker_root.mkdir(parents=True, exist_ok=True)
    requirement_ids = list(DEFAULT_REQUIREMENT_IDS)
    checker_paths: dict[str, Path] = {}
    for requirement_id in requirement_ids:
        checker_path = checker_root / f"{requirement_id}.py"
        checker_path.write_bytes(CHECKER_SOURCE)
        checker_paths[requirement_id] = checker_path
    requirement_dependencies = {
        requirement_id: sorted((dependencies or {}).get(requirement_id, []))
        for requirement_id in requirement_ids
    }
    requirement_checkers = {
        requirement_id: [f"CHK-{requirement_id}"] for requirement_id in requirement_ids
    }
    requirement_evaluators = {
        requirement_id: [f"EVAL-{requirement_id}"] for requirement_id in requirement_ids
    }
    requirement_tasks = {
        requirement_id: sorted(
            {
                "TASK-FINAL-QUALIFICATION"
                if requirement_id.startswith("REQ-DOD-")
                else "TASK-P0",
                *TEST_TASK_IDS,
            }
        )
        for requirement_id in requirement_ids
    }
    required_by = _invert(requirement_dependencies, requirement_ids)
    requirements = []
    for requirement_id in requirement_ids:
        phase = "DOD" if requirement_id.startswith("REQ-DOD-") else "P0"
        requirements.append(
            {
                "id": requirement_id,
                "phase": phase,
                "ordinal": int(requirement_id.rsplit("-", 1)[1]),
                "definition_kind": "test_authority",
                "completion_text": (
                    f"Machine evidence for {requirement_id}.{completion_suffix}"
                ),
                "literal_thresholds": [],
                "threshold_refs": [],
                "checker_ids": requirement_checkers[requirement_id],
                "evaluator_ids": requirement_evaluators[requirement_id],
                "task_ids": requirement_tasks[requirement_id],
                "depends_on": requirement_dependencies[requirement_id],
                "required_by": required_by[requirement_id],
                "dod_ids": [],
                "covered_requirement_ids": [],
                "state": "NOT_RUN",
                "receipt_ids": [],
            }
        )
    checker_registry = [
        {
            "id": f"CHK-{requirement_id}",
            "requirement_ids": [requirement_id],
            "implementation_status": checker_status,
            "implementation_path": checker_paths[requirement_id]
            .relative_to(project_root)
            .as_posix(),
            "implementation_hash": core.sha256_bytes(CHECKER_SOURCE),
        }
        for requirement_id in requirement_ids
    ]
    evaluator_registry = [
        {
            "id": f"EVAL-{requirement_id}",
            "requirement_ids": [requirement_id],
            "implementation_status": "implemented",
        }
        for requirement_id in requirement_ids
    ]
    task_registry = [
        {
            "id": task_id,
            "requirement_ids": sorted(
                requirement_id
                for requirement_id, task_ids in requirement_tasks.items()
                if task_id in task_ids
            ),
            "registration_status": "implemented",
        }
        for task_id in ("TASK-P0", "TASK-FINAL-QUALIFICATION", *TEST_TASK_IDS)
        if any(task_id in values for values in requirement_tasks.values())
    ]
    traceability = {
        "requirement_to_checkers": requirement_checkers,
        "checker_to_requirements": _invert(
            requirement_checkers, [entry["id"] for entry in checker_registry]
        ),
        "requirement_to_evaluators": requirement_evaluators,
        "evaluator_to_requirements": _invert(
            requirement_evaluators, [entry["id"] for entry in evaluator_registry]
        ),
        "requirement_to_tasks": requirement_tasks,
        "task_to_requirements": _invert(
            requirement_tasks, [entry["id"] for entry in task_registry]
        ),
        "requirement_dependencies": requirement_dependencies,
        "requirement_required_by": required_by,
    }
    registry = {
        "schema_version": 1,
        "generator": "test-authority",
        "spec_normalization": core.REQUIREMENTS_CANONICALIZATION,
        "source": {"path": "development-guide.md"},
        "requirement_count": len(requirements),
        "requirements": requirements,
        "threshold_registry": [],
        "checker_registry": checker_registry,
        "evaluator_registry": evaluator_registry,
        "task_registry": task_registry,
        "traceability": traceability,
        "registry_policies": {"test": "frozen"},
    }
    registry["requirements_spec_hash"] = core.sha256_bytes(
        core._requirements_canonical_bytes(core._requirements_spec_projection(registry))
    )
    registry_path = project_root / "requirements.json"
    registry_bytes = (
        json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    registry_path.write_bytes(registry_bytes)
    lock = {
        "schema_version": 1,
        "canonicalization": core.REQUIREMENTS_CANONICALIZATION,
        "requirements_spec_hash": registry["requirements_spec_hash"],
        "requirements_document_sha256": core.sha256_bytes(registry_bytes),
        "requirement_count": len(requirements),
    }
    lock_path = project_root / "requirements.lock.json"
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return registry_path, lock_path


def make_journal(
    tmp_path: Path,
    *,
    dependencies: dict[str, list[str]] | None = None,
    checker_status: str = "implemented",
) -> core.Journal:
    registry, lock = write_authority(
        tmp_path, dependencies=dependencies, checker_status=checker_status
    )
    return core.Journal(
        tmp_path / "events.jsonl",
        tmp_path / "state.json",
        project_root=tmp_path,
        evidence_root=tmp_path / "evidence",
        requirements_path=registry,
        requirements_lock_path=lock,
    )


def persist_authority(
    registry_path: Path, lock_path: Path, registry: dict[str, object]
) -> None:
    registry["requirements_spec_hash"] = core.sha256_bytes(
        core._requirements_canonical_bytes(core._requirements_spec_projection(registry))
    )
    registry_bytes = (
        json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    registry_path.write_bytes(registry_bytes)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["requirements_spec_hash"] = registry["requirements_spec_hash"]
    lock["requirements_document_sha256"] = core.sha256_bytes(registry_bytes)
    lock["requirement_count"] = registry["requirement_count"]
    lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def register_task(journal: core.Journal, contract: dict[str, object]) -> None:
    for requirement_id in contract["requirement_ids"]:
        journal.declare_requirement(requirement_id)
    journal.register_task(contract)


def make_causal_receipt(
    journal: core.Journal,
    receipt_id: str,
    task_id: str,
    requirement_id: str,
    *,
    failure_signature: str,
    environment_hash: str,
) -> dict[str, object]:
    state = journal.rebuild_state()
    prior_attempt = state["tasks"][task_id]["attempts"][-1]
    after_components = journal.capture_task_inputs(task_id)
    after_input_hash = core._input_components_hash(after_components)
    metadata = {
        "receipt_kind": "causal_delta_verification",
        "prior_attempt_id": prior_attempt["attempt_id"],
        "failure_signature": failure_signature,
        "before_input_hash": prior_attempt["input_hash"],
        "before_environment_hash": prior_attempt["environment_hash"],
        "after_input_hash": after_input_hash,
        "after_environment_hash": environment_hash,
        "changed_components": core._component_delta(
            prior_attempt["input_components"], after_components
        ),
    }
    return make_receipt(
        journal,
        receipt_id,
        task_id,
        [requirement_id],
        source_hash=after_input_hash,
        metadata=metadata,
        environment_hash=environment_hash,
    )


def test_canonical_json_and_task_contract_are_deterministic() -> None:
    left = {"z": [1, 1.0, 1e-7], "a": "科研"}
    right = {"a": "科研", "z": [1, 1.0, 0.0000001]}
    assert core.canonical_json(left) == core.canonical_json(right)
    assert core.sha256_json(left) == core.sha256_json(right)
    normalized = core.validate_task_contract(make_contract())
    assert normalized["retry_policy"]["max_attempts"] == 2
    with pytest.raises(core.ValidationError, match="NaN"):
        core.canonical_json(float("nan"))


def test_contract_rejects_missing_controls_duplicate_ids_and_unsafe_paths() -> None:
    contract = make_contract()
    del contract["real_e2e"]
    with pytest.raises(core.ValidationError, match="missing"):
        core.validate_task_contract(contract)

    unsafe = make_contract()
    unsafe["allowed_paths"] = ["../outside.py"]
    with pytest.raises(core.ValidationError, match="project-relative"):
        core.validate_task_contract(unsafe)

    contracts = [make_contract("TASK-A"), make_contract("TASK-A")]
    with pytest.raises(core.ValidationError, match="duplicate task"):
        core.validate_task_contracts(contracts)


def test_journal_rejects_tasks_outside_frozen_task_edges(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    unknown = make_contract("TASK-NOT-FROZEN", requirements=["REQ-P0-02"])

    with pytest.raises(core.ValidationError, match="absent from the frozen"):
        journal.register_task(unknown)


def test_journal_rejects_requirement_missing_from_task_forward_edge(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    registry = json.loads(journal.requirements_path.read_text(encoding="utf-8"))
    requirement = next(
        item for item in registry["requirements"] if item["id"] == "REQ-P0-03"
    )
    requirement["task_ids"].remove("P0-CORE-TEST")
    registry["traceability"]["requirement_to_tasks"]["REQ-P0-03"].remove(
        "P0-CORE-TEST"
    )
    registry["traceability"]["task_to_requirements"]["P0-CORE-TEST"].remove(
        "REQ-P0-03"
    )
    task_entry = next(
        item
        for item in registry["task_registry"]
        if item["id"] == "P0-CORE-TEST"
    )
    task_entry["requirement_ids"].remove("REQ-P0-03")
    persist_authority(
        journal.requirements_path, journal.requirements_lock_path, registry
    )
    journal.declare_requirement("REQ-P0-02")
    journal.declare_requirement("REQ-P0-03")
    contract = make_contract(requirements=["REQ-P0-02", "REQ-P0-03"])

    with pytest.raises(core.ValidationError, match="frozen task edges"):
        journal.register_task(contract)


def test_journal_rejects_planned_or_contract_hash_drifted_task(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    registry = json.loads(journal.requirements_path.read_text(encoding="utf-8"))
    task_entry = next(
        item
        for item in registry["task_registry"]
        if item["id"] == "P0-CORE-TEST"
    )
    task_entry["registration_status"] = "planned"
    persist_authority(
        journal.requirements_path, journal.requirements_lock_path, registry
    )
    journal.declare_requirement("REQ-P0-02")
    with pytest.raises(core.IntegrityError, match="not implemented"):
        journal.register_task(make_contract())

    journal = make_journal(tmp_path / "hash-drift")
    registry = json.loads(journal.requirements_path.read_text(encoding="utf-8"))
    task_entry = next(
        item
        for item in registry["task_registry"]
        if item["id"] == "P0-CORE-TEST"
    )
    task_entry["contract_hash"] = digest("different-contract")
    persist_authority(
        journal.requirements_path, journal.requirements_lock_path, registry
    )
    journal.declare_requirement("REQ-P0-02")
    with pytest.raises(core.IntegrityError, match="contract hash differs"):
        journal.register_task(make_contract())


def test_contract_enforces_route_limits_fallback_limit_and_cycles() -> None:
    too_many_attempts = make_contract(route_attempts=4)
    with pytest.raises(core.ValidationError, match=r"\[1, 3\]"):
        core.validate_task_contract(too_many_attempts)

    too_many_fallbacks = make_contract(
        fallbacks=[f"route-{index}" for index in range(5)]
    )
    with pytest.raises(core.ValidationError, match="at most four"):
        core.validate_task_contract(too_many_fallbacks)

    cyclic_routes = make_contract(
        fallbacks=[
            {"id": "route-a", "max_attempts": 1, "next": ["route-b"]},
            {"id": "route-b", "max_attempts": 1, "next": ["route-a"]},
        ]
    )
    with pytest.raises(core.ValidationError, match="cycle"):
        core.validate_task_contract(cyclic_routes)

    cyclic_tasks = [
        make_contract("TASK-A", depends_on=["TASK-B"]),
        make_contract("TASK-B", depends_on=["TASK-A"]),
    ]
    with pytest.raises(core.ValidationError, match="cycle"):
        core.validate_task_contracts(cyclic_tasks)


def test_journal_replays_exactly_and_rejects_manual_pass(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    journal.transition_requirement(
        "REQ-P0-02", "NOT_RUN", "RUNNING", "bounded checker started"
    )
    assert journal.verify()["requirements"]["REQ-P0-02"]["state"] == "RUNNING"
    assert journal.rebuild_state() == json.loads(
        (tmp_path / "state.json").read_text(encoding="utf-8")
    )

    with pytest.raises(core.TransitionError, match="manual success"):
        journal.transition_requirement(
            "REQ-P0-02", "RUNNING", "VERIFIED_PASS", "human said pass"
        )
    with pytest.raises(core.TransitionError, match="success events"):
        journal.append(
            "requirement_verified",
            {
                "requirement_id": "REQ-P0-02",
                "receipt_id": "manual",
                "receipt_hash": digest("manual"),
            },
        )
    journal.declare_requirement("REQ-P0-03")
    with pytest.raises(core.TransitionError, match="illegal requirement transition"):
        journal.transition_requirement(
            "REQ-P0-03", "NOT_RUN", "FAILED", "checker never started"
        )
    with pytest.raises(core.TransitionError, match="unknown requirement state"):
        journal.transition_requirement(
            "REQ-P0-03", "NOT_RUN", "MYSTERY", "unknown state injection"
        )


def test_journal_bootstrap_cli_creates_authority_and_projection(
    tmp_path: Path,
) -> None:
    registry, lock = write_authority(tmp_path)
    events = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    command = [
        sys.executable,
        str(Path(core.__file__)),
        "journal-bootstrap",
        "--events",
        str(events),
        "--state",
        str(state),
        "--project-root",
        str(tmp_path),
        "--evidence-root",
        str(tmp_path / "evidence"),
        "--requirements",
        str(registry),
        "--requirements-lock",
        str(lock),
    ]
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "BOOTSTRAPPED"
    assert payload["event"]["event_type"] == "authority_bootstrapped"
    assert payload["state"]["journal"]["sequence"] == 1
    assert events.is_file()
    assert state.is_file()
    assert core.Journal(
        events,
        state,
        project_root=tmp_path,
        evidence_root=tmp_path / "evidence",
        requirements_path=registry,
        requirements_lock_path=lock,
    ).verify()["journal"]["sequence"] == 1


def test_standalone_replay_requires_matching_frozen_authority(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    events = journal.read_events()
    with pytest.raises(core.IntegrityError, match="explicit frozen authority"):
        core.replay_events(events)
    authority = journal.load_authority()
    assert core.replay_events(events, authority=authority) == journal.rebuild_state()
    drifted = copy.deepcopy(authority)
    drifted["snapshot_hash"] = digest("different-authority-snapshot")
    with pytest.raises(core.IntegrityError, match="authority differs"):
        core.replay_events(events, authority=drifted)


def test_frozen_authority_rejects_orphan_registry_edges(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    registry = json.loads(journal.requirements_path.read_text(encoding="utf-8"))
    requirement = next(
        item for item in registry["requirements"] if item["id"] == "REQ-P0-02"
    )
    old_checker_id = requirement["checker_ids"][0]
    orphan_checker_id = "CHK-REQ-P0-02-ORPHAN"
    requirement["checker_ids"] = [orphan_checker_id]
    registry["traceability"]["requirement_to_checkers"]["REQ-P0-02"] = [
        orphan_checker_id
    ]
    registry["traceability"]["checker_to_requirements"][old_checker_id] = []
    registry["traceability"]["checker_to_requirements"][orphan_checker_id] = [
        "REQ-P0-02"
    ]
    persist_authority(
        journal.requirements_path, journal.requirements_lock_path, registry
    )
    with pytest.raises(core.IntegrityError, match="unknown checker IDs"):
        journal.load_authority()


def test_journal_rejects_payload_tamper_and_noncanonical_rehash(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    line = json.loads((tmp_path / "events.jsonl").read_text(encoding="utf-8"))
    line["payload"]["requirement_id"] = "REQ-P0-03"
    (tmp_path / "events.jsonl").write_text(
        core.canonical_json(line) + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.IntegrityError, match="event ID mismatch"):
        journal.rebuild_state()


def test_journal_rejects_duplicate_out_of_order_hash_break_and_unknown_event(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    journal = make_journal(source)
    journal.declare_requirement("REQ-P0-02")
    original = (source / "events.jsonl").read_bytes()

    duplicate_dir = tmp_path / "duplicate"
    duplicate_dir.mkdir()
    first = json.loads(original.decode("utf-8"))
    duplicate = copy.deepcopy(first)
    duplicate["sequence"] = 2
    duplicate["prev_hash"] = first["event_hash"]
    duplicate_body = {
        key: value for key, value in duplicate.items() if key != "event_hash"
    }
    duplicate["event_hash"] = core.sha256_json(duplicate_body)
    (duplicate_dir / "events.jsonl").write_text(
        core.canonical_json(first) + "\n" + core.canonical_json(duplicate) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(core.IntegrityError, match="duplicate semantic"):
        make_journal(duplicate_dir).rebuild_state()

    broken_dir = tmp_path / "broken"
    broken_dir.mkdir()
    event = json.loads(original.decode("utf-8"))
    event["sequence"] = 2
    body = {key: value for key, value in event.items() if key != "event_hash"}
    event["event_hash"] = core.sha256_json(body)
    (broken_dir / "events.jsonl").write_text(
        core.canonical_json(event) + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.IntegrityError, match="out-of-order"):
        make_journal(broken_dir).rebuild_state()

    hash_break_dir = tmp_path / "hash-break"
    hash_break_dir.mkdir()
    event = json.loads(original.decode("utf-8"))
    event["prev_hash"] = digest("not-genesis")
    body = {key: value for key, value in event.items() if key != "event_hash"}
    event["event_hash"] = core.sha256_json(body)
    (hash_break_dir / "events.jsonl").write_text(
        core.canonical_json(event) + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.IntegrityError, match="hash-chain break"):
        make_journal(hash_break_dir).rebuild_state()

    unknown_dir = tmp_path / "unknown"
    unknown_dir.mkdir()
    event = json.loads(original.decode("utf-8"))
    event["event_type"] = "manual_pass"
    event["event_id"] = core.sha256_json(
        {"event_type": event["event_type"], "payload": event["payload"]}
    )
    body = {key: value for key, value in event.items() if key != "event_hash"}
    event["event_hash"] = core.sha256_json(body)
    (unknown_dir / "events.jsonl").write_text(
        core.canonical_json(event) + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.IntegrityError, match="unknown event"):
        make_journal(unknown_dir).rebuild_state()


def test_exclusive_lock_serializes_concurrent_appends(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    requirement_ids = [f"REQ-P0-{index:02d}" for index in range(10, 18)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(journal.declare_requirement, requirement_ids))
    state = journal.verify()
    assert state["journal"]["sequence"] == 1
    assert set(state["requirements"]) == set(DEFAULT_REQUIREMENT_IDS)


def test_projection_anchor_detects_complete_tail_truncation_and_drift(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    journal.transition_requirement(
        "REQ-P0-02", "NOT_RUN", "RUNNING", "checker started"
    )
    lines = (tmp_path / "events.jsonl").read_bytes().splitlines(keepends=True)
    (tmp_path / "events.jsonl").write_bytes(lines[0])
    with pytest.raises(core.IntegrityError, match="tail truncation"):
        journal.rebuild_state()

    (tmp_path / "events.jsonl").write_bytes(b"".join(lines))
    projection = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    projection["requirements"]["REQ-P0-02"]["state"] = "VERIFIED_PASS"
    (tmp_path / "state.json").write_text(
        core.canonical_json(projection) + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.IntegrityError, match="projection drift"):
        journal.verify()
    repaired = journal.rebuild_projection()
    assert repaired["requirements"]["REQ-P0-02"]["state"] == "RUNNING"
    assert journal.verify() == repaired


def test_truncated_record_is_rejected(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    raw = (tmp_path / "events.jsonl").read_bytes()
    (tmp_path / "events.jsonl").write_bytes(raw[:-3])
    with pytest.raises(core.IntegrityError, match="truncated final record"):
        journal.rebuild_state()


def test_projection_recovers_after_injected_crash_without_reappending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = make_journal(tmp_path)
    journal.declare_requirement("REQ-P0-02")
    real_atomic_write = core.atomic_write_json
    calls = 0

    def crash_projection(path: object, value: object) -> None:
        nonlocal calls
        calls += 1
        raise OSError("injected projection crash")

    monkeypatch.setattr(core, "atomic_write_json", crash_projection)
    with pytest.raises(OSError, match="injected"):
        journal.transition_requirement(
                "REQ-P0-02", "NOT_RUN", "RUNNING", "durable journal first"
        )
    assert calls == 1
    assert len(journal.read_events()) == 2

    monkeypatch.setattr(core, "atomic_write_json", real_atomic_write)
    recovered = journal.rebuild_projection()
    assert recovered["journal"]["sequence"] == 2
    assert recovered["requirements"]["REQ-P0-02"]["state"] == "RUNNING"
    assert journal.verify() == recovered


def test_attempt_requires_causal_verifier_delta_and_changed_hash(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(route_attempts=2, total_attempts=2)
    register_task(journal, contract)
    environment = digest("environment-v1")
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-CHECKER-001",
        environment_hash=environment,
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-CHECKER-001",
        evidence_hash=digest("failure-evidence"),
    )

    with pytest.raises(core.AttemptError, match="causal_verifier_receipt_id"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="FAIL-CHECKER-001",
            environment_hash=environment,
        )

    unchanged = make_causal_receipt(
        journal,
        "causal-unchanged",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-CHECKER-001",
        environment_hash=environment,
    )
    journal.record_checker_receipt(unchanged)
    with pytest.raises(core.AttemptError, match="neither an input delta"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="FAIL-CHECKER-001",
            environment_hash=environment,
            causal_verifier_receipt_id="causal-unchanged",
        )

    (journal.project_root / "src" / "task.txt").write_text(
        "task input v2\n", encoding="utf-8", newline="\n"
    )
    unrelated_receipt = make_causal_receipt(
        journal,
        "causal-unrelated-claim",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-CHECKER-001",
        environment_hash=environment,
    )
    unrelated_receipt["metadata"]["changed_components"] = [
        {
            "path": "src/unrelated.txt",
            "before_hash": core.ABSENT_FILE_HASH,
            "after_hash": digest("unrelated-change"),
        }
    ]
    journal.record_checker_receipt(unrelated_receipt)
    with pytest.raises(core.AttemptError, match="differ from actual"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="FAIL-CHECKER-001",
            environment_hash=environment,
            causal_verifier_receipt_id="causal-unrelated-claim",
        )
    causal_receipt = make_causal_receipt(
        journal,
        "causal-changed",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-CHECKER-001",
        environment_hash=environment,
    )
    journal.record_checker_receipt(causal_receipt)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-CHECKER-001",
        environment_hash=environment,
        causal_verifier_receipt_id="causal-changed",
    )
    state = journal.rebuild_state()
    assert state["tasks"]["P0-CORE-TEST"]["total_attempts"] == 2


def test_environment_only_retry_requires_and_accepts_trusted_manifest(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=2, total_attempts=2))
    environment_v1 = digest("environment-only-v1")
    environment_v2 = digest("environment-only-v2")
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-ENVIRONMENT",
        environment_hash=environment_v1,
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-ENVIRONMENT",
        evidence_hash=digest("environment-only-failure"),
    )

    with pytest.raises(core.AttemptError, match="causal_verifier_receipt_id"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="FAIL-ENVIRONMENT",
            environment_hash=environment_v2,
        )

    causal_receipt = make_causal_receipt(
        journal,
        "causal-environment-only",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-ENVIRONMENT",
        environment_hash=environment_v2,
    )
    journal.record_checker_receipt(causal_receipt)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-ENVIRONMENT",
        environment_hash=environment_v2,
        causal_verifier_receipt_id="causal-environment-only",
    )

    attempts = journal.rebuild_state()["tasks"]["P0-CORE-TEST"]["attempts"]
    assert attempts[1]["input_hash"] == attempts[0]["input_hash"]
    assert attempts[1]["environment_hash"] != attempts[0]["environment_hash"]
    assert attempts[1]["causal_verifier_receipt_id"] == "causal-environment-only"


def test_interrupted_attempt_recovers_only_same_snapshot_without_repair(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=2, total_attempts=2))
    environment = digest("interrupted-environment")
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="PROCESS-INTERRUPTED",
        environment_hash=environment,
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="INTERRUPTED",
        failure_signature="PROCESS-INTERRUPTED",
        evidence_hash=digest("interrupted-supervisor-evidence"),
    )
    interrupted = journal.rebuild_state()
    assert interrupted["tasks"]["P0-CORE-TEST"]["status"] == "INTERRUPTED"
    assert interrupted["requirements"]["REQ-P0-02"]["state"] == "INTERRUPTED"

    input_path = journal.project_root / "src" / "task.txt"
    original = input_path.read_bytes()
    input_path.write_text("changed while interrupted\n", encoding="utf-8", newline="\n")
    with pytest.raises(core.AttemptError, match="same input"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="PROCESS-INTERRUPTED",
            environment_hash=environment,
        )
    input_path.write_bytes(original)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="PROCESS-INTERRUPTED",
        environment_hash=environment,
    )
    recovered = journal.rebuild_state()
    assert recovered["tasks"]["P0-CORE-TEST"]["total_attempts"] == 2
    assert recovered["requirements"]["REQ-P0-02"]["state"] == "RUNNING"


def test_route_and_total_exhaustion_become_terminal_blocked_final(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(route_attempts=1, total_attempts=1)
    register_task(journal, contract)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-ONLY-ROUTE",
        environment_hash=digest("environment"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-ONLY-ROUTE",
        evidence_hash=digest("failed-route"),
    )
    state = journal.rebuild_state()
    assert state["tasks"]["P0-CORE-TEST"]["status"] == "BLOCKED_FINAL"
    assert state["requirements"]["REQ-P0-02"]["state"] == "BLOCKED_FINAL"
    (journal.project_root / "src" / "task.txt").write_text(
        "task input after exhaustion\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(core.AttemptError, match="BLOCKED_FINAL"):
        journal.start_attempt(
            "P0-CORE-TEST",
            failure_signature="FAIL-ONLY-ROUTE",
            environment_hash=digest("environment"),
        )


def test_fallback_routing_is_one_way_and_all_routes_exhaust_to_blocked_final(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(
        route_attempts=1,
        total_attempts=2,
        fallbacks=[{"id": "route-b", "max_attempts": 1}],
    )
    register_task(journal, contract)
    environment = digest("fallback-environment")
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-MAIN",
        environment_hash=environment,
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-MAIN",
        evidence_hash=digest("main-failure"),
    )
    (journal.project_root / "src" / "task.txt").write_text(
        "fallback repair\n", encoding="utf-8", newline="\n"
    )
    causal_receipt = make_causal_receipt(
        journal,
        "fallback-causal",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-MAIN",
        environment_hash=environment,
    )
    journal.record_checker_receipt(causal_receipt)
    with pytest.raises(core.AttemptError, match="ADR evidence"):
        journal.start_attempt(
            "P0-CORE-TEST",
            route_id="route-b",
            failure_signature="FAIL-MAIN",
            environment_hash=environment,
            causal_verifier_receipt_id="fallback-causal",
        )
    journal.exhaust_route(
        "P0-CORE-TEST", "P0-CORE-TEST", "FAIL-MAIN", digest("route-switch-adr")
    )
    journal.start_attempt(
        "P0-CORE-TEST",
        route_id="route-b",
        failure_signature="FAIL-MAIN",
        environment_hash=environment,
        causal_verifier_receipt_id="fallback-causal",
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-FALLBACK",
        evidence_hash=digest("fallback-failure"),
    )
    state = journal.rebuild_state()
    assert state["tasks"]["P0-CORE-TEST"]["status"] == "BLOCKED_FINAL"
    assert state["tasks"]["P0-CORE-TEST"]["routes"]["P0-CORE-TEST"]["status"] == "EXHAUSTED"
    assert state["tasks"]["P0-CORE-TEST"]["routes"]["route-b"]["status"] == "EXHAUSTED"


def test_fallback_routing_uses_declared_next_edges_not_array_order(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(
        route_attempts=1,
        total_attempts=3,
        fallbacks=[
            {"id": "route-a", "max_attempts": 1, "next": ["route-c"]},
            {"id": "route-b", "max_attempts": 1, "next": []},
            {"id": "route-c", "max_attempts": 1, "next": []},
        ],
    )
    register_task(journal, contract)
    environment_v1 = digest("fallback-graph-environment-v1")
    environment_v2 = digest("fallback-graph-environment-v2")
    environment_v3 = digest("fallback-graph-environment-v3")

    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="FAIL-MAIN-GRAPH",
        environment_hash=environment_v1,
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-MAIN-GRAPH",
        evidence_hash=digest("fallback-graph-main-failure"),
    )
    journal.exhaust_route(
        "P0-CORE-TEST",
        "P0-CORE-TEST",
        "FAIL-MAIN-GRAPH",
        digest("fallback-graph-main-adr"),
    )
    route_a_receipt = make_causal_receipt(
        journal,
        "causal-route-a",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-MAIN-GRAPH",
        environment_hash=environment_v2,
    )
    journal.record_checker_receipt(route_a_receipt)
    journal.start_attempt(
        "P0-CORE-TEST",
        route_id="route-a",
        failure_signature="FAIL-MAIN-GRAPH",
        environment_hash=environment_v2,
        causal_verifier_receipt_id="causal-route-a",
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-ROUTE-A",
        evidence_hash=digest("fallback-graph-route-a-failure"),
    )
    journal.exhaust_route(
        "P0-CORE-TEST",
        "route-a",
        "FAIL-ROUTE-A",
        digest("fallback-graph-route-a-adr"),
    )
    route_c_receipt = make_causal_receipt(
        journal,
        "causal-route-c",
        "P0-CORE-TEST",
        "REQ-P0-02",
        failure_signature="FAIL-ROUTE-A",
        environment_hash=environment_v3,
    )
    journal.record_checker_receipt(route_c_receipt)

    with pytest.raises(core.AttemptError, match="not a declared next node"):
        journal.start_attempt(
            "P0-CORE-TEST",
            route_id="route-b",
            failure_signature="FAIL-ROUTE-A",
            environment_hash=environment_v3,
            causal_verifier_receipt_id="causal-route-c",
        )

    journal.start_attempt(
        "P0-CORE-TEST",
        route_id="route-c",
        failure_signature="FAIL-ROUTE-A",
        environment_hash=environment_v3,
        causal_verifier_receipt_id="causal-route-c",
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="FAILED",
        failure_signature="FAIL-ROUTE-C",
        evidence_hash=digest("fallback-graph-route-c-failure"),
    )

    state = journal.rebuild_state()
    task = state["tasks"]["P0-CORE-TEST"]
    assert task["status"] == "BLOCKED_FINAL"
    assert task["routes"]["route-b"] == {
        "max_attempts": 1,
        "attempt_count": 0,
        "status": "NOT_RUN",
    }
    assert [attempt["route_id"] for attempt in task["attempts"]] == [
        "P0-CORE-TEST",
        "route-a",
        "route-c",
    ]


def test_task_dependency_dag_blocks_execution_until_receipt_verified(tmp_path: Path) -> None:
    journal = make_journal(tmp_path)
    upstream = make_contract(
        "TASK-UPSTREAM",
        requirements=["REQ-P0-02"],
        route_attempts=1,
        total_attempts=1,
    )
    downstream = make_contract(
        "TASK-DOWNSTREAM",
        requirements=["REQ-DOD-17"],
        route_attempts=1,
        total_attempts=1,
        depends_on=["TASK-UPSTREAM"],
    )
    journal.declare_requirement("REQ-P0-02")
    journal.declare_requirement("REQ-DOD-17")
    journal.register_task(upstream)
    journal.register_task(downstream)
    with pytest.raises(core.AttemptError, match="dependencies are not VERIFIED_PASS"):
        journal.start_attempt(
            "TASK-DOWNSTREAM",
            failure_signature="INITIAL-DOWNSTREAM",
            environment_hash=digest("dependency-environment"),
        )

    evidence = digest("upstream-evidence")
    journal.start_attempt(
        "TASK-UPSTREAM",
        failure_signature="INITIAL-UPSTREAM",
        environment_hash=digest("dependency-environment"),
    )
    receipt = make_receipt(
        journal,
        "upstream-receipt",
        "TASK-UPSTREAM",
        ["REQ-P0-02"],
        source_hash=digest("dependency-source"),
    )
    journal.finish_attempt(
        "TASK-UPSTREAM", outcome="CHECKS_PASSED", evidence_hash=receipt["evidence_hash"]
    )
    journal.record_checker_receipt(receipt)
    journal.verify_requirement("REQ-P0-02", "upstream-receipt")
    journal.start_attempt(
        "TASK-DOWNSTREAM",
        failure_signature="INITIAL-DOWNSTREAM",
        environment_hash=digest("dependency-environment"),
    )
    assert journal.rebuild_state()["tasks"]["TASK-DOWNSTREAM"]["status"] == "RUNNING"


def test_requirement_dag_prevents_early_dod_receipt(tmp_path: Path) -> None:
    journal = make_journal(
        tmp_path, dependencies={"REQ-DOD-17": ["REQ-P0-02"]}
    )
    journal.declare_requirement("REQ-P0-02")
    journal.declare_requirement("REQ-DOD-17")
    journal.register_task(
        make_contract(
            "TASK-EARLY-DOD",
            requirements=["REQ-DOD-17"],
            route_attempts=1,
            total_attempts=1,
        )
    )
    journal.start_attempt(
        "TASK-EARLY-DOD",
        failure_signature="INITIAL-DOD",
        environment_hash=digest("dod-environment"),
    )
    receipt = make_receipt(
        journal,
        "early-dod-receipt",
        "TASK-EARLY-DOD",
        ["REQ-DOD-17"],
        source_hash=digest("dod-source"),
    )
    journal.finish_attempt(
        "TASK-EARLY-DOD",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    with pytest.raises(core.ValidationError, match="DAG dependency is not VERIFIED_PASS"):
        journal.record_checker_receipt(receipt)


def test_multi_requirement_task_binds_one_real_receipt_per_requirement(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(
        requirements=["REQ-P0-02", "REQ-P0-03"],
        route_attempts=1,
        total_attempts=1,
    )
    register_task(journal, contract)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-MULTI-REQUIREMENT",
        environment_hash=digest("multi-requirement-environment"),
    )
    first = make_receipt(
        journal,
        "multi-receipt-p0-02",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("multi-source"),
    )
    second = make_receipt(
        journal,
        "multi-receipt-p0-03",
        "P0-CORE-TEST",
        ["REQ-P0-03"],
        source_hash=digest("multi-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hashes=[first["evidence_hash"], second["evidence_hash"]],
    )
    journal.record_checker_receipt(first)
    journal.record_checker_receipt(second)
    journal.verify_requirement("REQ-P0-02", first["id"])
    assert journal.rebuild_state()["tasks"]["P0-CORE-TEST"]["status"] == "RUNNING"
    journal.verify_requirement("REQ-P0-03", second["id"])
    state = journal.verify()
    assert state["tasks"]["P0-CORE-TEST"]["status"] == "VERIFIED_PASS"
    assert all(
        state["requirements"][requirement_id]["state"] == "VERIFIED_PASS"
        for requirement_id in contract["requirement_ids"]
    )


def test_trace_only_requirements_do_not_run_or_block_task_completion(
    tmp_path: Path,
) -> None:
    journal = make_journal(
        tmp_path, dependencies={"REQ-DOD-17": ["REQ-P0-02"]}
    )
    contract = make_contract(
        requirements=["REQ-P0-02", "REQ-DOD-17"],
        route_attempts=1,
        total_attempts=1,
    )
    contract["deterministic_checkers"] = ["CHK-REQ-P0-02"]
    register_task(journal, contract)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-STAGE-CHECKER",
        environment_hash=digest("stage-checker-environment"),
    )
    running = journal.rebuild_state()
    assert running["requirements"]["REQ-P0-02"]["state"] == "RUNNING"
    assert running["requirements"]["REQ-DOD-17"]["state"] == "NOT_RUN"
    assert running["tasks"]["P0-CORE-TEST"]["checkable_requirement_ids"] == [
        "REQ-P0-02"
    ]
    receipt = make_receipt(
        journal,
        "stage-only-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("stage-only-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    journal.record_checker_receipt(receipt)
    journal.verify_requirement("REQ-P0-02", receipt["id"])
    complete = journal.verify()
    assert complete["tasks"]["P0-CORE-TEST"]["status"] == "VERIFIED_PASS"
    assert complete["requirements"]["REQ-DOD-17"]["state"] == "NOT_RUN"


def test_receipt_is_fully_bound_and_stales_dependents_recursively(tmp_path: Path) -> None:
    journal = make_journal(
        tmp_path, dependencies={"REQ-DOD-17": ["REQ-P0-02"]}
    )
    root_contract = make_contract(
        "TASK-ROOT", requirements=["REQ-P0-02"], route_attempts=1, total_attempts=1
    )
    dependent_contract = make_contract(
        "TASK-DEPENDENT",
        requirements=["REQ-DOD-17"],
        route_attempts=1,
        total_attempts=1,
        depends_on=["TASK-ROOT"],
    )
    journal.declare_requirement("REQ-P0-02")
    journal.declare_requirement("REQ-DOD-17")
    journal.register_task(root_contract)
    journal.register_task(dependent_contract)

    source_v1 = digest("source-v1")
    journal.start_attempt(
        "TASK-ROOT",
        failure_signature="INITIAL-ROOT",
        environment_hash=digest("qualification-environment"),
    )
    root_receipt = make_receipt(
        journal,
        "receipt-root",
        "TASK-ROOT",
        ["REQ-P0-02"],
        source_hash=source_v1,
    )
    with pytest.raises(core.ValidationError, match="CHECKS_PASSED"):
        journal.record_checker_receipt(root_receipt)
    journal.finish_attempt(
        "TASK-ROOT",
        outcome="CHECKS_PASSED",
        evidence_hash=root_receipt["evidence_hash"],
    )
    journal.record_checker_receipt(root_receipt)
    journal.verify_requirement("REQ-P0-02", "receipt-root")

    journal.start_attempt(
        "TASK-DEPENDENT",
        failure_signature="INITIAL-DEPENDENT",
        environment_hash=digest("qualification-environment"),
    )
    omitted_dependency = make_receipt(
        journal,
        "receipt-omitted-dependency",
        "TASK-DEPENDENT",
        ["REQ-DOD-17"],
        source_hash=digest("source-independent"),
    )
    with pytest.raises(core.ValidationError, match="omits current"):
        journal.record_checker_receipt(omitted_dependency)
    dependent_receipt = make_receipt(
        journal,
        "receipt-dependent",
        "TASK-DEPENDENT",
        ["REQ-DOD-17"],
        source_hash=digest("source-independent"),
        dependencies=["receipt-root"],
    )
    journal.finish_attempt(
        "TASK-DEPENDENT",
        outcome="CHECKS_PASSED",
        evidence_hash=dependent_receipt["evidence_hash"],
    )
    journal.record_checker_receipt(dependent_receipt)
    journal.verify_requirement("REQ-DOD-17", "receipt-dependent")
    verified_state = journal.rebuild_state()["requirements"]
    assert verified_state["REQ-P0-02"]["state"] == "VERIFIED_PASS"
    assert verified_state["REQ-DOD-17"]["state"] == "VERIFIED_PASS"

    journal.change_input(
        "source_tree_manifest_hash",
        root_receipt["inputs"]["source_tree_manifest_hash"],
        digest("source-v2"),
        "source tree changed after qualification",
        digest("source-change-proof"),
    )
    state = journal.rebuild_state()
    assert state["receipts"]["receipt-root"]["status"] == "STALE"
    assert state["receipts"]["receipt-dependent"]["status"] == "STALE"
    assert state["requirements"]["REQ-P0-02"]["state"] == "STALE"
    assert state["requirements"]["REQ-DOD-17"]["state"] == "STALE"


def test_receipt_rejects_missing_binding_and_forged_checker_derivation(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    contract = make_contract(route_attempts=1, total_attempts=1)
    register_task(journal, contract)
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-RECEIPT",
        environment_hash=digest("receipt-environment"),
    )
    receipt = make_receipt(
        journal,
        "receipt-valid",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("source"),
    )
    missing = copy.deepcopy(receipt)
    del missing["inputs"]["evaluator_hash"]
    with pytest.raises(core.ValidationError, match="bind exactly"):
        core.validate_receipt(missing)

    forged = copy.deepcopy(receipt)
    forged["checker"]["derived_verdict_hash"] = digest("handwritten-pass")
    with pytest.raises(core.ValidationError, match="deterministically bound"):
        core.validate_receipt(forged)


def test_false_success_receipts_fail_closed_on_checker_identity_and_evidence(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=1, total_attempts=1))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-COUNTEREXAMPLE",
        environment_hash=digest("counterexample-environment"),
    )
    valid = make_receipt(
        journal,
        "counterexample-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("counterexample-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=valid["evidence_hash"],
    )

    nonzero = copy.deepcopy(valid)
    nonzero["checker"]["exit_code"] = 17
    with pytest.raises(core.ValidationError, match="exit_code must equal zero"):
        journal.record_checker_receipt(nonzero)

    unknown_checker = copy.deepcopy(valid)
    unknown_checker["checker"]["checker_id"] = "CHK-UNKNOWN"
    rederive_receipt(unknown_checker)
    with pytest.raises(core.ValidationError, match="frozen requirement checker"):
        journal.record_checker_receipt(unknown_checker)

    wrong_verifier = copy.deepcopy(valid)
    wrong_verifier["metadata"]["verifier_id"] = "executor-calling-itself-verifier"
    with pytest.raises(core.ValidationError, match="verifier identity"):
        journal.record_checker_receipt(wrong_verifier)

    wrong_spec = copy.deepcopy(valid)
    wrong_spec["inputs"]["requirements_spec_hash"] = digest("unfrozen-spec")
    rederive_receipt(wrong_spec)
    with pytest.raises(core.ValidationError, match="differs from journal authority"):
        journal.record_checker_receipt(wrong_spec)

    manifest = json.loads(
        (journal.project_root / valid["evidence_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    stdout_path = next(
        artifact["path"]
        for artifact in manifest["artifacts"]
        if artifact["role"] == "stdout"
    )
    (journal.project_root / stdout_path).unlink()
    with pytest.raises(core.IntegrityError, match="unavailable or escapes"):
        journal.record_checker_receipt(valid)


def test_unimplemented_frozen_checker_cannot_issue_pass(tmp_path: Path) -> None:
    journal = make_journal(tmp_path, checker_status="planned")
    register_task(journal, make_contract(route_attempts=1, total_attempts=1))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-PLANNED-CHECKER",
        environment_hash=digest("planned-checker-environment"),
    )
    receipt = make_receipt(
        journal,
        "planned-checker-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("planned-checker-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    with pytest.raises(core.IntegrityError, match="implementation is not available"):
        journal.record_checker_receipt(receipt)


def test_authority_drift_fails_closed_and_spec_migration_stales_receipts(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=2, total_attempts=2))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-AUTHORITY",
        environment_hash=digest("authority-environment"),
    )
    receipt = make_receipt(
        journal,
        "authority-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("authority-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    journal.record_checker_receipt(receipt)
    journal.verify_requirement("REQ-P0-02", "authority-receipt")
    old_spec_hash = journal.load_authority()["requirements_spec_hash"]

    registry = json.loads(journal.requirements_path.read_text(encoding="utf-8"))
    registry["living_document_progress"] = {"note": "non-spec progress update"}
    registry_bytes = (
        json.dumps(registry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    journal.requirements_path.write_bytes(registry_bytes)
    lock = json.loads(journal.requirements_lock_path.read_text(encoding="utf-8"))
    lock["requirements_document_sha256"] = core.sha256_bytes(registry_bytes)
    journal.requirements_lock_path.write_text(
        json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    assert journal.verify()["authority"]["requirements_spec_hash"] == old_spec_hash

    write_authority(
        tmp_path,
        completion_suffix=" Strengthened completion semantics.",
    )
    new_spec_hash = journal.load_authority()["requirements_spec_hash"]
    assert new_spec_hash != old_spec_hash
    with pytest.raises(core.IntegrityError, match="authority differs"):
        journal.verify()
    with pytest.raises(core.ValidationError, match="change_requirements_authority"):
        journal.change_input(
            "requirements_spec_hash",
            old_spec_hash,
            new_spec_hash,
            "bypass migration",
            digest("bypass-proof"),
        )

    journal.change_requirements_authority(
        "requirement-bearing authority changed", digest("authority-migration-proof")
    )
    state = journal.verify()
    assert state["authority"]["requirements_spec_hash"] == new_spec_hash
    assert state["receipts"]["authority-receipt"]["status"] == "STALE"
    assert state["requirements"]["REQ-P0-02"]["state"] == "STALE"
    assert state["tasks"]["P0-CORE-TEST"]["status"] == "STALE"

    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="REQUALIFY-NEW-AUTHORITY",
        environment_hash=digest("authority-environment"),
    )
    replacement = make_receipt(
        journal,
        "authority-replacement-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("authority-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=replacement["evidence_hash"],
    )
    journal.record_checker_receipt(replacement)
    journal.verify_requirement("REQ-P0-02", replacement["id"])
    requalified = journal.verify()
    assert requalified["tasks"]["P0-CORE-TEST"]["total_attempts"] == 2
    assert requalified["requirements"]["REQ-P0-02"]["state"] == "VERIFIED_PASS"


def test_authority_migration_cannot_remove_frozen_dependency_edges(
    tmp_path: Path,
) -> None:
    journal = make_journal(
        tmp_path, dependencies={"REQ-DOD-17": ["REQ-P0-02"]}
    )
    journal.declare_requirement("REQ-P0-02")
    journal.declare_requirement("REQ-DOD-17")
    write_authority(tmp_path, completion_suffix=" Changed without dependency.")
    with pytest.raises(core.IntegrityError, match="authority differs"):
        journal.verify()
    with pytest.raises(core.ValidationError, match="removes frozen depends_on"):
        journal.change_requirements_authority(
            "attempted dependency weakening", digest("dependency-weakening-proof")
        )


def test_authority_replay_rejects_empty_and_partial_requirement_sets(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    authority = journal.load_authority()
    with pytest.raises(core.IntegrityError, match="no atomically bootstrapped"):
        core.replay_events([], authority=authority)

    requirement_id = "REQ-P0-02"
    partial = core._new_event(
        1,
        core.GENESIS_HASH,
        "requirement_declared",
        {
            "requirement_id": requirement_id,
            "requirements_spec_hash": authority["requirements_spec_hash"],
            "authority_snapshot_hash": authority["snapshot_hash"],
            **authority["requirements"][requirement_id],
        },
    )
    with pytest.raises(core.IntegrityError, match="incomplete or foreign"):
        core.replay_events([partial], authority=authority)

    journal.declare_requirement(requirement_id)
    assert set(journal.verify()["requirements"]) == set(DEFAULT_REQUIREMENT_IDS)


def test_finish_attempt_turns_out_of_allowlist_write_into_failure(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=2, total_attempts=2))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-SCOPE",
        environment_hash=digest("scope-environment"),
    )
    (tmp_path / "outside-contract.txt").write_text(
        "unauthorized\n", encoding="utf-8", newline="\n"
    )
    event = journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=digest("claimed-pass"),
    )
    assert event["payload"]["outcome"] == "FAILED"
    assert event["payload"]["failure_signature"].startswith(
        "ALLOWED_PATH_VIOLATION:"
    )
    assert [item["path"] for item in event["payload"]["scope_violations"]] == [
        "outside-contract.txt"
    ]
    state = journal.verify()
    assert state["tasks"]["P0-CORE-TEST"]["status"] == "FAILED"
    assert state["requirements"]["REQ-P0-02"]["state"] == "FAILED"


def test_receipt_input_manifest_is_recomputed_from_each_bound_file(
    tmp_path: Path,
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=1, total_attempts=1))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature="INITIAL-INPUT-MANIFEST",
        environment_hash=digest("input-manifest-environment"),
    )
    receipt = make_receipt(
        journal,
        "input-manifest-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest("input-manifest-source"),
    )
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    input_manifest = json.loads(
        (journal.project_root / receipt["input_manifest_path"]).read_text(
            encoding="utf-8"
        )
    )
    source_binding = next(
        item
        for item in input_manifest["bindings"]
        if item["name"] == "source_tree_manifest_hash"
    )
    (journal.project_root / source_binding["path"]).write_bytes(
        b"changed source manifest"
    )
    with pytest.raises(core.IntegrityError, match="trusted input file hash mismatch"):
        journal.record_checker_receipt(receipt)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("orphan", "left or could not count orphans"),
        ("argv", "argv differs from supervisor"),
        ("exit", "did not exit successfully"),
        ("identity", "cleanup identity is unverified"),
    ],
)
def test_rehashed_supervisor_receipt_semantics_still_fail_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    journal = make_journal(tmp_path)
    register_task(journal, make_contract(route_attempts=1, total_attempts=1))
    journal.start_attempt(
        "P0-CORE-TEST",
        failure_signature=f"INITIAL-SUPERVISOR-{mutation}",
        environment_hash=digest(f"supervisor-{mutation}-environment"),
    )
    receipt = make_receipt(
        journal,
        f"supervisor-{mutation}-receipt",
        "P0-CORE-TEST",
        ["REQ-P0-02"],
        source_hash=digest(f"supervisor-{mutation}-source"),
    )

    def mutate(supervisor: dict[str, object]) -> None:
        if mutation == "orphan":
            supervisor["cleanup"]["orphan_count"] = 1
        elif mutation == "argv":
            supervisor["command"]["argv"] = [
                *supervisor["command"]["argv"],
                "--forged",
            ]
        elif mutation == "exit":
            supervisor["exit_code"] = 9
        else:
            supervisor["cleanup"]["identity_match"] = False

    tamper_supervisor_and_rebind(journal, receipt, mutate)
    journal.finish_attempt(
        "P0-CORE-TEST",
        outcome="CHECKS_PASSED",
        evidence_hash=receipt["evidence_hash"],
    )
    with pytest.raises(core.IntegrityError, match=message):
        journal.record_checker_receipt(receipt)


def test_findings_are_hash_chained_and_only_proven_closures_release(tmp_path: Path) -> None:
    receipt_journal = make_journal(tmp_path / "receipt-journal")
    fix_contract = make_contract(
        "FINDING-FIX-TASK",
        requirements=["REQ-P0-02"],
        route_attempts=1,
        total_attempts=1,
    )
    register_task(receipt_journal, fix_contract)
    receipt_journal.start_attempt(
        "FINDING-FIX-TASK",
        failure_signature="INITIAL-FINDING-FIX",
        environment_hash=digest("finding-fix-environment"),
    )
    fix_receipt = make_receipt(
        receipt_journal,
        "fix-receipt",
        "FINDING-FIX-TASK",
        ["REQ-P0-02"],
        source_hash=digest("source"),
        metadata={"verified_fixed_finding_ids": ["F-ROOT"]},
    )
    receipt_journal.finish_attempt(
        "FINDING-FIX-TASK",
        outcome="CHECKS_PASSED",
        evidence_hash=fix_receipt["evidence_hash"],
    )
    receipt_journal.record_checker_receipt(fix_receipt)
    receipt_journal.verify_requirement("REQ-P0-02", "fix-receipt")
    receipt_resolver = receipt_journal.rebuild_state()["receipts"]
    fix_receipt_hash = receipt_resolver["fix-receipt"]["receipt_hash"]
    ledger = core.FindingLedger(
        tmp_path / "findings.jsonl", receipt_resolver=receipt_resolver
    )
    with pytest.raises(core.FindingError, match="audit"):
        ledger.assert_release_clear()
    with pytest.raises(core.FindingError, match="severity"):
        ledger.open(
            "F-INVALID", "P1", ["REQ-P0-02"], "phase labels are not severities"
        )

    ledger.open(
        "F-ROOT", "S1_high", ["REQ-P0-02"], "Journal mutation was accepted"
    )
    ledger.dispose(
        "F-ROOT",
        "verified_fixed",
        {"receipt_id": "fix-receipt", "receipt_hash": fix_receipt_hash},
    )
    ledger.open(
        "F-DUP", "S2_medium", ["REQ-P0-02"], "Same root cause at another call site"
    )
    ledger.dispose("F-DUP", "duplicate", {"original_finding_id": "F-ROOT"})
    ledger.record_audit(
        "AUDIT-001", digest("checklist"), digest("positive"), digest("fault")
    )
    clear = ledger.assert_release_clear()
    assert clear["findings"]["F-ROOT"]["closed"] is True
    assert clear["findings"]["F-DUP"]["closed"] is True

    head = clear["ledger"]
    assert ledger.verify(
        expected_sequence=head["sequence"], expected_head_hash=head["head_hash"]
    ) == clear


def test_verified_fixed_rejects_unresolved_or_unbound_receipt(tmp_path: Path) -> None:
    ledger = core.FindingLedger(tmp_path / "findings.jsonl")
    ledger.open("F-NO-RECEIPT", "S1_high", ["REQ-P0-02"], "Unverified fix")
    with pytest.raises(core.FindingError, match="resolver"):
        ledger.dispose(
            "F-NO-RECEIPT",
            "verified_fixed",
            {"receipt_id": "missing", "receipt_hash": digest("missing")},
        )


def test_nonclosing_finding_dispositions_keep_requirement_blocked(tmp_path: Path) -> None:
    ledger = core.FindingLedger(tmp_path / "findings.jsonl")
    ledger.open(
        "F-RISK", "S3_low", ["REQ-DOD-17"], "Risk remains in enabled core"
    )
    ledger.dispose(
        "F-RISK",
        "accepted_risk",
        {
            "reason_receipt_id": "risk-receipt",
            "reason_receipt_hash": digest("risk-receipt"),
        },
    )
    ledger.record_audit(
        "AUDIT-002", digest("checklist"), digest("positive"), digest("fault")
    )
    with pytest.raises(core.FindingError, match="block release"):
        ledger.assert_release_clear()


def test_findings_mutation_and_tail_truncation_anchor_are_detected(tmp_path: Path) -> None:
    ledger = core.FindingLedger(tmp_path / "findings.jsonl")
    ledger.open("F-1", "S0_critical", ["REQ-P0-02"], "Critical control failure")
    state = ledger.state()
    expected_sequence = state["ledger"]["sequence"]
    expected_head = state["ledger"]["head_hash"]
    raw = (tmp_path / "findings.jsonl").read_bytes()
    (tmp_path / "findings.jsonl").write_bytes(b"")
    with pytest.raises(core.IntegrityError, match="truncation"):
        ledger.verify(
            expected_sequence=expected_sequence, expected_head_hash=expected_head
        )
    (tmp_path / "findings.jsonl").write_bytes(raw[:-2])
    with pytest.raises(core.IntegrityError, match="truncated final record"):
        ledger.state()
