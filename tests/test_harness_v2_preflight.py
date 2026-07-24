from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.v2.scripts.preflight import (
    BACKEND_CLASSIFICATIONS,
    classify_backend_evidence,
    run_preflight,
)
from harness.v2.scripts.supervisor import SupervisorConfig, run_supervised
import harness.v2.scripts.preflight as preflight_module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _project_fixture(tmp_path: Path) -> Path:
    services = tmp_path / "backend" / "services"
    services.mkdir(parents=True)
    (services / "agent_bundle.py").write_text(
        "ADAPTERS = {'codex': {}, 'claude': {}}\n", encoding="utf-8"
    )
    (services / "model_profiles.py").write_text(
        "PROVIDERS = {'openai_responses': 'Responses', 'openai_compatible': 'Chat', "
        "'anthropic_messages': 'Anthropic', 'gemini_generate_content': 'Gemini'}\n",
        encoding="utf-8",
    )
    return tmp_path


def _environment(tmp_path: Path, **extra: str) -> dict[str, str]:
    local = tmp_path / "local"
    machine = tmp_path / "machine"
    home = tmp_path / "home"
    for directory in (local, machine, home):
        directory.mkdir(exist_ok=True)
    return {
        "PATH": "",
        "HOME": str(home),
        "LOCALAPPDATA": str(local),
        "ProgramFiles": str(machine),
        **extra,
    }


def _legacy_boolean_evidence(**overrides):
    evidence = {
        "evidence_id": "caller-asserted-live-001",
        "classification": "live_core_task",
        "adapter_id": "openai_responses",
        "task_kind": "literature_research",
        "via_product_broker": True,
        "authenticated": True,
        "live_provider_invoked": True,
        "core_task_completed": True,
        "semantic_evidence_nonempty": True,
        "exit_code": 0,
        "orphan_count": 0,
        "supervisor_receipt_sha256": "a" * 64,
        "semantic_evidence_sha256": "b" * 64,
        "default_route_enabled": True,
    }
    evidence.update(overrides)
    return evidence


def test_bundled_isolated_python_can_run_preflight_help_directly() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "harness/v2/scripts/preflight.py"), "--help"],
        cwd=PROJECT_ROOT,
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--project-root" in result.stdout


