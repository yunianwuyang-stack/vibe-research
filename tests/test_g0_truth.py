from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness" / "scripts"))

import g0_truth  # noqa: E402
from bootstrap_contract import generate_candidate_lock  # noqa: E402
from common import canonical_json  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, *, decision: str = "PASS") -> tuple[dict, Ed25519PrivateKey, Path]:
    paths = {}
    for name, content in {
        "phase-contract.candidate.lock": b"{}\n",
        "checker-manifest.json": b"manifest",
        "report.json": b"report",
        "checker.py": b"checker",
        "generator.py": b"generator",
        "wrapper.py": b"wrapper",
        "bootstrap.json": b"bootstrap",
    }.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    runner = tmp_path / "harness" / "scripts" / "g0_truth.py"
    runner.parent.mkdir(parents=True)
    runner.write_bytes(b"frozen verifier")
    paths["phase-contract.candidate.lock"].write_bytes(
        canonical_json({"gates": [{"runner": {"path": "harness/scripts/g0_truth.py", "command": ["python", "harness/scripts/g0_truth.py"], "sha256": _hash(runner)}}]}) + b"\n"
    )
    paths["checker-manifest.json"].write_bytes(b"{}\n")
    scope = {
        "candidate_lock": "phase-contract.candidate.lock",
        "checker_manifest": "checker-manifest.json",
        "reports": [{"path": "report.json", "sha256": _hash(paths["report.json"])}],
        "checker_hashes": [{"path": "checker.py", "sha256": _hash(paths["checker.py"])}],
        "generator_hashes": [{"path": "generator.py", "sha256": _hash(paths["generator.py"])}],
        "wrapper": "wrapper.py",
        "bootstrap": "bootstrap.json",
    }
    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": "1.0",
        "receipt_id": "receipt-1",
        "issuer_key_id": "issuer-1",
        "algorithm": "Ed25519",
        "decision": decision,
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "revocation": "none",
        "reviewer_scope": scope,
        "scope_hash": hashlib.sha256(canonical_json(scope)).hexdigest(),
        "candidate_lock_sha256": _hash(paths["phase-contract.candidate.lock"]),
        "checker_manifest_sha256": _hash(paths["checker-manifest.json"]),
        "wrapper_sha256": _hash(paths["wrapper.py"]),
        "bootstrap_sha256": _hash(paths["bootstrap.json"]),
        "reviewer_permissions": ["g0:adjudicate"],
    }
    private = Ed25519PrivateKey.generate()
    envelope = {
        "payload": payload,
        "canonical_payload": base64.b64encode(canonical_json(payload)).decode("ascii"),
        "signature": base64.b64encode(private.sign(canonical_json(payload))).decode("ascii"),
    }
    return envelope, private, paths["report.json"]


def _write_canonical(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(value) + b"\n")


def _protected_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    protected = tmp_path / "protected"
    protected.mkdir()
    envelope, private, _ = _fixture(tmp_path)
    public = base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")
    trust = {
        "schema_version": "1.0",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "issuers": {"issuer-1": {"algorithm": "Ed25519", "public_key_b64": public}},
    }
    runner_private = Ed25519PrivateKey.generate()
    runner_public = base64.b64encode(runner_private.public_key().public_bytes_raw()).decode("ascii")
    runner_trust = {
        "schema_version": "1.0",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "issuers": {"runner-1": {"algorithm": "Ed25519", "public_key_b64": runner_public, "permissions": ["g0:run"]}},
    }
    revocations = {
        "schema_version": "1.0",
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "revoked_receipt_ids": [],
    }
    trust_path = protected / "trust.json"
    runner_trust_path = protected / "runner-trust.json"
    revocation_path = protected / "revocations.json"
    ledger_path = protected / "replay.json"
    receipt_path = tmp_path / "receipt.json"
    _write_canonical(trust_path, trust)
    _write_canonical(runner_trust_path, runner_trust)
    _write_canonical(revocation_path, revocations)
    _write_canonical(ledger_path, {"schema_version": "1.0", "consumed_receipt_ids": []})
    _write_canonical(receipt_path, envelope)
    config_path = protected / "config.json"
    _write_canonical(
        config_path,
        {
            "schema_version": "1.0",
            "trust": {"path": "trust.json", "sha256": _hash(trust_path)},
            "runner_trust": {"path": "runner-trust.json", "sha256": _hash(runner_trust_path)},
            "revocations": {"path": "revocations.json", "sha256": _hash(revocation_path)},
            "replay_ledger": {"path": "replay.json"},
        },
    )
    return receipt_path, config_path, protected, envelope["payload"]["receipt_id"]


