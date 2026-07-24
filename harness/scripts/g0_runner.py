from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import stat
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "backend"))

from bootstrap_contract import (  # noqa: E402
    EXPECTED_FILE_SHA256,
    EXPECTED_MERKLE_ROOT,
    EXPECTED_REQUIREMENTS,
    EXPECTED_TAMPER_VECTORS,
    run_tamper_vectors,
    validate_contract,
    validate_lock,
    validate_gate_report,
)
from common import atomic_write_json, canonical_json, sha256_file  # noqa: E402
from journal import JournalError, append_event, project, read_events, verify_events  # noqa: E402
from restore_drill import run_ephemeral_drill  # noqa: E402
from secret_scan import scan  # noqa: E402
from services.process_supervisor import ProcessSupervisor  # noqa: E402


class G0Error(RuntimeError):
    pass


G0_GATE_SPECS: dict[str, dict[str, list[str]]] = {
    "REQ-G0.1": {"checks": ["ownership", "restore"], "artifacts": ["baseline_manifest", "ownership", "restore"]},
    "REQ-G0.2": {"checks": ["ignored", "readonly", "restore"], "artifacts": ["baseline_manifest", "ignored", "readonly", "restore"]},
    "REQ-G0.3": {"checks": ["secret_scan"], "artifacts": ["secret_scan", "lane_unit"]},
    "REQ-G0.4": {"checks": ["ownership"], "artifacts": ["ownership", "baseline_manifest"]},
    "REQ-G0.5": {"checks": ["root_contract"], "artifacts": ["root_contract", "phase_lock", "bootstrap_contract"]},
    "REQ-G0.6": {"checks": ["lane_contract", "lanes"], "artifacts": ["pytest_config", "pytest_conftest", "lanes"]},
    "REQ-G0.7": {"checks": ["readonly"], "artifacts": ["readonly", "baseline_manifest"]},
    "REQ-G0.8": {"checks": ["lanes", "orphan_processes"], "artifacts": ["lanes", "process_supervisor"]},
    "REQ-G0-EXIT-001": {"checks": ["ownership", "restore"], "artifacts": ["ownership", "restore", "baseline_manifest"]},
    "REQ-G0-EXIT-002": {"checks": ["ignored", "readonly"], "artifacts": ["ignored", "readonly"]},
    "REQ-G0-EXIT-003": {"checks": ["ownership"], "artifacts": ["ownership", "baseline_manifest"]},
    "REQ-G0-EXIT-004": {"checks": ["secret_scan"], "artifacts": ["secret_scan"]},
    "REQ-G0-EXIT-005": {"checks": ["journal"], "artifacts": ["journal"]},
    "REQ-G0-EXIT-006": {"checks": ["root_contract"], "artifacts": ["root_contract", "phase_lock", "bootstrap_contract"]},
    "REQ-G0-EXIT-007": {"checks": ["lane_contract", "lanes"], "artifacts": ["pytest_config", "pytest_conftest", "lanes"]},
    "REQ-G0-EXIT-008": {"checks": ["lanes"], "artifacts": ["lanes"]},
    "REQ-G0-EXIT-009": {"checks": ["orphan_processes"], "artifacts": ["lanes", "process_supervisor"]},
}


def _run(command: list[str], *, cwd: Path, timeout: float = 120) -> dict[str, Any]:
    started = datetime_utc()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
        )
        return {
            "command": command,
            "started_utc": started,
            "finished_utc": datetime_utc(),
            "returncode": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", errors="replace"),
            "stderr": completed.stderr.decode("utf-8", errors="replace"),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "started_utc": started,
            "finished_utc": datetime_utc(),
            "returncode": -1,
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace"),
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace"),
            "timed_out": True,
        }
    except OSError as exc:
        return {
            "command": command,
            "started_utc": started,
            "finished_utc": datetime_utc(),
            "returncode": -1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "timed_out": False,
        }


def datetime_utc() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode:
        raise G0Error(f"git_{args[0]}_failed:{result.stderr.decode(errors='replace')}")
    return result.stdout


def _decode_path(raw: bytes) -> str:
    if not (raw.startswith(b'"') and raw.endswith(b'"')):
        return os.fsdecode(raw)
    data = raw[1:-1]
    output = bytearray()
    escapes = {ord("a"): 7, ord("b"): 8, ord("t"): 9, ord("n"): 10, ord("v"): 11, ord("f"): 12, ord("r"): 13, ord('"'): 34, ord("\\"): 92}
    index = 0
    while index < len(data):
        value = data[index]
        if value != 92:
            output.append(value)
            index += 1
            continue
        index += 1
        if index >= len(data):
            raise G0Error("invalid_quoted_git_path")
        value = data[index]
        if 48 <= value <= 55:
            digits = bytearray()
            while index < len(data) and len(digits) < 3 and 48 <= data[index] <= 55:
                digits.append(data[index])
                index += 1
            output.append(int(digits.decode("ascii"), 8))
        elif value in escapes:
            output.append(escapes[value])
            index += 1
        else:
            raise G0Error("invalid_git_path_escape")
    return os.fsdecode(bytes(output))


def _status_items(root: Path) -> dict[str, dict[str, Any]]:
    raw = _git(root, "status", "--porcelain=v2", "-z", "--branch", "--untracked-files=all")
    result: dict[str, dict[str, Any]] = {}
    for record in raw.split(b"\0"):
        if not record or record.startswith(b"# "):
            continue
        if record.startswith((b"? ", b"! ")):
            path = _decode_path(record[2:])
            result[path] = {"kind": "untracked" if record.startswith(b"? ") else "ignored", "raw": record.decode("utf-8", errors="replace")}
            continue
        if record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            if len(fields) != 9:
                raise G0Error("invalid_status_record")
            result[_decode_path(fields[8])] = {"kind": "tracked", "raw": record.decode("utf-8", errors="replace")}
            continue
        if record.startswith(b"2 "):
            fields = record.split(b" ", 9)
            if len(fields) != 10:
                raise G0Error("invalid_rename_status_record")
            result[_decode_path(fields[9].split(b"\t", 1)[0])] = {"kind": "tracked", "raw": record.decode("utf-8", errors="replace")}
            continue
        if record.startswith(b"u "):
            fields = record.split(b" ", 10)
            if len(fields) != 11:
                raise G0Error("invalid_unmerged_status_record")
            result[_decode_path(fields[10])] = {"kind": "tracked", "raw": record.decode("utf-8", errors="replace")}
            continue
        raise G0Error("unsupported_status_record")
    return result


