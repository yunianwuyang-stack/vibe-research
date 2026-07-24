from __future__ import annotations

import argparse
import base64
import sys
import binascii
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_contract import EXPECTED_FILE_SHA256, validate_candidate_lock, validate_gate_report
from common import canonical_json, sha256_file

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except Exception:
    InvalidSignature = Exception
    Ed25519PublicKey = None

PAYLOAD_FIELDS = {
    "schema_version", "receipt_id", "issuer_key_id", "algorithm", "decision", "issued_at", "expires_at",
    "revocation", "reviewer_scope", "scope_hash", "candidate_lock_sha256", "checker_manifest_sha256",
    "wrapper_sha256", "bootstrap_sha256", "reviewer_permissions",
}
SCOPE_FIELDS = {"candidate_lock", "checker_manifest", "reports", "checker_hashes", "generator_hashes", "wrapper", "bootstrap"}
RUNNER_PAYLOAD_FIELDS = {
    "schema_version", "receipt_id", "issuer_key_id", "algorithm", "kind", "issued_at", "expires_at", "revocation",
    "runner_permissions", "gate_id", "report_sha256", "candidate_runner_path", "candidate_runner_sha256",
    "candidate_runner_command", "input_manifest_sha256", "output_manifest_sha256", "exit_code", "timed_out",
    "verdict", "root_contract_sha256",
}


def _blocked(reason: str) -> dict[str, str]:
    return {"verdict": "BLOCKED", "reason": reason}


def _sha(path: Path) -> str:
    return sha256_file(path)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except ValueError:
        return None


def _strict_json(raw: bytes, *, canonical: bool = True) -> tuple[Any | None, str | None]:
    duplicates: list[str] = []
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                duplicates.append(key)
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError):
        return None, "unreadable"
    if duplicates:
        return None, "duplicate_key"
    if canonical and raw != canonical_json(value) + b"\n":
        return None, "not_canonical"
    return value, None


def _contained_regular(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw or "\\" in raw or Path(raw).is_absolute():
        return None
    relative = Path(raw)
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root
        for part in relative.parts:
            candidate /= part
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400):
                return None
        candidate = candidate.resolve(strict=True)
        candidate.relative_to(root)
        before = candidate.stat()
        if not stat.S_ISREG(before.st_mode):
            return None
        with candidate.open("rb") as handle:
            opened = os.fstat(handle.fileno())
        after = candidate.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            return None
        return candidate
    except (OSError, ValueError):
        return None


def _entry_hashes(root: Path, entries: Any, name: str) -> str | None:
    if not isinstance(entries, list) or not entries:
        return f"{name}_empty"
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256"}:
            return f"{name}_entry"
        path = _contained_regular(root, entry["path"])
        if path is None or not isinstance(entry["sha256"], str) or _sha(path) != entry["sha256"]:
            return f"{name}_hash"
    return None


