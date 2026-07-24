from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json, sha256_file


class RestoreError(RuntimeError):
    pass


GIT_METADATA_PATHS = {
    "@git/branch": "git-metadata/branch.txt",
    "@git/HEAD": "git-metadata/HEAD",
    "@git/head-commit": "git-metadata/head-commit.txt",
    "@git/index": "git-metadata/index",
    "@git/refs-before": "git-metadata/refs-before.txt",
    "@git/repository.bundle": "git-metadata/repository.bundle",
    "@git/status-before": "git-metadata/status-before.txt",
}


def _safe_relative(value: object, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise RestoreError(f"invalid_{label}")
    candidate = Path(value.replace("/", os.sep))
    if candidate.is_absolute() or ".." in candidate.parts or candidate.name in {"", "."}:
        raise RestoreError(f"unsafe_{label}")
    return candidate


def _snapshot_path(baseline: Path, value: object) -> Path:
    relative = _safe_relative(value, label="snapshot_path")
    path = baseline / relative
    try:
        path.resolve(strict=True).relative_to(baseline.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise RestoreError("snapshot_path_outside_baseline") from exc
    if not path.is_file() or path.is_symlink():
        raise RestoreError("invalid_snapshot_file")
    return path


def _full_repository_path(baseline: Path, relative: str) -> Path:
    root = baseline / "full-repository"
    if not root.is_dir() or root.is_symlink():
        raise RestoreError("missing_full_repository_snapshot")
    path = root / _safe_relative(relative, label="full_repository_path")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise RestoreError("full_repository_path_outside_baseline") from exc
    if not path.is_file() or path.is_symlink():
        raise RestoreError("invalid_full_repository_file")
    return path


def _read_manifest(baseline: Path) -> tuple[dict[str, Any], str]:
    path = baseline / "manifest.json"
    if not path.is_file():
        raise RestoreError("missing_manifest")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RestoreError("invalid_manifest_json") from exc
    if manifest.get("kind") != "vibe-research-day0-baseline" or not isinstance(manifest.get("entries"), list):
        raise RestoreError("invalid_manifest_schema")
    return manifest, sha256_file(path)


def validate_baseline(baseline: Path) -> dict[str, Any]:
    baseline = baseline.resolve(strict=True)
    manifest, manifest_hash = _read_manifest(baseline)
    seen_paths: set[str] = set()
    metadata: dict[str, Path] = {}
    worktree_entries: list[dict[str, Any]] = []
    deleted_entries: list[dict[str, Any]] = []
    checked_files = 0
    checked_bytes = 0

    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            raise RestoreError("invalid_manifest_entry")
        path_name = entry.get("path")
        if not isinstance(path_name, str) or not path_name or path_name in seen_paths:
            raise RestoreError("invalid_or_duplicate_manifest_path")
        seen_paths.add(path_name)
        source = entry.get("source")
        snapshot_name = entry.get("snapshotPath")
        if source == "tracked_deleted":
            _safe_relative(path_name, label="worktree_path")
            if snapshot_name is not None or entry.get("size") is not None or entry.get("sha256") is not None:
                raise RestoreError("invalid_deletion_marker")
            deleted_entries.append(entry)
            continue
        if not isinstance(snapshot_name, str) or not isinstance(entry.get("size"), int) or not isinstance(entry.get("sha256"), str):
            raise RestoreError("invalid_file_entry")
        snapshot = _snapshot_path(baseline, snapshot_name)
        if snapshot.stat().st_size != entry["size"] or sha256_file(snapshot) != entry["sha256"]:
            raise RestoreError("snapshot_content_mismatch")
        checked_files += 1
        checked_bytes += int(entry["size"])
        if path_name.startswith("@git/"):
            expected_snapshot = GIT_METADATA_PATHS.get(path_name)
            if expected_snapshot != snapshot_name:
                raise RestoreError("invalid_git_metadata_path")
            metadata[path_name] = snapshot
        elif snapshot_name.startswith("worktree/"):
            _safe_relative(path_name, label="worktree_path")
            worktree_entries.append(entry)
        else:
            raise RestoreError("unsupported_snapshot_entry")

    if set(metadata) != set(GIT_METADATA_PATHS):
        raise RestoreError("missing_git_metadata")
    return {
        "baseline": baseline,
        "manifest": manifest,
        "manifest_sha256": manifest_hash,
        "metadata": metadata,
        "worktree_entries": worktree_entries,
        "deleted_entries": deleted_entries,
        "checked_files": checked_files,
        "checked_bytes": checked_bytes,
    }


def _run_git(root: Path, *args: str, optional_locks: bool = True) -> bytes:
    env = os.environ.copy()
    if not optional_locks:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if result.returncode:
        raise RestoreError(f"git_{args[0]}_failed")
    return result.stdout


def _run_git_with_input(root: Path, args: tuple[str, ...], stdin: bytes) -> bytes:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if result.returncode:
        raise RestoreError(f"git_{args[0]}_failed")
    return result.stdout


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _parse_refs(raw: bytes) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    for line in raw.splitlines():
        try:
            ref, object_id = line.decode("ascii").split(" ", 1)
        except ValueError as exc:
            raise RestoreError("invalid_refs_metadata") from exc
        if not ref.startswith("refs/") or len(object_id) not in {40, 64}:
            raise RestoreError("invalid_refs_metadata")
        refs.append((ref, object_id))
    if len({ref for ref, _ in refs}) != len(refs):
        raise RestoreError("duplicate_ref_metadata")
    return refs


def _restore_refs(target: Path, expected: list[tuple[str, str]]) -> None:
    current = _run_git(target, "for-each-ref", "--format=%(refname)").decode("ascii").splitlines()
    for ref in current:
        symbolic = subprocess.run(
            ["git", "-C", str(target), "symbolic-ref", "-q", ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if symbolic.returncode == 0:
            _run_git(target, "symbolic-ref", "-d", ref)
        else:
            _run_git(target, "update-ref", "-d", ref)
    for ref, object_id in expected:
        _run_git(target, "cat-file", "-e", f"{object_id}^{{commit}}")
        _run_git(target, "update-ref", ref, object_id)


def _configure_branch(target: Path, head_raw: bytes, status_raw: bytes, refs: list[tuple[str, str]]) -> None:
    if not head_raw.startswith(b"ref: refs/heads/") or not head_raw.endswith(b"\n"):
        raise RestoreError("unsupported_head")
    branch = head_raw[len(b"ref: refs/heads/") : -1].decode("utf-8")
    _run_git(target, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    _run_git(target, "config", "--unset-all", f"branch.{branch}.remote") if _has_config(target, f"branch.{branch}.remote") else None
    _run_git(target, "config", "--unset-all", f"branch.{branch}.merge") if _has_config(target, f"branch.{branch}.merge") else None

    upstream = next((line[len(b"# branch.upstream ") :].decode("utf-8") for line in status_raw.splitlines() if line.startswith(b"# branch.upstream ")), None)
    if upstream is None:
        return
    matching = [ref for ref, _ in refs if ref.startswith("refs/remotes/") and ref[len("refs/remotes/") :].replace("/", "/", 1) == upstream]
    if len(matching) != 1:
        raise RestoreError("upstream_ref_not_restorable")
    remote_and_branch = matching[0][len("refs/remotes/") :]
    remote, remote_branch = remote_and_branch.split("/", 1)
    _run_git(target, "config", f"branch.{branch}.remote", remote)
    _run_git(target, "config", f"branch.{branch}.merge", f"refs/heads/{remote_branch}")


def _has_config(target: Path, key: str) -> bool:
    result = subprocess.run(["git", "-C", str(target), "config", "--get-all", key], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0


def _read_status_exact(target: Path, expected: bytes) -> tuple[bytes, str]:
    modes = (
        ("default", ("status", "--porcelain=v2", "--branch")),
        ("all", ("status", "--porcelain=v2", "--branch", "--untracked-files=all")),
        (
            "default-unquoted",
            ("-c", "core.quotePath=false", "status", "--porcelain=v2", "--branch"),
        ),
        (
            "all-unquoted",
            (
                "-c",
                "core.quotePath=false",
                "status",
                "--porcelain=v2",
                "--branch",
                "--untracked-files=all",
            ),
        ),
    )
    first_actual = b""
    for index, (name, args) in enumerate(modes):
        actual = _run_git(target, *args, optional_locks=False)
        if index == 0:
            first_actual = actual
        if actual == expected:
            return actual, name
    return first_actual, "no_exact_match"


def _tracked_status_paths(target: Path) -> bytes:
    raw = _run_git(
        target,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=no",
        "--no-renames",
        optional_locks=False,
    )
    paths: list[bytes] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        if record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            if len(fields) != 9 or not fields[8]:
                raise RestoreError("invalid_tracked_status_record")
            paths.append(fields[8])
            continue
        raise RestoreError("unsupported_tracked_status_record")
    return b"".join(path + b"\0" for path in paths)


def _nul_paths(raw: bytes) -> list[str]:
    return [os.fsdecode(path) for path in raw.split(b"\0") if path]


def _decode_porcelain_path(raw: bytes) -> str:
    if not (raw.startswith(b'"') and raw.endswith(b'"')):
        return os.fsdecode(raw)
    data = raw[1:-1]
    decoded = bytearray()
    escapes = {
        ord("a"): 7,
        ord("b"): 8,
        ord("t"): 9,
        ord("n"): 10,
        ord("v"): 11,
        ord("f"): 12,
        ord("r"): 13,
        ord('"'): ord('"'),
        ord("\\"): ord("\\"),
    }
    index = 0
    while index < len(data):
        value = data[index]
        if value != ord("\\"):
            decoded.append(value)
            index += 1
            continue
        index += 1
        if index >= len(data):
            raise RestoreError("invalid_quoted_status_path")
        value = data[index]
        if ord("0") <= value <= ord("7"):
            digits = bytearray()
            while index < len(data) and len(digits) < 3 and ord("0") <= data[index] <= ord("7"):
                digits.append(data[index])
                index += 1
            decoded.append(int(digits.decode("ascii"), 8))
            continue
        if value not in escapes:
            raise RestoreError("invalid_quoted_status_escape")
        decoded.append(escapes[value])
        index += 1
    return os.fsdecode(bytes(decoded))


def _expected_tracked_status_paths(raw: bytes) -> set[str]:
    paths: set[str] = set()
    for line in raw.splitlines():
        path_field: bytes | None = None
        if line.startswith(b"1 "):
            fields = line.split(b" ", 8)
            path_field = fields[8] if len(fields) == 9 else None
        elif line.startswith(b"2 "):
            fields = line.split(b" ", 9)
            path_field = fields[9].split(b"\t", 1)[0] if len(fields) == 10 else None
        elif line.startswith(b"u "):
            fields = line.split(b" ", 10)
            path_field = fields[10] if len(fields) == 11 else None
        elif line.startswith((b"# ", b"? ", b"! ")):
            continue
        else:
            raise RestoreError("invalid_expected_status_record")
        if not path_field:
            raise RestoreError("invalid_expected_status_record")
        relative = _decode_porcelain_path(path_field)
        _safe_relative(relative, label="expected_status_path")
        if relative in paths:
            raise RestoreError("duplicate_expected_status_path")
        paths.add(relative)
    return paths


def _restore_validated_full_repository_file(
    target: Path,
    baseline: Path,
    relative: str,
    purpose: str,
) -> dict[str, str]:
    candidate = _full_repository_path(baseline, relative)
    staged = _run_git(target, "ls-files", "--stage", "-z", "--", relative)
    fields = staged.split(b" ", 2)
    if len(fields) != 3 or not fields[1]:
        raise RestoreError("invalid_staged_entry")
    expected_object_id = fields[1]
    candidate_object_id = _run_git(
        target,
        "hash-object",
        f"--path={relative}",
        str(candidate),
        optional_locks=False,
    ).strip()
    if candidate_object_id != expected_object_id:
        raise RestoreError("full_repository_candidate_object_mismatch")
    _copy_file(candidate, target / _safe_relative(relative, label="worktree_path"))
    return {
        "path": relative,
        "purpose": purpose,
        "sha256": sha256_file(candidate),
        "git_object_id": candidate_object_id.decode("ascii"),
    }


def restore_and_verify(baseline: Path, target: Path) -> dict[str, Any]:
    checked = validate_baseline(baseline)
    target = target.resolve()
    if target.exists():
        raise RestoreError("target_already_exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Path] = checked["metadata"]
    bundle = metadata["@git/repository.bundle"]
    status_raw = metadata["@git/status-before"].read_bytes()
    expected_tracked_paths = _expected_tracked_status_paths(status_raw)
    clone = subprocess.run(
        ["git", "clone", "--quiet", "--no-checkout", str(bundle), str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if clone.returncode:
        raise RestoreError("git_clone_failed")

    try:
        # The saved index is the source of truth for both tracked content and its
        # byte-exact stat cache. A normal clone checkout can apply different
        # line-ending/filter settings before the snapshot overlay.
        _copy_file(metadata["@git/index"], target / ".git" / "index")
        expected_index_hash = sha256_file(metadata["@git/index"])
        index_hash_after_copy = sha256_file(target / ".git" / "index")
        _run_git(target, "checkout-index", "--all", "--force", optional_locks=False)
        materialization_dirty = _tracked_status_paths(target)
        repair_paths = [
            relative
            for relative in _nul_paths(materialization_dirty)
            if relative not in expected_tracked_paths
        ]
        repair_input = b"".join(os.fsencode(path) + b"\0" for path in repair_paths)
        if repair_input:
            _run_git_with_input(
                target,
                (
                    "-c",
                    "core.autocrlf=false",
                    "checkout-index",
                    "--force",
                    "--stdin",
                    "-z",
                ),
                repair_input,
            )
        unresolved_materialization = _tracked_status_paths(target)
        manifest_tracked_dirty_paths = {
            str(entry["path"])
            for entry in checked["worktree_entries"]
            if entry.get("source") == "tracked_modified"
        }
        manifest_tracked_dirty_paths.update(str(entry["path"]) for entry in checked["deleted_entries"])
        status_only_fallbacks = [
            _restore_validated_full_repository_file(
                target,
                checked["baseline"],
                relative,
                "expected_status_only",
            )
            for relative in sorted(expected_tracked_paths - manifest_tracked_dirty_paths)
        ]
        clean_fallbacks: list[dict[str, str]] = []
        for relative in _nul_paths(unresolved_materialization):
            if relative not in expected_tracked_paths:
                clean_fallbacks.append(
                    _restore_validated_full_repository_file(
                        target,
                        checked["baseline"],
                        relative,
                        "clean_mixed_line_endings",
                    )
                )
        unexpected_materialization_paths = [
            relative
            for relative in _nul_paths(_tracked_status_paths(target))
            if relative not in expected_tracked_paths
        ]
        index_hash_after_materialization = sha256_file(target / ".git" / "index")

        for entry in checked["worktree_entries"]:
            source = _snapshot_path(checked["baseline"], entry["snapshotPath"])
            target_file = target / _safe_relative(entry["path"], label="worktree_path")
            _copy_file(source, target_file)
        for entry in checked["deleted_entries"]:
            target_file = target / _safe_relative(entry["path"], label="worktree_path")
            if target_file.is_symlink() or target_file.is_file():
                target_file.unlink()
            elif target_file.exists():
                raise RestoreError("deletion_marker_targets_directory")

        expected_refs = metadata["@git/refs-before"].read_bytes()
        refs = _parse_refs(expected_refs)
        head_raw = metadata["@git/HEAD"].read_bytes()
        _restore_refs(target, refs)
        _configure_branch(target, head_raw, status_raw, refs)
        _copy_file(metadata["@git/HEAD"], target / ".git" / "HEAD")

        actual_head = (target / ".git" / "HEAD").read_bytes()
        actual_refs = _run_git(target, "for-each-ref", "--format=%(refname) %(objectname)")
        index_hash_before_status = sha256_file(target / ".git" / "index")
        actual_status, status_untracked_mode = _read_status_exact(target, status_raw)
        actual_index_hash = sha256_file(target / ".git" / "index")
        actual_head_commit = _run_git(target, "rev-parse", "HEAD").strip()
        expected_head_commit = metadata["@git/head-commit"].read_bytes().strip()
        restored_files_ok = all(
            (target / _safe_relative(entry["path"], label="worktree_path")).is_file()
            and sha256_file(target / _safe_relative(entry["path"], label="worktree_path")) == entry["sha256"]
            for entry in checked["worktree_entries"]
        )
        deletions_ok = all(
            not (target / _safe_relative(entry["path"], label="worktree_path")).exists()
            for entry in checked["deleted_entries"]
        )
        verification = {
            "manifest_entries_verified": checked["checked_files"],
            "manifest_bytes_verified": checked["checked_bytes"],
            "restored_worktree_files": len(checked["worktree_entries"]),
            "deletion_markers": len(checked["deleted_entries"]),
            "materialization_repaired_paths": len(repair_paths),
            "materialization_unresolved_paths": unresolved_materialization.count(b"\0"),
            "materialization_expected_status_fallbacks": status_only_fallbacks,
            "materialization_clean_snapshot_fallbacks": clean_fallbacks,
            "unexpected_tracked_materialization_resolved": not unexpected_materialization_paths,
            "restored_files_match_manifest": restored_files_ok,
            "deletions_match_manifest": deletions_ok,
            "head_byte_exact_match": actual_head == head_raw,
            "head_commit_exact_match": actual_head_commit == expected_head_commit,
            "refs_byte_exact_match": actual_refs == expected_refs,
            "status_byte_exact_match": actual_status == status_raw,
            "status_untracked_mode": status_untracked_mode,
            "index_sha256_expected": expected_index_hash,
            "index_sha256_after_copy": index_hash_after_copy,
            "index_sha256_after_materialization": index_hash_after_materialization,
            "index_sha256_before_status": index_hash_before_status,
            "index_sha256_actual": actual_index_hash,
            "index_sha256_match": actual_index_hash == expected_index_hash,
            "index_unchanged_by_materialization": index_hash_after_materialization == index_hash_after_copy,
            "index_unchanged_by_status": actual_index_hash == index_hash_before_status,
        }
        passed = all(
            value
            for key, value in verification.items()
            if key.endswith("_match")
            or key.startswith("index_unchanged_by_")
            or key in {
                "restored_files_match_manifest",
                "deletions_match_manifest",
                "unexpected_tracked_materialization_resolved",
            }
        )
        return {
            "schema_version": "1.0",
            "kind": "isolated_day0_restore_drill",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "baseline_manifest_sha256": checked["manifest_sha256"],
            "target_mode": "caller_supplied",
            "verification": verification,
            "verdict": "PASS" if passed else "FAIL",
        }
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def run_ephemeral_drill(baseline: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=".day0-restore-drill-", dir=baseline.resolve().parent) as temporary:
        receipt = restore_and_verify(baseline, Path(temporary) / "restored")
    receipt["target_mode"] = "ephemeral"
    receipt["ephemeral_target_cleaned"] = True
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    try:
        receipt = restore_and_verify(args.baseline, args.target) if args.target else run_ephemeral_drill(args.baseline)
    except (OSError, RestoreError, subprocess.SubprocessError) as exc:
        receipt = {
            "schema_version": "1.0",
            "kind": "isolated_day0_restore_drill",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "verdict": "FAIL",
            "reason": str(exc),
        }
    atomic_write_json(args.output, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0 if receipt["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