def _hash_path(path: Path) -> str | None:
    return sha256_file(path) if path.is_file() and not path.is_symlink() else None


def _before_hash(root: Path, baseline: Path, entry: dict[str, Any] | None, relative: str, head: str) -> tuple[str | None, str]:
    if entry is not None:
        if entry.get("sha256"):
            return str(entry["sha256"]), f"manifest:{entry.get('source')}"
        if entry.get("source") == "tracked_deleted":
            try:
                blob = subprocess.check_output(["git", "-C", str(root), "show", f"{head}:{relative}"], stderr=subprocess.DEVNULL)
                return hashlib.sha256(blob).hexdigest(), "git_head_blob"
            except subprocess.CalledProcessError:
                return None, "tracked_deleted_unresolved"
    candidate = baseline / "full-repository" / Path(relative.replace("/", os.sep))
    if candidate.is_file() and not candidate.is_symlink():
        return sha256_file(candidate), "full_repository"
    return None, "absent_at_day0"


PRIOR_AUTOMATION_OWNERSHIP_PATH = Path("harness/baseline/prior-automation-ownership.json")


def _safe_ownership_relative(value: object) -> str | None:
    if not isinstance(value, str) or not value or chr(92) in value:
        return None
    candidate = Path(value)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return candidate.as_posix()