def _scope(
    payload: Mapping[str, Any], root: Path, *, formal: bool = False,
    bootstrap_path: Path | None = None, authoritative_lock_path: Path | None = None,
    gate_id: str | None = None, runner_issuers: Mapping[str, Any] | None = None,
    runner_revoked_receipt_ids: set[str] | None = None, now: datetime | None = None,
) -> str | None:
    scope = payload.get("reviewer_scope")
    if not isinstance(scope, Mapping) or set(scope) != SCOPE_FIELDS:
        return "reviewer_scope_fields"
    for key, field in (("candidate_lock", "candidate_lock_sha256"), ("checker_manifest", "checker_manifest_sha256"), ("wrapper", "wrapper_sha256"), ("bootstrap", "bootstrap_sha256")):
        path = _contained_regular(root, scope[key])
        if path is None or payload.get(field) != _sha(path):
            return f"{key}_hash"
    for name in ("reports", "checker_hashes", "generator_hashes"):
        error = _entry_hashes(root, scope[name], name)
        if error:
            return error
    if payload.get("scope_hash") != hashlib.sha256(canonical_json(scope)).hexdigest():
        return "scope_hash"
    return _candidate_lock(
        payload, root, required=formal, bootstrap_path=bootstrap_path,
        authoritative_lock_path=authoritative_lock_path, gate_id=gate_id,
        runner_issuers=runner_issuers, runner_revoked_receipt_ids=runner_revoked_receipt_ids,
        now=now,
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _verify_runner_receipt(
    receipt: Mapping[str, Any], *, trusted_issuers: Mapping[str, Any], now: datetime,
    revoked_receipt_ids: set[str], seen_receipt_ids: set[str],
) -> dict[str, str]:
    """Verify a trusted runner receipt under a trust root separate from reviewers."""
    if Ed25519PublicKey is None:
        return _blocked("ed25519_unavailable")
    if set(receipt) != {"payload", "canonical_payload", "signature"} or not isinstance(receipt.get("payload"), Mapping):
        return _blocked("envelope_fields")
    payload = receipt["payload"]
    if set(payload) != RUNNER_PAYLOAD_FIELDS:
        return _blocked("payload_fields")
    body = canonical_json(payload)
    if receipt.get("canonical_payload") != base64.b64encode(body).decode("ascii"):
        return _blocked("canonical_payload_mismatch")
    issuer = payload.get("issuer_key_id")
    record = trusted_issuers.get(issuer) if isinstance(issuer, str) else None
    if not isinstance(record, Mapping):
        return _blocked("untrusted_issuer")
    trust_permissions = record.get("permissions")
    if record.get("algorithm") != "Ed25519" or not isinstance(trust_permissions, list) or "g0:run" not in trust_permissions:
        return _blocked("trust_acl")
    try:
        key = base64.b64decode(record.get("public_key_b64"), validate=True)
        signature = base64.b64decode(receipt.get("signature"), validate=True)
    except (TypeError, ValueError, binascii.Error):
        return _blocked("untrusted_issuer")
    if payload.get("algorithm") != "Ed25519" or len(key) != 32:
        return _blocked("untrusted_issuer")
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, body)
    except (InvalidSignature, ValueError, TypeError):
        return _blocked("signature_invalid")
    issued, expires = _parse_time(payload.get("issued_at")), _parse_time(payload.get("expires_at"))
    if issued is None or expires is None or not issued <= now < expires:
        return _blocked("expired_or_invalid_time")
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id or receipt_id in revoked_receipt_ids:
        return _blocked("revoked")
    if receipt_id in seen_receipt_ids:
        return _blocked("replay")
    permissions = payload.get("runner_permissions")
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("kind") != "g0_trusted_runner_receipt"
        or payload.get("revocation") != "none"
        or not isinstance(permissions, list)
        or any(not isinstance(permission, str) for permission in permissions)
        or "g0:run" not in permissions
    ):
        return _blocked("runner_acl")
    if (
        not isinstance(payload.get("gate_id"), str)
        or not _is_sha256(payload.get("report_sha256"))
        or not isinstance(payload.get("candidate_runner_path"), str)
        or not _is_sha256(payload.get("candidate_runner_sha256"))
        or not isinstance(payload.get("candidate_runner_command"), list)
        or not payload["candidate_runner_command"]
        or any(not isinstance(item, str) or not item for item in payload["candidate_runner_command"])
        or not _is_sha256(payload.get("input_manifest_sha256"))
        or not _is_sha256(payload.get("output_manifest_sha256"))
        or not _is_sha256(payload.get("root_contract_sha256"))
    ):
        return _blocked("payload_binding_fields")
    if payload.get("exit_code") != 0 or payload.get("timed_out") is not False or payload.get("verdict") != "PASS":
        return _blocked("runner_execution")
    seen_receipt_ids.add(receipt_id)
    return {"verdict": "PASS", "receipt_id": receipt_id}