def _verify(tmp_path: Path, envelope: dict, private: Ed25519PrivateKey, **kwargs: object) -> dict:
    public = private.public_key().public_bytes_raw()
    return g0_truth.verify_receipt(
        envelope,
        root=tmp_path,
        trusted_issuers={"issuer-1": base64.b64encode(public).decode("ascii")},
        **kwargs,
    )


def test_signed_receipt_passes_with_exact_scope(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    assert _verify(tmp_path, envelope, private)["verdict"] == "PASS"


def test_signature_tamper_blocks(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    envelope["payload"]["decision"] = "FAIL"
    assert _verify(tmp_path, envelope, private)["reason"] == "canonical_payload_mismatch"


def test_unknown_issuer_blocks_before_acceptance(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    result = g0_truth.verify_receipt(envelope, root=tmp_path, trusted_issuers={})
    assert result == {"verdict": "BLOCKED", "reason": "untrusted_issuer"}


def test_expiry_revocation_and_replay_block(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    assert _verify(tmp_path, envelope, private, now=now)["reason"] == "receipt_expired_or_invalid_time"
    assert _verify(tmp_path, envelope, private, revoked_receipt_ids={"receipt-1"})["reason"] == "receipt_revoked"
    assert _verify(tmp_path, envelope, private, seen_receipt_ids={"receipt-1"})["reason"] == "receipt_replay"


def test_scope_path_escape_and_hash_drift_block(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    envelope["payload"]["reviewer_scope"]["reports"][0]["path"] = "../outside.json"
    envelope["payload"]["scope_hash"] = hashlib.sha256(canonical_json(envelope["payload"]["reviewer_scope"])).hexdigest()
    envelope["canonical_payload"] = base64.b64encode(canonical_json(envelope["payload"])).decode("ascii")
    envelope["signature"] = base64.b64encode(private.sign(canonical_json(envelope["payload"]))).decode("ascii")
    assert _verify(tmp_path, envelope, private)["reason"] == "reports_hash"


def test_missing_crypto_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    monkeypatch.setattr(g0_truth, "Ed25519PublicKey", None)
    assert _verify(tmp_path, envelope, private)["reason"] == "ed25519_unavailable"


def test_raw_receipt_requires_canonical_envelope_and_rejects_duplicate_keys(tmp_path: Path) -> None:
    receipt, config, protected, _ = _protected_fixture(tmp_path)
    receipt.write_bytes(receipt.read_bytes().replace(b'"payload":', b'  "payload" : ', 1))
    result = g0_truth.verify_adjudication(receipt, root=tmp_path, protected_root=protected, config_path=config)
    assert result["reason"] == "receipt_not_canonical"

    receipt.write_bytes(b'{"payload":{},"payload":{},"canonical_payload":"","signature":""}\n')
    result = g0_truth.verify_adjudication(receipt, root=tmp_path, protected_root=protected, config_path=config)
    assert result["reason"] == "receipt_duplicate_key"


def test_formal_adjudication_rejects_candidate_without_gates(tmp_path: Path) -> None:
    receipt, config, protected, _ = _protected_fixture(tmp_path)
    (tmp_path / "phase-contract.candidate.lock").write_bytes(b"{}\n")
    result = g0_truth.verify_adjudication(receipt, root=tmp_path, protected_root=protected, config_path=config)
    assert result["verdict"] == "BLOCKED"


def test_formal_runner_path_uses_canonical_forward_slashes(tmp_path: Path) -> None:
    receipt, config, protected, _ = _protected_fixture(tmp_path)
    candidate = json.loads((tmp_path / "phase-contract.candidate.lock").read_text(encoding="utf-8"))
    candidate["gates"][0]["section"] = "G0"
    candidate["gates"][0]["runner"]["path"] = "harness/scripts/g0_truth.py"
    candidate["gates"][0]["runner"]["command"] = ["python", "harness/scripts/g0_truth.py", "--gate-id", "GATE-REQ-G0.1"]
    (tmp_path / "phase-contract.candidate.lock").write_bytes(canonical_json(candidate) + b"\n")
    result = g0_truth.verify_adjudication(receipt, root=tmp_path, protected_root=protected, config_path=config)
    assert result["reason"] != "candidate_lock_runner_path"


def test_protected_config_consumes_receipt_once_atomically(tmp_path: Path) -> None:
    receipt, config, protected, receipt_id = _protected_fixture(tmp_path)
    result = g0_truth.verify_adjudication(receipt, root=tmp_path, protected_root=protected, config_path=config)
    assert result["verdict"] == "BLOCKED"
    ledger = json.loads((protected / "replay.json").read_text(encoding="utf-8"))
    assert ledger["consumed_receipt_ids"] == []
    assert g0_truth.verify_adjudication(
        receipt, root=tmp_path, protected_root=protected, config_path=config
    )["verdict"] == "BLOCKED"


def test_protected_config_rejects_hash_drift_and_expired_revocations(tmp_path: Path) -> None:
    receipt, config, protected, _ = _protected_fixture(tmp_path)
    (protected / "trust.json").write_bytes((protected / "trust.json").read_bytes() + b" ")
    assert g0_truth.verify_adjudication(
        receipt, root=tmp_path, protected_root=protected, config_path=config
    )["reason"] == "trust_hash"


def test_scope_binds_real_wrapper_and_bootstrap_files(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    (tmp_path / "wrapper.py").write_bytes(b"wrapper")
    (tmp_path / "bootstrap.json").write_bytes(b"bootstrap")
    envelope["payload"]["reviewer_scope"].update(
        {"wrapper": "wrapper.py", "bootstrap": "bootstrap.json"}
    )
    envelope["payload"]["wrapper_sha256"] = _hash(tmp_path / "wrapper.py")
    envelope["payload"]["bootstrap_sha256"] = _hash(tmp_path / "bootstrap.json")
    envelope["payload"]["scope_hash"] = hashlib.sha256(
        canonical_json(envelope["payload"]["reviewer_scope"])
    ).hexdigest()
    envelope["canonical_payload"] = base64.b64encode(canonical_json(envelope["payload"])).decode("ascii")
    envelope["signature"] = base64.b64encode(private.sign(canonical_json(envelope["payload"]))).decode("ascii")
    assert _verify(tmp_path, envelope, private)["verdict"] == "PASS"
    (tmp_path / "wrapper.py").write_bytes(b"tampered")
    assert _verify(tmp_path, envelope, private)["reason"] == "wrapper_hash"


def _formal_bundle(
    tmp_path: Path,
    *,
    report_kind: str = "signed",
    runner_exit_code: int = 0,
    runner_sha_override: str | None = None,
) -> dict[str, Path]:
    """Build a test-only formal candidate with a separately trusted runner signer."""
    root = tmp_path / "root"
    (root / "harness" / "scripts").mkdir(parents=True)
    for relative in ("harness/phase-contract.lock", "harness/scripts/g0_truth.py", "harness/scripts/verify_truth.py"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    bootstrap = root / "bootstrap.json"
    shutil.copyfile(Path(r"D:\科研软件制作\开发指导.bootstrap.json"), bootstrap)
    contract = json.loads(bootstrap.read_text(encoding="utf-8"))
    candidate = generate_candidate_lock(contract, root=root, bootstrap_path=bootstrap, authoritative_lock_path=root / "harness/phase-contract.lock")
    now = datetime.now(timezone.utc)
    reviewer_key = Ed25519PrivateKey.generate()
    runner_key = Ed25519PrivateKey.generate()
    protected = root / "protected"
    protected.mkdir()
    reviewer_public = base64.b64encode(reviewer_key.public_key().public_bytes_raw()).decode("ascii")
    runner_public = base64.b64encode(runner_key.public_key().public_bytes_raw()).decode("ascii")
    trust_path = protected / "trust.json"
    runner_trust_path = protected / "runner-trust.json"
    revocation_path = protected / "revocations.json"
    ledger_path = protected / "replay.json"
    _write_canonical(trust_path, {"schema_version": "1.0", "expires_at": (now + timedelta(minutes=5)).isoformat(), "issuers": {"reviewer": {"algorithm": "Ed25519", "public_key_b64": reviewer_public}}})
    _write_canonical(runner_trust_path, {"schema_version": "1.0", "expires_at": (now + timedelta(minutes=5)).isoformat(), "issuers": {"runner": {"algorithm": "Ed25519", "public_key_b64": runner_public, "permissions": ["g0:run"]}}})
    _write_canonical(revocation_path, {"schema_version": "1.0", "expires_at": (now + timedelta(minutes=5)).isoformat(), "revoked_receipt_ids": []})
    _write_canonical(ledger_path, {"schema_version": "1.0", "consumed_receipt_ids": []})
    config_path = protected / "config.json"
    _write_canonical(config_path, {"schema_version": "1.0", "trust": {"path": "trust.json", "sha256": _hash(trust_path)}, "runner_trust": {"path": "runner-trust.json", "sha256": _hash(runner_trust_path)}, "revocations": {"path": "revocations.json", "sha256": _hash(revocation_path)}, "replay_ledger": {"path": "replay.json"}})
    for gate in candidate["gates"]:
        if gate["section"] != "G0":
            continue
        report_path = root / "harness" / "evidence" / "G0" / f"{gate['id']}.json"
        if report_kind == "bare":
            _write_canonical(report_path, {"gate_id": gate["id"], "verdict": "PASS"})
            continue
        root_receipt_relative = f"harness/evidence/G0/root-receipts/{gate['id']}.json"
        root_receipt_path = root / root_receipt_relative
        _write_canonical(root_receipt_path, {"schema_version": "1.0", "kind": "gate_root_contract_os_hash", "gate_id": gate["id"], "expected_sha256": _hash(bootstrap), "actual_sha256": _hash(bootstrap), "verdict": "PASS"})
        truth_file = root / "harness" / "scripts" / "g0_truth.py"
        input_artifacts = [{"path": "harness/scripts/g0_truth.py", "sha256": _hash(truth_file), "size": truth_file.stat().st_size}]
        metrics = {"numerator": 1, "denominator": 1, "strata": ["trusted_runner"], "abstentions": 0}
        checks = {"trusted_runner": "PASS"}
        output_manifest = {"checks": checks, "metrics": metrics, "verdict": "PASS"}
        runner_receipt_relative = f"harness/evidence/G0/runner-receipts/{gate['id']}.json"
        report = {
            "schema_version": "1.0", "gate_id": gate["id"], "requirement_ids": gate["requirement_ids"],
            "requirement_sha256": gate["requirement_sha256"], "runner_sha256": gate["runner"]["sha256"],
            "phase": "G0", "verdict": "PASS", "required": True, "metrics": metrics,
            "runner_receipt": runner_receipt_relative, "root_contract_receipt": root_receipt_relative,
            "root_contract_sha256": _hash(bootstrap), "input_artifacts": input_artifacts,
            "input_manifest_sha256": hashlib.sha256(canonical_json(input_artifacts)).hexdigest(),
            "output_manifest": output_manifest,
            "output_manifest_sha256": hashlib.sha256(canonical_json(output_manifest)).hexdigest(),
            "checks": checks, "artifacts": input_artifacts, "external_validation": "pending",
            "release_qualification": "pending",
        }
        _write_canonical(report_path, report)
        runner_receipt_path = root / runner_receipt_relative
        if report_kind == "unsigned":
            _write_canonical(runner_receipt_path, {"schema_version": "1.0", "kind": "unsigned_local_derivation"})
            continue
        runner_payload = {
            "schema_version": "1.0", "receipt_id": f"runner-{gate['id']}", "issuer_key_id": "runner",
            "algorithm": "Ed25519", "kind": "g0_trusted_runner_receipt", "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(), "revocation": "none",
            "runner_permissions": ["g0:run"], "gate_id": gate["id"], "report_sha256": _hash(report_path),
            "candidate_runner_path": gate["runner"]["path"], "candidate_runner_sha256": runner_sha_override or gate["runner"]["sha256"],
            "candidate_runner_command": gate["runner"]["command"], "input_manifest_sha256": report["input_manifest_sha256"],
            "output_manifest_sha256": report["output_manifest_sha256"], "exit_code": runner_exit_code,
            "timed_out": False, "verdict": "PASS", "root_contract_sha256": report["root_contract_sha256"],
        }
        _write_canonical(runner_receipt_path, {"payload": runner_payload, "canonical_payload": base64.b64encode(canonical_json(runner_payload)).decode("ascii"), "signature": base64.b64encode(runner_key.sign(canonical_json(runner_payload))).decode("ascii")})
    generate_candidate_lock(contract, root=root, bootstrap_path=bootstrap, authoritative_lock_path=root / "harness/phase-contract.lock")
    report_set = json.loads((root / "harness" / "evidence" / "G0" / "g0-report-set.json").read_text(encoding="utf-8"))
    scope = {
        "candidate_lock": "harness/phase-contract.candidate.lock", "checker_manifest": "harness/phase-contract.candidate.manifest.json",
        "reports": [{"path": item["path"], "sha256": item["sha256"]} for item in report_set["gate_reports"]],
        "checker_hashes": [{"path": "harness/scripts/g0_truth.py", "sha256": _hash(root / "harness" / "scripts" / "g0_truth.py")}],
        "generator_hashes": [{"path": "harness/scripts/verify_truth.py", "sha256": _hash(root / "harness" / "scripts" / "verify_truth.py")}],
        "wrapper": "harness/scripts/g0_truth.py", "bootstrap": "bootstrap.json",
    }
    def reviewer_receipt(receipt_id: str) -> dict:
        payload = {
            "schema_version": "1.0", "receipt_id": receipt_id, "issuer_key_id": "reviewer", "algorithm": "Ed25519",
            "decision": "PASS", "issued_at": now.isoformat(), "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "revocation": "none", "reviewer_scope": scope, "scope_hash": hashlib.sha256(canonical_json(scope)).hexdigest(),
            "candidate_lock_sha256": _hash(root / scope["candidate_lock"]), "checker_manifest_sha256": _hash(root / scope["checker_manifest"]),
            "wrapper_sha256": _hash(root / scope["wrapper"]), "bootstrap_sha256": _hash(bootstrap), "reviewer_permissions": ["g0:adjudicate"],
        }
        return {"payload": payload, "canonical_payload": base64.b64encode(canonical_json(payload)).decode("ascii"), "signature": base64.b64encode(reviewer_key.sign(canonical_json(payload))).decode("ascii")}
    api_receipt = root / "api-receipt.json"
    cli_receipt = root / "cli-receipt.json"
    _write_canonical(api_receipt, reviewer_receipt("review-api"))
    _write_canonical(cli_receipt, reviewer_receipt("review-cli"))
    return {"root": root, "bootstrap": bootstrap, "protected": protected, "config": config_path, "api_receipt": api_receipt, "cli_receipt": cli_receipt}


def _formal_result(bundle: dict[str, Path], receipt_name: str = "api_receipt") -> dict:
    return g0_truth.verify_adjudication(bundle[receipt_name], root=bundle["root"], protected_root=bundle["protected"], config_path=bundle["config"], bootstrap_path=bundle["bootstrap"], authoritative_lock_path=bundle["root"] / "harness" / "phase-contract.lock", gate_id="GATE-REQ-G0.1")


def test_formal_adjudication_blocks_bare_pass_reports(tmp_path: Path) -> None:
    result = _formal_result(_formal_bundle(tmp_path, report_kind="bare"))
    assert result["verdict"] == "BLOCKED"
    assert "report_schema:gate_report_fields" in result["reason"]


def test_formal_adjudication_blocks_unsigned_runner_receipt(tmp_path: Path) -> None:
    result = _formal_result(_formal_bundle(tmp_path, report_kind="unsigned"))
    assert result["verdict"] == "BLOCKED"
    assert "runner_receipt:envelope_fields" in result["reason"]


def test_formal_adjudication_blocks_runner_candidate_hash_mismatch(tmp_path: Path) -> None:
    result = _formal_result(_formal_bundle(tmp_path, runner_sha_override="0" * 64))
    assert result["verdict"] == "BLOCKED"
    assert "runner_receipt:candidate_runner_binding" in result["reason"]


def test_formal_adjudication_blocks_nonzero_runner_exit(tmp_path: Path) -> None:
    result = _formal_result(_formal_bundle(tmp_path, runner_exit_code=7))
    assert result["verdict"] == "BLOCKED"
    assert "runner_receipt:runner_execution" in result["reason"]


def test_test_only_signed_runner_receipts_pass_formal_api_and_cli(tmp_path: Path) -> None:
    bundle = _formal_bundle(tmp_path)
    assert _formal_result(bundle)["verdict"] == "PASS"
    command = [str(ROOT / "runtime" / "python" / "python.exe"), str(ROOT / "harness" / "scripts" / "g0_truth.py"), "--gate-id", "GATE-REQ-G0.1", "--receipt", str(bundle["cli_receipt"]), "--protected-root", str(bundle["protected"]), "--config", str(bundle["config"]), "--root", str(bundle["root"]), "--bootstrap", str(bundle["bootstrap"]), "--authoritative-lock", str(bundle["root"] / "harness" / "phase-contract.lock")]
    completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert json.loads(completed.stdout.decode("utf-8"))["verdict"] == "PASS"

def test_cli_rejects_gate_id_not_in_signed_g0_scope(tmp_path: Path) -> None:
    receipt, key, _ = _fixture(tmp_path)
    command = [str(ROOT / "runtime" / "python" / "python.exe"), str(ROOT / "harness" / "scripts" / "g0_truth.py"), "--gate-id", "GATE-NOT-G0", "--receipt", str(tmp_path / "receipt.json"), "--protected-root", str(tmp_path), "--config", str(tmp_path / "config.json"), "--root", str(tmp_path)]
    _write_canonical(tmp_path / "receipt.json", receipt)
    completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert completed.returncode != 0
    assert json.loads(completed.stdout.decode("utf-8"))["verdict"] == "BLOCKED"



def test_scope_rejects_symlink_segment(tmp_path: Path) -> None:
    envelope, private, _ = _fixture(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    (real / "report.json").write_bytes(b"report")
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as symlink_error:
        # Windows junctions do not need Developer Mode and are reparse points,
        # so they exercise the same segment-rejection branch as a directory symlink.
        if os.name != "nt":
            pytest.fail(f"cannot create test-owned reparse point: {symlink_error}")
        # Run from tmp_path with fixed relative operands: cmd.exe does not mangle
        # them, and both the link and target remain entirely pytest-owned.
        command = ["cmd.exe", "/d", "/c", "mklink /J linked real"]
        try:
            junction = subprocess.run(
                command,
                cwd=tmp_path,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as junction_error:
            pytest.fail(f"cannot create test-owned junction after symlink failure: {junction_error}")
        if junction.returncode != 0 or not link.is_dir():
            pytest.fail(
                "cannot create test-owned junction after symlink failure: "
                f"exit={junction.returncode}; stdout={junction.stdout!r}; stderr={junction.stderr!r}"
            )
        attributes = getattr(link.lstat(), "st_file_attributes", 0)
        assert attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT, "junction fallback must be a reparse point"
    envelope["payload"]["reviewer_scope"]["reports"] = [
        {"path": "linked/report.json", "sha256": _hash(real / "report.json")}
    ]
    envelope["payload"]["scope_hash"] = hashlib.sha256(canonical_json(envelope["payload"]["reviewer_scope"])).hexdigest()
    envelope["canonical_payload"] = base64.b64encode(canonical_json(envelope["payload"])).decode("ascii")
    envelope["signature"] = base64.b64encode(private.sign(canonical_json(envelope["payload"]))).decode("ascii")
    assert _verify(tmp_path, envelope, private)["reason"] == "reports_hash"