def _load_prior_automation_ownership(root: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Observe the legacy workspace ledger without treating it as a trust anchor.

    A mutable file under the candidate workspace cannot establish ownership of its
    own contents.  It remains visible for forensic comparison, but no entry is
    returned until a separate protected, independently signed Day-0 attestation
    is implemented and verified.
    """

    path = root / PRIOR_AUTOMATION_OWNERSHIP_PATH
    metadata: dict[str, Any] = {
        "path": PRIOR_AUTOMATION_OWNERSHIP_PATH.as_posix(),
        "sha256": _hash_path(path),
        "errors": [],
        "legacy_manifest_status": "absent",
        "observed_declared_paths": [],
        "external_validation": "not_applicable",
        "unblock_conditions": [],
    }
    if not path.exists():
        return {}, metadata

    metadata["external_validation"] = "pending"
    metadata["unblock_conditions"] = [
        "Provide a protected, independently signed Day-0 ownership attestation outside the mutable candidate workspace.",
        "Bind the attestation to the baseline manifest hash, root-contract SHA-256, file paths, file SHA-256 values, issuer identity, issuance time, and revocation state.",
        "Validate the attestation through a separately protected trust configuration with an issuer authorized for ownership provenance.",
    ]
    if not path.is_file() or path.is_symlink():
        metadata["legacy_manifest_status"] = "not_regular"
        metadata["errors"].append("prior_automation_ownership_external_attestation_required")
        return {}, metadata

    metadata["legacy_manifest_status"] = "observed_untrusted"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata["observed_schema"] = "unreadable"
    else:
        if isinstance(payload, dict):
            metadata["observed_schema"] = (
                "legacy_v1"
                if payload.get("schema_version") == "1.0" and payload.get("kind") == "g0_exact_prior_automation_ownership"
                else "unrecognized"
            )
            entries = payload.get("entries")
            if isinstance(entries, list):
                observed = []
                for entry in entries:
                    if isinstance(entry, dict):
                        relative = _safe_ownership_relative(entry.get("path"))
                        if relative is not None:
                            observed.append(relative)
                metadata["observed_declared_paths"] = sorted(set(observed))
        else:
            metadata["observed_schema"] = "unrecognized"

    metadata["errors"].append("prior_automation_ownership_external_attestation_required")
    return {}, metadata


def _aggregate_verdict(outcomes: list[str]) -> str:
    """Preserve blocking states instead of flattening them into an ambiguous FAIL."""

    if not outcomes:
        return "MISSING"
    values = {str(value) for value in outcomes}
    for status in ("ERROR", "INVALID", "BLOCKED", "STALE", "NEEDS_REVIEW", "MISSING", "WARN"):
        if status in values:
            return status
    return "PASS" if all(value == "PASS" for value in outcomes) else "FAIL"


def build_ownership(root: Path, baseline: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads((baseline / "manifest.json").read_text(encoding="utf-8"))
    entries = {str(item["path"]): item for item in manifest.get("entries", []) if isinstance(item, dict) and "path" in item}
    status = _status_items(root)
    ignored_raw = _git(root, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    ignored_paths = {_decode_path(path) for path in ignored_raw.split(b"\0") if path}
    status.update({path: {"kind": "ignored", "raw": "ignored"} for path in ignored_paths})
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    prior_automation_receipt = _load_prior_automation_ownership(root)[1]
    excluded = manifest.get("selection", {}).get("excludedIgnoredInventory", [])
    excluded_by_root = {str(item.get("topLevelPath")): item for item in excluded if isinstance(item, dict)}
    ledger: list[dict[str, Any]] = []
    unknown: list[str] = []
    unknown_ignored: list[str] = []
    for relative in sorted(status, key=str.casefold):
        item = status[relative]
        entry = entries.get(relative)
        top = relative.split("/", 1)[0]
        category = item["kind"]
        agent_generated_ignored = category == "ignored" and relative.startswith("harness/scripts/__pycache__/") and relative.endswith(".pyc")
        excluded_item = excluded_by_root.get(top) if category == "ignored" and entry is None else None
        reproducible_exclusion = excluded_item is not None and "reproducible" in str(excluded_item.get("disposition", ""))
        if reproducible_exclusion:
            before, before_source, after = None, "excluded_reproducible_inventory", None
        else:
            before, before_source = _before_hash(root, baseline, entry, relative, head)
            after = _hash_path(root / Path(relative.replace("/", os.sep)))
        if agent_generated_ignored:
            classification = "agent_ignored_reproducible"
            owner = "agent_g0"
            before, before_source = None, "absent_at_day0"
        elif category == "ignored" and entry is None:
            if reproducible_exclusion:
                classification = "ignored_excluded_reproducible"
                owner = "preexisting_generated_or_vendor"
            else:
                classification = "ignored_unaccounted"
                owner = "unattributed"
                unknown.append(relative)
                unknown_ignored.append(relative)
        elif entry is not None or before_source != "absent_at_day0":
            classification = f"preexisting_{category}"
            owner = "preexisting_user_or_previous"
        else:
            classification = f"post_baseline_{category}"
            owner = "unattributed"
            unknown.append(relative)
        ledger.append(
            {
                "path": relative,
                "kind": category,
                "owner": owner,
                "classification": classification,
                "before_sha256": before,
                "before_source": before_source,
                "after_sha256": after,
                "status_raw": item.get("raw"),
            }
        )
    ownership_verdict = (
        "BLOCKED"
        if "prior_automation_ownership_external_attestation_required" in prior_automation_receipt["errors"]
        else "PASS"
        if not unknown
        else "FAIL"
    )
    result = {
        "schema_version": "1.0",
        "kind": "g0_ownership_ledger",
        "baseline_manifest_sha256": sha256_file(baseline / "manifest.json"),
        "repository_head": head,
        "tracked_untracked_ignored_entries": len(ledger),
        "unattributed_paths": sorted(set(unknown)),
        "prior_automation_ownership": prior_automation_receipt,
        "external_validation": prior_automation_receipt["external_validation"],
        "release_qualification": "pending" if ownership_verdict == "BLOCKED" else "not_applicable",
        "verdict": ownership_verdict,
        "entries": ledger,
    }
    disposition = {
        "schema_version": "1.0",
        "kind": "g0_ignored_disposition",
        "ignored_total": len(ignored_paths),
        "selected_snapshot_entries": sum(1 for path in ignored_paths if entries.get(path, {}).get("source") in {"ignored_user_data", "ignored_verification_evidence"}),
        "excluded_reproducible_entries": sum(1 for item in ledger if item["classification"] == "ignored_excluded_reproducible"),
        "agent_reproducible_entries": sum(1 for item in ledger if item["classification"] == "agent_ignored_reproducible"),
        "unaccounted_entries": unknown_ignored,
        "write_protection_required": True,
        "verdict": "PASS" if not unknown_ignored else "FAIL",
    }
    return result, disposition


def readonly_probe(root: Path, baseline: Path, output_dir: Path) -> dict[str, Any]:
    probe_dir = Path(tempfile.mkdtemp(prefix=".g0-readonly-", dir=str(root.parent)))
    probe = probe_dir / "baseline-probe.txt"
    source = baseline / "full-repository" / "package.json"
    shutil.copyfile(source, probe)
    before = sha256_file(probe)
    attribute = _run(["attrib", "+R", str(probe)], cwd=root, timeout=30)
    acl = {"attempted": False, "returncode": None, "stdout": "", "stderr": ""}
    try:
        with probe.open("ab") as handle:
            handle.write(b"\nprobe")
        write_failed = False
        write_error = None
    except (OSError, PermissionError) as exc:
        write_failed = True
        write_error = f"{type(exc).__name__}: {exc}"
    after = sha256_file(probe)
    cleanup = _run(["attrib", "-R", str(probe)], cwd=root, timeout=30)
    shutil.rmtree(probe_dir, ignore_errors=True)
    return {
        "schema_version": "1.0",
        "kind": "g0_readonly_baseline_probe",
        "probe_source": str(source),
        "before_sha256": before,
        "after_sha256": after,
        "attribute_receipt": attribute,
        "write_failure": {
            "expected": True,
            "observed": write_failed,
            "error": write_error,
            "supervisor_pid": os.getpid(),
        },
        "cleanup_receipt": cleanup,
        "verdict": "PASS" if write_failed and before == after and cleanup["returncode"] == 0 else "FAIL",
    }


def journal_drill(output_dir: Path) -> dict[str, Any]:
    journal_path = output_dir / "journal-drill.events.jsonl"
    state_path = output_dir / "journal-drill.state.json"
    journal_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)
    import journal as journal_module

    original_writer = journal_module.atomic_write_json
    failure_observed = False

    def fail_state_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("injected_state_projection_failure")

    journal_module.atomic_write_json = fail_state_write
    try:
        append_event(journal_path, state_path, "phase_state", {"phase_id": "G0", "state": "in_progress"}, "g0:fault")
    except OSError as exc:
        failure_observed = str(exc) == "injected_state_projection_failure"
    finally:
        journal_module.atomic_write_json = original_writer
    events = read_events(journal_path)
    rebuilt = project(events)
    atomic_write_json(state_path, rebuilt)
    trunc = journal_path.with_name("journal-drill.truncated.jsonl")
    trunc.write_bytes(journal_path.read_bytes()[:-1])
    tampered = journal_path.with_name("journal-drill.tampered.jsonl")
    tampered.write_bytes(journal_path.read_bytes().replace(b'"state":"in_progress"', b'"state":"accepted"', 1))
    try:
        read_events(trunc)
        trunc_rejected = False
    except JournalError:
        trunc_rejected = True
    try:
        verify_events(read_events(tampered))
        tamper_rejected = False
    except JournalError:
        tamper_rejected = True
    verified = verify_events(events)
    return {
        "schema_version": "1.0",
        "kind": "g0_journal_fault_matrix",
        "failure_after_journal_write_observed": failure_observed,
        "reconciliation_projection_matches": json.loads(state_path.read_text(encoding="utf-8")) == rebuilt,
        "sequence_hash_verification": verified,
        "truncated_tail_rejected": trunc_rejected,
        "tampered_event_rejected": tamper_rejected,
        "verdict": "PASS" if failure_observed and trunc_rejected and tamper_rejected else "FAIL",
    }


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _lane_receipt_failure(required_lanes: tuple[str, ...], error: str) -> dict[str, Any]:
    results = {
        lane: {
            "declared_junit_sha256": None,
            "actual_junit_sha256": None,
            "errors": [error],
            "verdict": "FAIL",
        }
        for lane in required_lanes
    }
    return {
        "schema_version": "1.0",
        "kind": "g0_lane_receipt_validation",
        "numerator": 0,
        "denominator": len(required_lanes),
        "strata": list(required_lanes),
        "lanes": results,
        "verdict": "FAIL",
    }


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(_absolute_path(path))))


def _lexically_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([_path_key(path), _path_key(parent)]) == _path_key(parent)
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _has_reparse_component(path: Path, boundary: Path) -> bool:
    candidate = _absolute_path(path)
    stop = _absolute_path(boundary)
    while True:
        if _is_reparse_point(candidate):
            return True
        if _path_key(candidate) == _path_key(stop):
            return False
        parent = candidate.parent
        if parent == candidate:
            return True
        candidate = parent


def _evidence_dir_error(evidence_dir: Path, workspace_root: Path) -> str | None:
    evidence_raw = _absolute_path(evidence_dir)
    workspace_raw = _absolute_path(workspace_root)
    if not _lexically_within(evidence_raw, workspace_raw):
        return "evidence_dir_outside_workspace"
    if not evidence_raw.exists():
        return "evidence_dir_missing"
    if not evidence_raw.is_dir():
        return "evidence_dir_not_directory"
    if _has_reparse_component(evidence_raw, workspace_raw):
        return "evidence_dir_reparse_point_not_allowed"
    try:
        evidence_resolved = evidence_raw.resolve(strict=True)
        workspace_resolved = workspace_raw.resolve(strict=True)
    except OSError:
        return "evidence_dir_unresolvable"
    if not _lexically_within(evidence_resolved, workspace_resolved):
        return "evidence_dir_resolves_outside_workspace"
    return None



class _EvidenceDirectoryGuard:
    """Bind lane writes to the same checked evidence directory identity."""

    def __init__(self, evidence_dir: Path, workspace_root: Path) -> None:
        evidence_error = _evidence_dir_error(evidence_dir, workspace_root)
        if evidence_error is not None:
            raise G0Error(evidence_error)
        self.raw = _absolute_path(evidence_dir)
        self.workspace = _absolute_path(workspace_root)
        self.resolved = self.raw.resolve(strict=True)
        self.identity = self._identity(self.raw)

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int]:
        metadata = path.lstat()
        return (
            int(getattr(metadata, "st_dev", 0)),
            int(getattr(metadata, "st_ino", 0)),
            int(getattr(metadata, "st_mode", 0)),
            int(getattr(metadata, "st_file_attributes", 0)),
        )

    def assert_unchanged(self) -> None:
        evidence_error = _evidence_dir_error(self.raw, self.workspace)
        if evidence_error is not None:
            raise G0Error(evidence_error)
        try:
            current_resolved = self.raw.resolve(strict=True)
            current_identity = self._identity(self.raw)
        except OSError as exc:
            raise G0Error("evidence_dir_unresolvable") from exc
        if _path_key(current_resolved) != _path_key(self.resolved) or current_identity != self.identity:
            raise G0Error("evidence_dir_identity_changed")


def _assert_safe_evidence_target(path: Path, guard: _EvidenceDirectoryGuard) -> None:
    guard.assert_unchanged()
    target = _absolute_path(path)
    if not _lexically_within(target, guard.raw):
        raise G0Error("evidence_target_outside_evidence")
    if _path_key(target.parent) != _path_key(guard.raw):
        raise G0Error("evidence_target_parent_not_canonical")
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise G0Error("evidence_target_unreadable") from exc
    if _is_reparse_point(target):
        raise G0Error("evidence_target_reparse_point_not_allowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise G0Error("evidence_target_not_regular")
    if metadata.st_nlink != 1:
        raise G0Error("evidence_target_hardlink_not_allowed")



def _assert_external_staging_dir(staging: Path, guard: _EvidenceDirectoryGuard) -> None:
    raw = _absolute_path(staging)
    try:
        metadata = raw.lstat()
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise G0Error("lane_staging_unresolvable") from exc
    if _is_reparse_point(raw):
        raise G0Error("lane_staging_reparse_point_not_allowed")
    if not stat.S_ISDIR(metadata.st_mode):
        raise G0Error("lane_staging_not_directory")
    if _lexically_within(raw, guard.workspace) or _lexically_within(resolved, guard.workspace.resolve()):
        raise G0Error("lane_staging_inside_workspace_not_allowed")


class _StagingDirectoryGuard:
    """Bind staged lane sources to one checked external temporary directory."""

    def __init__(self, staging: Path, evidence_guard: _EvidenceDirectoryGuard) -> None:
        self.evidence_guard = evidence_guard
        self.raw = _absolute_path(staging)
        _assert_external_staging_dir(self.raw, self.evidence_guard)
        self.resolved = self.raw.resolve(strict=True)
        self.identity = _EvidenceDirectoryGuard._identity(self.raw)

    def assert_unchanged(self) -> None:
        self.evidence_guard.assert_unchanged()
        _assert_external_staging_dir(self.raw, self.evidence_guard)
        try:
            current_resolved = self.raw.resolve(strict=True)
            current_identity = _EvidenceDirectoryGuard._identity(self.raw)
        except OSError as exc:
            raise G0Error("lane_staging_unresolvable") from exc
        if _path_key(current_resolved) != _path_key(self.resolved) or current_identity != self.identity:
            raise G0Error("lane_staging_identity_changed")



def _assert_safe_staged_source(path: Path, staging_guard: _StagingDirectoryGuard) -> bool:
    """Return False only for a missing staged leaf; reject every aliased source."""
    staging_guard.assert_unchanged()
    source = _absolute_path(path)
    if not _lexically_within(source, staging_guard.raw):
        raise G0Error("lane_staged_source_outside_staging")
    if _path_key(source.parent) != _path_key(staging_guard.raw):
        raise G0Error("lane_staged_source_parent_not_canonical")
    try:
        metadata = source.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise G0Error("lane_staged_source_unreadable") from exc
    if _is_reparse_point(source):
        raise G0Error("lane_staged_source_reparse_point_not_allowed")
    if not stat.S_ISREG(metadata.st_mode):
        raise G0Error("lane_staged_source_not_regular")
    if metadata.st_nlink != 1:
        raise G0Error("lane_staged_source_hardlink_not_allowed")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise G0Error("lane_staged_source_unresolvable") from exc
    if not _lexically_within(resolved, staging_guard.resolved) or _path_key(resolved.parent) != _path_key(staging_guard.resolved):
        raise G0Error("lane_staged_source_resolves_outside_staging")
    staging_guard.assert_unchanged()
    return True



def _cleanup_owned_evidence_temp(path: Path, identity: tuple[int, int, int, int]) -> None:
    """Remove only the unchanged exclusive temporary leaf created by this commit."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise G0Error("evidence_temp_cleanup_unreadable") from exc
    if (
        _EvidenceDirectoryGuard._identity(path) != identity
        or _is_reparse_point(path)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
    ):
        raise G0Error("evidence_temp_cleanup_identity_changed")
    try:
        path.unlink()
    except OSError as exc:
        raise G0Error("evidence_temp_cleanup_failed") from exc



def _commit_staged_evidence_file(
    source: Path,
    destination: Path,
    guard: _EvidenceDirectoryGuard,
    staging_guard: _StagingDirectoryGuard,
) -> bool:
    """Copy through a bound evidence temp leaf, then atomically replace destination."""
    if not _assert_safe_staged_source(source, staging_guard):
        return False
    _assert_safe_evidence_target(destination, guard)
    temporary: Path | None = None
    temporary_identity: tuple[int, int, int, int] | None = None
    descriptor: int | None = None
    try:
        try:
            descriptor, temporary_raw = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=str(guard.raw),
            )
        except OSError as exc:
            raise G0Error("evidence_temp_create_failed") from exc
        temporary = Path(temporary_raw)
        _assert_safe_evidence_target(temporary, guard)
        temporary_identity = _EvidenceDirectoryGuard._identity(temporary)
        try:
            with os.fdopen(descriptor, "wb") as output:
                descriptor = None
                with source.open("rb") as staged_input:
                    shutil.copyfileobj(staged_input, output)
                output.flush()
                os.fsync(output.fileno())
        except OSError as exc:
            raise G0Error("evidence_temp_write_failed") from exc
        _assert_safe_staged_source(source, staging_guard)
        _assert_safe_evidence_target(temporary, guard)
        if _EvidenceDirectoryGuard._identity(temporary) != temporary_identity:
            raise G0Error("evidence_temp_identity_changed")
        guard.assert_unchanged()
        try:
            os.replace(temporary, destination)
        except OSError as exc:
            raise G0Error("evidence_target_replace_failed") from exc
        temporary = None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if temporary is not None and temporary_identity is not None:
            _cleanup_owned_evidence_temp(temporary, temporary_identity)
    _assert_safe_evidence_target(destination, guard)
    _assert_safe_staged_source(source, staging_guard)
    return True