def _validate_formal_g0_report(
    report: Mapping[str, Any], report_path: Path, gate: Mapping[str, Any], *, root: Path,
    trusted_runner_issuers: Mapping[str, Any], now: datetime, revoked_receipt_ids: set[str],
    seen_runner_receipt_ids: set[str],
) -> str | None:
    static_result = validate_gate_report(dict(report))
    if static_result.get("verdict") == "INVALID":
        return f"report_schema:{static_result.get('reason', 'invalid')}"
    if static_result.get("verdict") != "PASS":
        return "report_not_pass"
    if report.get("gate_id") != gate.get("id"):
        return "gate_id"
    if report.get("requirement_ids") != gate.get("requirement_ids") or report.get("requirement_sha256") != gate.get("requirement_sha256"):
        return "requirement_binding"
    runner = gate.get("runner")
    if not isinstance(runner, Mapping) or report.get("runner_sha256") != runner.get("sha256"):
        return "runner_hash"
    input_artifacts = report["input_artifacts"]
    output_manifest = {"checks": report["checks"], "metrics": report["metrics"], "verdict": report["verdict"]}
    if report.get("input_manifest_sha256") != hashlib.sha256(canonical_json(input_artifacts)).hexdigest():
        return "input_manifest_hash"
    if report.get("output_manifest") != output_manifest or report.get("output_manifest_sha256") != hashlib.sha256(canonical_json(output_manifest)).hexdigest():
        return "output_manifest_hash"
    if report.get("root_contract_sha256") != EXPECTED_FILE_SHA256:
        return "root_contract_hash"
    root_receipt_path = _contained_regular(root, report["root_contract_receipt"])
    if root_receipt_path is None:
        return "root_contract_receipt_path"
    root_receipt, root_error = _strict_json(root_receipt_path.read_bytes())
    if root_error or not isinstance(root_receipt, Mapping):
        return "root_contract_receipt_invalid"
    if root_receipt.get("verdict") != "PASS" or root_receipt.get("actual_sha256") != EXPECTED_FILE_SHA256:
        return "root_contract_receipt_hash"
    runner_receipt_path = _contained_regular(root, report["runner_receipt"])
    if runner_receipt_path is None:
        return "runner_receipt_path"
    runner_receipt, runner_error = _strict_json(runner_receipt_path.read_bytes())
    if runner_error or not isinstance(runner_receipt, Mapping):
        return "runner_receipt_invalid"
    runner_result = _verify_runner_receipt(
        runner_receipt, trusted_issuers=trusted_runner_issuers, now=now,
        revoked_receipt_ids=revoked_receipt_ids, seen_receipt_ids=seen_runner_receipt_ids,
    )
    if runner_result.get("verdict") != "PASS":
        return f"runner_receipt:{runner_result.get('reason', 'invalid')}"
    payload = runner_receipt["payload"]
    if payload.get("gate_id") != gate.get("id") or payload.get("report_sha256") != _sha(report_path):
        return "runner_receipt:report_binding"
    if (
        payload.get("candidate_runner_path") != runner.get("path")
        or payload.get("candidate_runner_sha256") != runner.get("sha256")
        or payload.get("candidate_runner_command") != runner.get("command")
    ):
        return "runner_receipt:candidate_runner_binding"
    if payload.get("input_manifest_sha256") != report.get("input_manifest_sha256") or payload.get("output_manifest_sha256") != report.get("output_manifest_sha256"):
        return "runner_receipt:manifest_binding"
    if payload.get("root_contract_sha256") != report.get("root_contract_sha256"):
        return "runner_receipt:root_contract_binding"
    return None