def test_cli_probe_rejects_exit_zero_without_identity_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_receipt = {
        "termination_reason": "EXITED",
        "exit_code": 0,
        "pid_tree": [{"pid": 1}],
        "root_identity": {"executable_identity_match": True},
        "cleanup": {"orphan_count": 0, "identity_match": False},
        "stdout": {"redacted_text": "ok", "raw_bytes": 2},
        "stderr": {"redacted_text": "", "raw_bytes": 0},
    }
    monkeypatch.setattr(preflight_module, "run_supervised", lambda *_args, **_kwargs: fake_receipt)
    result = preflight_module._probe_command(
        [sys.executable, "--version"],
        cwd=tmp_path,
        environment={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result["exit_code"] == 0
    assert result["orphan_count"] == 0
    assert result["identity_match"] is False
    assert result["passed"] is False


def test_caller_booleans_and_fakeprovider_injection_are_not_candidates(tmp_path: Path) -> None:
    project = _project_fixture(tmp_path)
    fake = _legacy_boolean_evidence(adapter_id="fakeprovider", evidence_id="fakeprovider-001")
    receipt = run_preflight(
        project,
        environment=_environment(tmp_path),
        backend_evidence=[_legacy_boolean_evidence(), fake],
        command_probes=False,
    )
    asserted = next(
        item for item in receipt["backend_evidence"] if item["evidence_id"] == "caller-asserted-live-001"
    )
    rejected = next(
        item for item in receipt["backend_evidence"] if item["evidence_id"] == "fakeprovider-001"
    )
    assert asserted["candidate_for_live_verification"] is False
    assert "live_evidence_schema_invalid" in asserted["candidate_reasons"]
    assert rejected["candidate_for_live_verification"] is False
    assert rejected["adapter_id"] == "UNTRUSTED"
    assert "adapter_not_in_trusted_product_registry" in rejected["candidate_reasons"]
    assert rejected["qualifies_as_live_product_backend"] is False


def test_registry_bound_structured_files_form_candidate_but_never_preflight_pass(
    tmp_path: Path,
) -> None:
    project = _project_fixture(tmp_path)
    evidence_dir = project / "evidence"
    evidence_dir.mkdir()
    supervisor_path = evidence_dir / "supervisor.json"
    artifact_path = evidence_dir / "artifact.json"
    semantic_path = evidence_dir / "semantic.json"
    artifact_path.write_text('{"records":[{"title":"observed"}]}\n', encoding="utf-8")
    run_supervised(
        SupervisorConfig(
            argv=[sys.executable, "-c", "print('provider-result-observed')"],
            cwd=project,
            allowed_cwd_roots=[project],
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            allowed_env_keys=["PYTHONDONTWRITEBYTECODE"],
            deadline_seconds=3,
            heartbeat_seconds=0.05,
        ),
        receipt_path=supervisor_path,
    )
    semantic = {
        "schema": "harness-v2-live-core-semantic-evidence/1",
        "adapter_id": "openai_responses",
        "task_kind": "literature_research",
        "supervisor_receipt_sha256": _sha256(supervisor_path),
        "input_sha256": hashlib.sha256(b"research question").hexdigest(),
        "output_sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "input_units": 1,
        "output_units": 1,
        "artifact_path": "evidence/artifact.json",
        "artifact_sha256": _sha256(artifact_path),
    }
    semantic_path.write_text(json.dumps(semantic, sort_keys=True) + "\n", encoding="utf-8")
    live_evidence = {
        "schema": "harness-v2-product-broker-live-core-task/1",
        "evidence_id": "structured-live-core-001",
        "classification": "live_core_task",
        "adapter_id": "openai_responses",
        "task_kind": "literature_research",
        "supervisor_receipt": {
            "path": "evidence/supervisor.json",
            "sha256": _sha256(supervisor_path),
        },
        "semantic_evidence": {
            "path": "evidence/semantic.json",
            "sha256": _sha256(semantic_path),
        },
    }

    receipt = run_preflight(
        project,
        environment=_environment(tmp_path),
        backend_evidence=[live_evidence],
        command_probes=False,
    )
    candidate = next(
        item for item in receipt["backend_evidence"] if item["evidence_id"] == "structured-live-core-001"
    )
    assert candidate["candidate_for_live_verification"] is True
    assert candidate["candidate_reasons"] == []
    assert candidate["structured_evidence"]["artifact_sha256"] == _sha256(artifact_path)
    assert candidate["qualifies_as_live_product_backend"] is False
    assert receipt["qualification"]["qualified_live_product_backend_count"] == 0
    assert receipt["qualification"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_preflight_records_references_not_credential_values_and_uses_tmp_paths(tmp_path: Path) -> None:
    local_app_data = tmp_path / "local-app-data"
    program_files = tmp_path / "program-files"
    reference_root = tmp_path / "reference-source"
    for directory in (local_app_data, program_files, reference_root):
        directory.mkdir()
    (reference_root / "source.txt").write_text("readable", encoding="utf-8")
    output = tmp_path / "preflight.json"
    secret = "credential-material-never-persist"
    environment = {
        "PATH": "",
        "OPENAI_API_KEY": secret,
        "ANTHROPIC_API_KEY": "",
        "LOCALAPPDATA": str(local_app_data),
        "ProgramFiles": str(program_files),
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    receipt = run_preflight(
        tmp_path,
        environment=environment,
        reference_root=reference_root,
        output_path=output,
        command_probes=False,
    )
    serialized = output.read_text(encoding="utf-8")
    assert secret not in serialized
    assert json.loads(serialized) == receipt
    openai = next(item for item in receipt["credentials"] if item["reference"] == "OPENAI_API_KEY")
    assert openai == {
        "reference": "OPENAI_API_KEY",
        "reference_kind": "environment_variable",
        "present": True,
        "value_persisted": False,
        "value_hashed": False,
        "value_length_persisted": False,
    }
    assert receipt["installation_permissions"]["per_user_install_root"]["writable"] is True
    assert receipt["installation_permissions"]["machine_install_root"]["writable"] is True
    assert not list(local_app_data.glob(".vibe-preflight-*"))
    assert not list(program_files.glob(".vibe-preflight-*"))
    assert receipt["clean_room_acl"]["reference_root_probe"] == "ALLOWED"
    assert receipt["clean_room_acl"]["implementer_hard_read_isolation_verified"] is False


def test_current_project_preflight_is_honestly_insufficient_without_live_receipt(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    local = tmp_path / "local"
    machine = tmp_path / "machine"
    for directory in (home, local, machine):
        directory.mkdir()
    receipt = run_preflight(
        PROJECT_ROOT,
        environment={
            "PATH": "",
            "HOME": str(home),
            "LOCALAPPDATA": str(local),
            "ProgramFiles": str(machine),
        },
        command_probes=False,
    )
    assert set(receipt["backend_classification_counts"]) == BACKEND_CLASSIFICATIONS
    assert receipt["product_adapter_registry"]["status"] == "VERIFIED"
    assert "codex" in receipt["product_adapter_registry"]["adapter_ids"]
    assert "openai_responses" in receipt["product_adapter_registry"]["adapter_ids"]
    assert receipt["backend_classification_counts"]["goal_agent"] >= 1
    assert receipt["backend_classification_counts"]["product_broker"] >= 1
    codex_discovery = next(
        item for item in receipt["backend_evidence"] if item["evidence_id"] == "codex-product-adapter-discovery"
    )["discovery"]
    assert codex_discovery["source"] == "trusted_product_adapter_registry"
    assert codex_discovery["authentication_probe"]["status"] in {
        "EXECUTABLE_NOT_FOUND",
        "NOT_RUN",
    }
    assert codex_discovery["authentication_probe"]["passed"] is False
    assert receipt["qualification"] == {
        "qualified_live_product_backend_count": 0,
        "qualified_evidence_ids": [],
        "live_product_backend_available": False,
        "goal_agents_excluded": True,
        "echo_health_fake_excluded": True,
        "discovery_or_auth_alone_qualifies": False,
        "preflight_self_qualification_allowed": False,
        "status": "INSUFFICIENT_EVIDENCE",
    }
    assert all(
        not item["qualifies_as_live_product_backend"] for item in receipt["backend_evidence"]
    )


def test_eight_character_and_nested_suspected_credentials_never_persist(
    tmp_path: Path,
) -> None:
    project = _project_fixture(tmp_path)
    secret = "Abc12345"
    injected = _legacy_boolean_evidence(
        evidence_id=secret,
        adapter_id="fakeprovider",
        api_key=secret,
        nested={"token": secret, "credential": {"value": secret}},
    )
    output = tmp_path / "preflight-secret.json"
    receipt = run_preflight(
        project,
        environment=_environment(tmp_path, SESSION_SECRET=secret),
        backend_evidence=[injected],
        output_path=output,
        command_probes=False,
    )
    serialized = output.read_text(encoding="utf-8")
    assert secret not in serialized
    assert hashlib.sha256(secret.encode()).hexdigest() not in serialized
    assert receipt["qualification"]["qualified_live_product_backend_count"] == 0
    rejected = receipt["backend_evidence"][-1]
    assert rejected["evidence_id"] == "[REDACTED]"
    assert rejected["candidate_for_live_verification"] is False
    assert rejected["qualifies_as_live_product_backend"] is False
    assert "credential_field_forbidden_in_backend_evidence" in rejected["candidate_reasons"]
def test_account_probe_survives_getpass_pwd_fallback_failure(monkeypatch) -> None:
    monkeypatch.setattr(preflight_module, "_native_windows_username", lambda: "worker")
    monkeypatch.setattr(
        preflight_module.getpass,
        "getuser",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("pwd")),
    )

    account = preflight_module._account_identifier()

    assert account["current_os_account_observed"] is True
    assert account["account_identifier_sha256"]
    assert account["account_name_persisted"] is False


def test_account_probe_fails_closed_when_no_identity_source(monkeypatch) -> None:
    monkeypatch.setattr(preflight_module, "_native_windows_username", lambda: None)
    monkeypatch.setattr(
        preflight_module.getpass,
        "getuser",
        lambda: (_ for _ in ()).throw(ModuleNotFoundError("pwd")),
    )

    account = preflight_module._account_identifier()

    assert account["current_os_account_observed"] is False
    assert account["account_identifier_sha256"] is None
    assert account["real_non_administrator_current_account"] is False