def validate_lane_receipts(
    lane_summary: dict[str, Any],
    *,
    evidence_dir: Path,
    workspace_root: Path,
    required_lanes: tuple[str, ...] = ("unit", "contract", "integration", "desktop", "release"),
) -> dict[str, Any]:
    """Fail closed unless each lane binds one unaliased canonical raw JUnit within workspace evidence."""

    evidence_error = _evidence_dir_error(evidence_dir, workspace_root)
    if evidence_error is not None:
        return _lane_receipt_failure(required_lanes, evidence_error)
    evidence_raw = _absolute_path(evidence_dir)
    evidence_resolved = evidence_raw.resolve(strict=True)
    lanes = lane_summary.get("lanes")
    if not isinstance(lanes, dict):
        result = _lane_receipt_failure(required_lanes, "lanes_not_object")
        result["errors"] = ["lanes_not_object"]
        return result
    results: dict[str, dict[str, Any]] = {}
    for lane in required_lanes:
        item = lanes.get(lane)
        errors: list[str] = []
        if not isinstance(item, dict):
            results[lane] = {"verdict": "FAIL", "errors": ["lane_missing"]}
            continue
        raw_path = item.get("junit")
        declared = item.get("junit_sha256")
        junit: Path | None = None
        if not isinstance(raw_path, str) or not raw_path:
            errors.append("junit_path_missing")
        else:
            junit = _absolute_path(Path(raw_path))
            expected = _absolute_path(evidence_raw / f"lane-{lane}.xml")
            if not _lexically_within(junit, evidence_raw):
                errors.append("junit_path_outside_evidence")
            elif _path_key(junit) != _path_key(expected):
                errors.append("junit_path_not_canonical_for_lane")
            else:
                try:
                    resolved = junit.resolve(strict=True)
                    expected_resolved = expected.resolve(strict=True)
                except OSError:
                    pass
                else:
                    if not _lexically_within(resolved, evidence_resolved):
                        errors.append("junit_path_outside_evidence")
                    elif _path_key(resolved) != _path_key(expected_resolved):
                        errors.append("junit_path_not_canonical_for_lane")
        if item.get("junit_exists") is not True:
            errors.append("junit_not_declared_existing")
        if not _valid_sha256(declared):
            errors.append("junit_sha256_missing_or_invalid")
        actual = None
        if junit is not None and not errors:
            if not junit.is_file():
                errors.append("junit_file_missing")
            elif _is_reparse_point(junit):
                errors.append("junit_reparse_point_not_allowed")
            elif junit.lstat().st_nlink != 1:
                errors.append("junit_hardlink_not_allowed")
            else:
                actual = sha256_file(junit)
                if actual != declared:
                    errors.append("junit_sha256_mismatch")
        results[lane] = {
            "declared_junit_sha256": declared,
            "actual_junit_sha256": actual,
            "errors": errors,
            "verdict": "PASS" if not errors else "FAIL",
        }
    numerator = sum(item["verdict"] == "PASS" for item in results.values())
    denominator = len(required_lanes)
    return {
        "schema_version": "1.0",
        "kind": "g0_lane_receipt_validation",
        "numerator": numerator,
        "denominator": denominator,
        "strata": list(required_lanes),
        "lanes": results,
        "verdict": "PASS" if numerator == denominator and denominator > 0 else "FAIL",
    }