def _candidate_lock(
    payload: Mapping[str, Any], root: Path, *, required: bool,
    bootstrap_path: Path | None = None, authoritative_lock_path: Path | None = None,
    gate_id: str | None = None, runner_issuers: Mapping[str, Any] | None = None,
    runner_revoked_receipt_ids: set[str] | None = None, now: datetime | None = None,
) -> str | None:
    scope = payload["reviewer_scope"]
    lock_path = _contained_regular(root, scope["candidate_lock"])
    manifest_path = _contained_regular(root, scope["checker_manifest"])
    assert lock_path and manifest_path
    lock, error = _strict_json(lock_path.read_bytes())
    if error or not isinstance(lock, Mapping):
        return "candidate_lock_invalid"
    gates = lock.get("gates")
    if not isinstance(gates, list) or not gates:
        return "candidate_lock_gates" if required else None
    if not required:
        return None
    for gate in gates:
        if not isinstance(gate, Mapping) or not isinstance(gate.get("id"), str):
            return "candidate_lock_gate_schema"
        if gate.get("section") != "G0":
            continue
        runner = gate.get("runner")
        if not isinstance(runner, Mapping) or runner.get("path") != "harness/scripts/g0_truth.py":
            return "candidate_lock_runner_path"
        runner_path = _contained_regular(root, runner["path"])
        expected_command = ["python", "harness/scripts/g0_truth.py", "--gate-id", gate["id"]]
        if runner.get("command") != expected_command or runner_path is None or runner.get("sha256") != _sha(runner_path):
            return "candidate_lock_runner_binding"
    manifest, manifest_error = _strict_json(manifest_path.read_bytes())
    if manifest_error or not isinstance(manifest, Mapping):
        return "checker_manifest_invalid"
    bootstrap = bootstrap_path or Path(r"D:\科研软件制作\开发指导.bootstrap.json")
    try:
        contract = json.loads(bootstrap.read_text(encoding="utf-8"))
        candidate_result = validate_candidate_lock(dict(lock), contract, root=root, bootstrap_path=bootstrap, authoritative_lock_path=authoritative_lock_path)
    except (OSError, json.JSONDecodeError, ValueError):
        return "candidate_lock_validation_error"
    if candidate_result.get("verdict") != "CANDIDATE":
        return f"candidate_lock_{candidate_result.get('reason', 'invalid')}"
    report_binding = lock.get("g0_report_set")
    if not isinstance(report_binding, Mapping) or set(report_binding) != {"path", "sha256"}:
        return "g0_report_set_binding"
    report_set_path = _contained_regular(root, report_binding["path"])
    if report_set_path is None or report_binding["sha256"] != _sha(report_set_path):
        return "g0_report_set_hash"
    report_set, report_error = _strict_json(report_set_path.read_bytes())
    if report_error or not isinstance(report_set, Mapping) or set(report_set) != {"schema_version", "gate_reports"} or report_set.get("schema_version") != "1.0":
        return "g0_report_set_schema"
    reports = report_set.get("gate_reports")
    g0_ids = [gate["id"] for gate in gates if gate.get("section") == "G0"]
    if not isinstance(reports, list) or [item.get("gate_id") if isinstance(item, Mapping) else None for item in reports] != sorted(g0_ids):
        return "g0_report_set_gate_ids"
    scope_reports = payload["reviewer_scope"]["reports"]
    if not isinstance(scope_reports, list):
        return "reports_schema"
    expected_scope: list[dict[str, str]] = []
    report_records: list[tuple[Mapping[str, Any], Path]] = []
    for entry in reports:
        if not isinstance(entry, Mapping) or set(entry) != {"gate_id", "path", "sha256"} or not isinstance(entry.get("sha256"), str):
            return "g0_report_set_unavailable"
        report_path = _contained_regular(root, entry["path"])
        if report_path is None or _sha(report_path) != entry["sha256"]:
            return "g0_report_set_report_hash"
        expected_scope.append({"path": entry["path"], "sha256": entry["sha256"]})
        report_records.append((entry, report_path))
    if scope_reports != expected_scope:
        return "g0_report_set_scope_mismatch"
    if runner_issuers is None:
        return "runner_trust_missing"
    seen_runner_receipt_ids: set[str] = set()
    gate_by_id = {gate["id"]: gate for gate in gates if gate.get("section") == "G0"}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    revoked = runner_revoked_receipt_ids or set()
    for entry, report_path in report_records:
        report, report_error = _strict_json(report_path.read_bytes())
        if report_error or not isinstance(report, Mapping):
            return f"g0_report:{entry['gate_id']}:unreadable"
        report_error = _validate_formal_g0_report(
            report, report_path, gate_by_id[entry["gate_id"]], root=root,
            trusted_runner_issuers=runner_issuers, now=current,
            revoked_receipt_ids=revoked, seen_runner_receipt_ids=seen_runner_receipt_ids,
        )
        if report_error:
            return f"g0_report:{entry['gate_id']}:{report_error}"
    if gate_id is not None and gate_id not in g0_ids:
        return "gate_id_not_g0_candidate_gate"
    if gate_id is not None and gate_id not in {entry["gate_id"] for entry in reports}:
        return "gate_id_not_signed_report"
    return None