def _preflight_lane_evidence_dir(evidence_dir: Path, workspace_root: Path) -> None:
    evidence_error = _evidence_dir_error(evidence_dir, workspace_root)
    if evidence_error is not None:
        raise G0Error(evidence_error)


async def run_lanes(root: Path, runtime: Path, evidence_dir: Path, lanes: list[str]) -> dict[str, Any]:
    guard = _EvidenceDirectoryGuard(evidence_dir, root)
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="vibe-g0-lane-staging-") as staging_raw:
        staging = Path(staging_raw)
        staging_guard = _StagingDirectoryGuard(staging, guard)
        supervisor = ProcessSupervisor(root, {runtime.name, "python", "python.exe"})
        guard.assert_unchanged()
        staging_guard.assert_unchanged()
        for lane in lanes:
            guard.assert_unchanged()
            staging_guard.assert_unchanged()
            junit = evidence_dir / f"lane-{lane}.xml"
            stdout_path = evidence_dir / f"lane-{lane}.stdout.txt"
            stderr_path = evidence_dir / f"lane-{lane}.stderr.txt"
            staged_junit = staging / f"lane-{lane}.xml"
            staged_stdout = staging / f"lane-{lane}.stdout.txt"
            staged_stderr = staging / f"lane-{lane}.stderr.txt"
            command = [str(runtime), "-m", "pytest", "-m", lane, "--junitxml", str(staged_junit)]
            receipt = await supervisor.run(f"g0-lane-{lane}", command, root, timeout=3600)
            staged_junit_exists = _assert_safe_staged_source(staged_junit, staging_guard)
            staged_stdout.write_text(receipt.get("stdout", ""), encoding="utf-8")
            staged_stderr.write_text(receipt.get("stderr", ""), encoding="utf-8")
            if not _assert_safe_staged_source(staged_stdout, staging_guard) or not _assert_safe_staged_source(staged_stderr, staging_guard):
                raise G0Error("lane_staged_output_missing")
            junit_metrics = parse_junit(staged_junit) if staged_junit_exists else {
                "tests": 0,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
                "time": 0.0,
            }
            passed = (
                receipt.get("returncode") == 0
                and "timed out" not in receipt.get("stderr", "").lower()
                and staged_junit_exists
                and junit_metrics["tests"] > 0
                and junit_metrics["failures"] == 0
                and junit_metrics["errors"] == 0
                and junit_metrics["skipped"] == 0
            )
            guard.assert_unchanged()
            staging_guard.assert_unchanged()
            committed_junit = _commit_staged_evidence_file(staged_junit, junit, guard, staging_guard)
            committed_stdout = _commit_staged_evidence_file(staged_stdout, stdout_path, guard, staging_guard)
            committed_stderr = _commit_staged_evidence_file(staged_stderr, stderr_path, guard, staging_guard)
            if not committed_stdout or not committed_stderr:
                raise G0Error("lane_output_commit_missing")
            results[lane] = {
                "command": command,
                "returncode": receipt.get("returncode"),
                "timed_out": "timed out" in receipt.get("stderr", "").lower(),
                "junit": str(junit),
                "junit_exists": committed_junit and junit.is_file(),
                "junit_sha256": sha256_file(junit) if committed_junit and junit.is_file() else None,
                "junit_metrics": junit_metrics,
                "stdout_sha256": sha256_file(stdout_path),
                "stderr_sha256": sha256_file(stderr_path),
                "supervisor_owned_processes_after": len(supervisor._processes),
                "verdict": "PASS" if passed else "FAIL",
            }
    summary = {"lanes": results}
    summary["receipt_validation"] = validate_lane_receipts(
        summary,
        evidence_dir=evidence_dir,
        workspace_root=root,
        required_lanes=tuple(lanes),
    )
    summary["verdict"] = "PASS" if all(item["verdict"] == "PASS" for item in results.values()) and summary["receipt_validation"]["verdict"] == "PASS" else "FAIL"
    return summary

def parse_junit(path: Path) -> dict[str, int | float]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        "tests": sum(int(suite.attrib.get("tests", 0)) for suite in suites),
        "failures": sum(int(suite.attrib.get("failures", 0)) for suite in suites),
        "errors": sum(int(suite.attrib.get("errors", 0)) for suite in suites),
        "skipped": sum(int(suite.attrib.get("skipped", 0)) for suite in suites),
        "time": sum(float(suite.attrib.get("time", 0.0)) for suite in suites),
    }


def build_artifact_manifest(paths: list[Path]) -> list[dict[str, Any]]:
    artifacts = []
    for path in paths:
        if path.is_file():
            artifacts.append({"path": str(path.resolve()), "sha256": sha256_file(path), "size": path.stat().st_size})
    return artifacts


def _unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path.resolve()))
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _capture_gate_root_receipt(contract_path: Path, root: Path, gate_id: str) -> dict[str, Any]:
    escaped_contract_path = str(contract_path).replace("'", "''")
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        (
            "$h=Get-FileHash -Algorithm SHA256 -LiteralPath "
            f"'{escaped_contract_path}';"
            "$h|Select-Object Algorithm,Hash,Path|ConvertTo-Json -Compress"
        ),
    ]
    command_receipt = _run(command, cwd=root, timeout=30)
    try:
        actual = json.loads(command_receipt["stdout"])["Hash"].lower()
    except (json.JSONDecodeError, KeyError, TypeError):
        actual = ""
    return {
        "schema_version": "1.0",
        "kind": "gate_root_contract_os_hash",
        "gate_id": gate_id,
        "expected_sha256": EXPECTED_FILE_SHA256,
        "actual_sha256": actual,
        "command_receipt": command_receipt,
        "verdict": "PASS" if command_receipt["returncode"] == 0 and not command_receipt["timed_out"] and actual == EXPECTED_FILE_SHA256 else "FAIL",
    }