def verify_receipt(receipt: Mapping[str, Any], *, root: Path, trusted_issuers: Mapping[str, Any], now: datetime | None = None, revoked_receipt_ids: set[str] = set(), seen_receipt_ids: set[str] = set()) -> dict[str, str]:
    if Ed25519PublicKey is None:
        return _blocked("ed25519_unavailable")
    if set(receipt) != {"payload", "canonical_payload", "signature"} or not isinstance(receipt.get("payload"), Mapping):
        return _blocked("envelope_fields")
    payload = receipt["payload"]
    if set(payload) != PAYLOAD_FIELDS:
        return _blocked("payload_fields")
    body = canonical_json(payload)
    if receipt["canonical_payload"] != base64.b64encode(body).decode("ascii"):
        return _blocked("canonical_payload_mismatch")
    issuer = payload.get("issuer_key_id")
    record = trusted_issuers.get(issuer) if isinstance(issuer, str) else None
    key_text = record.get("public_key_b64") if isinstance(record, Mapping) else record
    try:
        key = base64.b64decode(key_text, validate=True)
        signature = base64.b64decode(receipt["signature"], validate=True)
    except (TypeError, ValueError, binascii.Error):
        return _blocked("untrusted_issuer")
    if payload.get("algorithm") != "Ed25519" or len(key) != 32:
        return _blocked("untrusted_issuer")
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, body)
    except (InvalidSignature, ValueError, TypeError):
        return _blocked("signature_invalid")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued, expires = _parse_time(payload.get("issued_at")), _parse_time(payload.get("expires_at"))
    if issued is None or expires is None or not issued <= current < expires:
        return _blocked("receipt_expired_or_invalid_time")
    receipt_id = payload.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id or receipt_id in revoked_receipt_ids:
        return _blocked("receipt_revoked")
    if receipt_id in seen_receipt_ids:
        return _blocked("receipt_replay")
    permissions = payload.get("reviewer_permissions")
    if (
        payload.get("decision") != "PASS"
        or payload.get("revocation") != "none"
        or not isinstance(permissions, list)
        or any(not isinstance(permission, str) for permission in permissions)
        or "g0:adjudicate" not in permissions
    ):
        return _blocked("receipt_acl_or_decision")
    error = _scope(payload, root, formal=False)
    return _blocked(error) if error else {"verdict": "PASS", "receipt_id": receipt_id}


def _config(
    protected_root: Path, config_path: Path, now: datetime,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None, list[str] | None, Path | None, str | None]:
    try:
        protected = protected_root.resolve(strict=True)
        config_path.resolve(strict=True).relative_to(protected)
        config, error = _strict_json(config_path.read_bytes())
    except (OSError, ValueError):
        return None, None, None, None, "protected_config_path"
    if error or not isinstance(config, Mapping):
        return None, None, None, None, "protected_config_invalid"
    loaded: dict[str, Mapping[str, Any]] = {}
    for name in ("trust", "runner_trust", "revocations"):
        binding = config.get(name)
        if not isinstance(binding, Mapping):
            return None, None, None, None, f"{name}_binding"
        path = _contained_regular(protected, binding.get("path"))
        if path is None or binding.get("sha256") != _sha(path):
            return None, None, None, None, f"{name}_hash"
        record, err = _strict_json(path.read_bytes())
        if err or not isinstance(record, Mapping) or (expiry := _parse_time(record.get("expires_at"))) is None or now >= expiry:
            return None, None, None, None, f"{name}_expired"
        loaded[name] = record
    ledger_binding = config.get("replay_ledger")
    ledger = _contained_regular(protected, ledger_binding.get("path") if isinstance(ledger_binding, Mapping) else None)
    if ledger is None:
        return None, None, None, None, "replay_path"
    reviewers = loaded["trust"].get("issuers")
    runners = loaded["runner_trust"].get("issuers")
    revoked = loaded["revocations"].get("revoked_receipt_ids")
    if not isinstance(reviewers, Mapping) or not isinstance(runners, Mapping) or not isinstance(revoked, list) or any(not isinstance(item, str) for item in revoked):
        return None, None, None, None, "protected_config_issuers_or_revocations"
    return reviewers, runners, revoked, ledger, None

def _consume(ledger: Path, receipt_id: str) -> str | None:
    lock = ledger.with_suffix(ledger.suffix + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return "replay_ledger_busy"
    try:
        os.close(fd)
        value, error = _strict_json(ledger.read_bytes())
        consumed = value.get("consumed_receipt_ids") if isinstance(value, Mapping) and not error else None
        if not isinstance(consumed, list): return "replay_ledger_invalid"
        if receipt_id in consumed: return "receipt_replay"
        temporary = ledger.with_suffix(ledger.suffix + ".tmp")
        temporary.write_bytes(canonical_json({"schema_version": "1.0", "consumed_receipt_ids": [*consumed, receipt_id]}) + b"\n")
        os.replace(temporary, ledger)
        return None
    finally:
        lock.unlink(missing_ok=True)


def verify_adjudication(
    receipt_path: Path,
    *,
    root: Path,
    protected_root: Path,
    config_path: Path,
    bootstrap_path: Path | None = None,
    authoritative_lock_path: Path | None = None,
    gate_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, str]:
    try: raw = receipt_path.read_bytes()
    except OSError: return _blocked("receipt_unreadable")
    receipt, error = _strict_json(raw)
    if error: return _blocked(f"receipt_{error}")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issuers, runner_issuers, revoked, ledger, error = _config(protected_root, config_path, current)
    if error or issuers is None or runner_issuers is None or revoked is None or ledger is None: return _blocked(error or "protected_config_invalid")
    result = verify_receipt(receipt, root=root, trusted_issuers=issuers, now=current, revoked_receipt_ids=set(revoked))
    if result["verdict"] != "PASS": return result
    scope_error = _scope(
        receipt["payload"], root, formal=True, bootstrap_path=bootstrap_path,
        authoritative_lock_path=authoritative_lock_path, gate_id=gate_id,
        runner_issuers=runner_issuers, runner_revoked_receipt_ids=set(revoked), now=current,
    )
    if scope_error: return _blocked(scope_error)
    error = _consume(ledger, result["receipt_id"])
    return _blocked(error) if error else result


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--gate-id")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--protected-root", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--bootstrap", type=Path)
    parser.add_argument("--authoritative-lock", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments, unknown = parser.parse_known_args()
    if unknown or not arguments.gate_id or not arguments.receipt or not arguments.protected_root or not arguments.config:
        result = _blocked("missing_required_anchor_parameters")
    else:
        result = verify_adjudication(
            arguments.receipt,
            root=arguments.root,
            protected_root=arguments.protected_root,
            config_path=arguments.config,
            bootstrap_path=arguments.bootstrap,
            authoritative_lock_path=arguments.authoritative_lock,
            gate_id=arguments.gate_id,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