def _prepare_g0_gate_receipts(
    *,
    root: Path,
    contract_path: Path,
    lock: dict[str, Any],
    checks: dict[str, Any],
    artifact_sources: dict[str, list[Path]],
    evidence: Path,
) -> tuple[list[dict[str, Any]], list[Path]]:
    g0_requirements = {
        item["requirement_id"]
        for item in lock["mappings"]
        if item["requirement_id"].startswith("REQ-G0")
    }
    if set(G0_GATE_SPECS) != g0_requirements:
        raise G0Error("g0_gate_spec_coverage_mismatch")
    gate_by_requirement = {
        gate["requirement_ids"][0]: gate
        for gate in lock["gates"]
        if gate.get("requirement_ids") and gate["requirement_ids"][0] in g0_requirements
    }
    checker = root / "harness" / "scripts" / "verify_truth.py"
    generator = Path(__file__).resolve()
    prepared: list[dict[str, Any]] = []
    receipt_paths: list[Path] = []
    for requirement_id, spec in G0_GATE_SPECS.items():
        gate = gate_by_requirement[requirement_id]
        gate_id = gate["id"]
        safe_id = gate_id.replace("/", "_")
        root_receipt_path = evidence / "gate-root-receipts" / f"{safe_id}.json"
        root_receipt = _capture_gate_root_receipt(contract_path, root, gate_id)
        atomic_write_json(root_receipt_path, root_receipt)
        selected = {name: checks[name].get("verdict", "MISSING") for name in spec["checks"]}
        strata = ["root_contract_os_hash", *spec["checks"]]
        outcomes = [root_receipt["verdict"], *selected.values()]
        verdict = _aggregate_verdict(outcomes)
        selected_paths = _unique_paths(
            [path for name in spec["artifacts"] for path in artifact_sources[name]]
            + [root_receipt_path, checker, generator]
        )
        derivation_path = evidence / "gate-runner-receipts" / f"{safe_id}.json"
        derivation = {
            "schema_version": "1.0",
            "kind": "g0_gate_candidate_derivation",
            "gate_id": gate_id,
            "requirement_id": requirement_id,
            "requirement_sha256": gate["requirement_sha256"],
            "root_receipt": str(root_receipt_path.resolve()),
            "selected_checks": selected,
            "metrics": {
                "numerator": sum(value == "PASS" for value in outcomes),
                "denominator": len(outcomes),
                "strata": strata,
                "abstentions": 0,
            },
            "generator": {"path": str(generator), "sha256": sha256_file(generator)},
            "checker": {"path": str(checker), "sha256": sha256_file(checker)},
            "inputs": build_artifact_manifest(selected_paths),
            "verdict": verdict,
        }
        atomic_write_json(derivation_path, derivation)
        receipt_paths.extend([root_receipt_path, derivation_path])
        prepared.append(
            {
                "gate": gate,
                "requirement_id": requirement_id,
                "verdict": verdict,
                "metrics": derivation["metrics"],
                "checks": selected,
                "selected_paths": selected_paths,
                "root_receipt_path": root_receipt_path,
                "derivation_path": derivation_path,
            }
        )
    return prepared, receipt_paths


def _relative_to_root(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _manifest_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _write_g0_gate_reports(prepared: list[dict[str, Any]], artifact_manifest: Path, evidence: Path, root: Path) -> list[Path]:
    report_paths: list[Path] = []
    for item in prepared:
        gate = item["gate"]
        input_artifacts = build_artifact_manifest(_unique_paths(item["selected_paths"]))
        output_manifest = {"checks": item["checks"], "metrics": item["metrics"], "verdict": item["verdict"]}
        report = {
            "schema_version": "1.0",
            "gate_id": gate["id"],
            "requirement_ids": [item["requirement_id"]],
            "requirement_sha256": gate["requirement_sha256"],
            "runner_sha256": gate["runner"]["sha256"],
            "phase": "G0",
            "verdict": item["verdict"],
            "required": True,
            "metrics": item["metrics"],
            "runner_receipt": _relative_to_root(root, item["derivation_path"]),
            "root_contract_receipt": _relative_to_root(root, item["root_receipt_path"]),
            "root_contract_sha256": EXPECTED_FILE_SHA256,
            "input_artifacts": input_artifacts,
            "input_manifest_sha256": _manifest_sha256(input_artifacts),
            "output_manifest": output_manifest,
            "output_manifest_sha256": _manifest_sha256(output_manifest),
            "checks": item["checks"],
            "artifacts": build_artifact_manifest(_unique_paths(item["selected_paths"] + [item["derivation_path"], artifact_manifest])),
            "external_validation": "pending",
            "release_qualification": "pending",
        }
        validation = validate_gate_report(report)
        if validation.get("verdict") != report["verdict"]:
            raise G0Error(f"g0_report_schema:{gate['id']}:{validation}")
        report_path = evidence / "gate-reports" / f"{gate['id']}.json"
        atomic_write_json(report_path, report)
        report_paths.append(report_path)
        if gate["id"] == "GATE-REQ-G0-EXIT-001":
            atomic_write_json(evidence / "g0-gate-report.json", report)
    return report_paths

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline", type=Path, default=Path(r"D:\科研软件制作\Vibe-research源码-Day0Baseline"))
    parser.add_argument("--contract", type=Path, default=Path(r"D:\科研软件制作\开发指导.bootstrap.json"))
    parser.add_argument("--lock", type=Path, default=ROOT / "harness" / "phase-contract.lock")
    parser.add_argument("--runtime", type=Path, default=ROOT / "runtime" / "python" / "python.exe")
    parser.add_argument("--skip-lanes", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    baseline = args.baseline.resolve()
    evidence = root / "harness" / "evidence" / "G0"
    evidence.mkdir(parents=True, exist_ok=True)
    artifacts: list[Path] = []
    checks: dict[str, Any] = {}

    contract_hash = sha256_file(args.contract)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    escaped_contract_path = str(args.contract).replace("'", "''")
    os_hash_command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        (
            "$h=Get-FileHash -Algorithm SHA256 -LiteralPath "
            f"'{escaped_contract_path}';"
            "$h|Select-Object Algorithm,Hash,Path|ConvertTo-Json -Compress"
        ),
    ]
    os_hash_receipt = _run(os_hash_command, cwd=root, timeout=30)
    try:
        os_hash_value = json.loads(os_hash_receipt["stdout"])["Hash"].lower()
    except (json.JSONDecodeError, KeyError, TypeError):
        os_hash_value = ""
    contract_result = validate_contract(contract, file_hash=contract_hash)
    lock_result = validate_lock(json.loads(args.lock.read_text(encoding="utf-8")), contract)
    tamper_result = run_tamper_vectors(contract, json.loads(args.lock.read_text(encoding="utf-8")))
    checks["root_contract"] = {
        "verdict": "PASS" if contract_result.get("verdict") == lock_result.get("verdict") == tamper_result.get("verdict") == "PASS" and os_hash_receipt["returncode"] == 0 and os_hash_value == contract_hash == EXPECTED_FILE_SHA256 else "FAIL",
        "contract": contract_result,
        "os_hash_receipt": os_hash_receipt,
        "sha256_expected": EXPECTED_FILE_SHA256,
        "sha256_actual": contract_hash,
        "merkle_root": EXPECTED_MERKLE_ROOT,
        "requirements": EXPECTED_REQUIREMENTS,
        "tamper_vectors": EXPECTED_TAMPER_VECTORS,
        "lock": lock_result,
        "tamper": tamper_result,
    }
    root_receipt = evidence / "root-contract-g0.json"
    atomic_write_json(root_receipt, checks["root_contract"])
    artifacts.append(root_receipt)

    ownership, ignored = build_ownership(root, baseline)
    ownership_path = evidence / "ownership-ledger.json"
    ignored_path = evidence / "ignored-disposition.json"
    atomic_write_json(ownership_path, ownership)
    atomic_write_json(ignored_path, ignored)
    artifacts.extend([ownership_path, ignored_path])
    checks["ownership"] = ownership
    checks["ignored"] = ignored

    readonly = readonly_probe(root, baseline, evidence)
    readonly_path = evidence / "readonly-probe.json"
    atomic_write_json(readonly_path, readonly)
    artifacts.append(readonly_path)
    checks["readonly"] = readonly

    secret = scan(root)
    secret_path = evidence / "secret-scan-g0.json"
    atomic_write_json(secret_path, secret)
    artifacts.append(secret_path)
    checks["secret_scan"] = secret

    journal = journal_drill(evidence)
    journal_path = evidence / "journal-fault-matrix.json"
    atomic_write_json(journal_path, journal)
    artifacts.append(journal_path)
    checks["journal"] = journal

    restore = run_ephemeral_drill(baseline)
    restore_path = evidence / "restore-drill-trusted.json"
    atomic_write_json(restore_path, restore)
    artifacts.append(restore_path)
    checks["restore"] = restore

    if args.skip_lanes:
        lanes = {"verdict": "BLOCKED", "reason": "lanes_skipped"}
    else:
        lanes = asyncio.run(run_lanes(root, args.runtime.resolve(), evidence, ["unit", "contract", "integration", "desktop", "release"]))
    lanes_path = evidence / "lane-summary.json"
    atomic_write_json(lanes_path, lanes)
    artifacts.append(lanes_path)
    checks["lanes"] = lanes

    checks["orphan_processes"] = {
        "owned_processes_after": 0,
        "verdict": "PASS" if lanes.get("lanes") and all(item.get("supervisor_owned_processes_after") == 0 for item in lanes.get("lanes", {}).values()) else "FAIL",
    }
    required_lane_names = {"unit", "contract", "integration", "live_provider", "desktop", "release", "private_eval"}
    pytest_config_text = (root / "pytest.ini").read_text(encoding="utf-8")
    conftest_text = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    checks["lane_contract"] = {
        "required_lanes": sorted(required_lane_names),
        "pytest_ini_coverage": sorted(name for name in required_lane_names if f"{name}:" in pytest_config_text),
        "conftest_coverage": sorted(name for name in required_lane_names if f'"{name}"' in conftest_text),
        "verdict": "PASS"
        if all(f"{name}:" in pytest_config_text and f'"{name}"' in conftest_text for name in required_lane_names)
        else "FAIL",
    }
    checks_path = evidence / "g0-checks.json"
    atomic_write_json(checks_path, checks)
    artifacts.append(checks_path)

    required = ["root_contract", "ownership", "ignored", "readonly", "secret_scan", "journal", "restore", "lane_contract", "lanes", "orphan_processes"]
    verdict = _aggregate_verdict([str(checks[name].get("verdict", "MISSING")) for name in required])
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    lane_paths = [lanes_path]
    for lane in ("unit", "contract", "integration", "desktop", "release"):
        lane_paths.extend(
            [
                evidence / f"lane-{lane}.xml",
                evidence / f"lane-{lane}.stdout.txt",
                evidence / f"lane-{lane}.stderr.txt",
            ]
        )
    artifact_sources = {
        "baseline_manifest": [baseline / "manifest.json", baseline / "verification.json"],
        "ownership": [ownership_path],
        "ignored": [ignored_path],
        "readonly": [readonly_path],
        "secret_scan": [secret_path],
        "journal": [journal_path],
        "restore": [restore_path],
        "root_contract": [root_receipt],
        "phase_lock": [args.lock],
        "bootstrap_contract": [args.contract],
        "pytest_config": [root / "pytest.ini"],
        "pytest_conftest": [root / "tests" / "conftest.py"],
        "lanes": lane_paths,
        "lane_unit": [evidence / "lane-unit.xml"],
        "process_supervisor": [root / "backend" / "services" / "process_supervisor.py"],
    }
    prepared, gate_receipts = _prepare_g0_gate_receipts(
        root=root,
        contract_path=args.contract,
        lock=lock,
        checks=checks,
        artifact_sources=artifact_sources,
        evidence=evidence,
    )
    artifacts.extend(path for paths in artifact_sources.values() for path in paths)
    artifacts.extend(gate_receipts)
    artifact_manifest = evidence / "artifact-manifest.json"
    atomic_write_json(
        artifact_manifest,
        {
            "schema_version": "1.0",
            "phase": "G0",
            "artifacts": build_artifact_manifest(_unique_paths(artifacts)),
            "verdict": verdict,
        },
    )
    checks["artifact_manifest"] = str(artifact_manifest)
    report_paths = _write_g0_gate_reports(prepared, artifact_manifest, evidence, root)
    print(
        json.dumps(
            {
                "verdict": verdict,
                "checks": {name: checks[name].get("verdict") for name in required},
                "reports": [str(path) for path in report_paths],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
