from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "harness" / "v2" / "scripts" / "baseline.py"
SPEC = importlib.util.spec_from_file_location("harness_v2_baseline", MODULE_PATH)
assert SPEC and SPEC.loader
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _write_fixture(root: Path) -> tuple[Path, Path]:
    target = root / "preexisting.txt"
    target.write_text("alpha\r\nbeta\r\n", encoding="utf-8", newline="")
    stat = target.stat()
    baseline_id = "baseline-fixture"
    folder = root / "harness" / "v2" / "evidence" / "P0" / "baseline" / baseline_id
    folder.mkdir(parents=True)
    patch = b"diff --git a/preexisting.txt b/preexisting.txt\n--- a/preexisting.txt\n+++ b/preexisting.txt\n@@ -1 +1 @@\n-old\n+alpha\n"
    (folder / "preexisting.hunks.patch").write_bytes(patch)
    (folder / "preexisting.diff.binary.patch").write_bytes(b"")
    (folder / "status.start.z").write_bytes(b"same")
    (folder / "status.end.z").write_bytes(b"same")
    manifest_path = folder / "preimage-files.tsv.gz"
    with gzip.open(manifest_path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(baseline.HEADER)
        writer.writerow(
            [
                "untracked",
                _b64("preexisting.txt"),
                "true",
                "file",
                str(stat.st_size),
                str(stat.st_mtime_ns // 100 + 621355968000000000),
                "Archive" if hasattr(stat, "st_file_attributes") else "",
                _sha(target),
                "crlf",
                _b64("fixture-owner"),
                _b64("fixture-sddl"),
                "true",
                "",
            ]
        )
    artifacts = {
        path.name: _sha(path)
        for path in folder.iterdir()
        if path.name not in {"baseline-summary.json", "import-envelope.json"}
    }
    status_hash = _sha(folder / "status.start.z")
    summary = {
        "schema_version": 1,
        "status_stable": True,
        "start_status_sha256": status_hash,
        "end_status_sha256": status_hash,
        "counts": {"tracked": 0, "untracked": 1, "ignored": 0, "missing": 0, "errors": 0, "unstable": 0},
        "total": 1,
        "artifact_sha256": artifacts,
    }
    summary_path = folder / "baseline-summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    (root / "开发指导.md").write_text("guide", encoding="utf-8")
    (root / "goal提示词.md").write_text("goal", encoding="utf-8")
    envelope = {
        "baseline_summary_sha256": _sha(summary_path),
        "development_guide_sha256": _sha(root / "开发指导.md"),
        "goal_prompt_sha256": _sha(root / "goal提示词.md"),
    }
    envelope_path = folder / "import-envelope.json"
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    v2 = root / "harness" / "v2"
    (v2 / "manifest.json").write_text(
        json.dumps({"baseline_id": baseline_id, "baseline_envelope_sha256": _sha(envelope_path)}),
        encoding="utf-8",
    )
    return folder, target


def test_parse_hunks_hashes_exact_blocks() -> None:
    patch = b"diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n@@ -3 +3 @@\n-c\n+d\n"
    result = baseline.parse_hunks(patch)
    assert result["file_count"] == 1
    assert result["hunk_count"] == 2
    assert result["patch_sha256"] == hashlib.sha256(patch).hexdigest()
    assert result["files"][0]["hunks"][0]["sha256"] != result["files"][0]["hunks"][1]["sha256"]


def test_parse_hunks_rejects_content_before_diff() -> None:
    with pytest.raises(baseline.BaselineError, match="before first diff"):
        baseline.parse_hunks(b"not-a-diff\n")


def test_static_checks_treat_empty_artifact_mismatches_as_pass() -> None:
    checks = {
        "artifact_mismatches": [],
        "declared_artifact_count": 19,
        "baseline_id_match": True,
        "summary_hash_match": True,
    }
    assert baseline._static_checks_pass(checks)
    checks["artifact_mismatches"] = [{"path": "changed"}]
    assert not baseline._static_checks_pass(checks)


def test_fixture_capture_verifies_without_live_git(tmp_path: Path) -> None:
    folder, _ = _write_fixture(tmp_path)
    manifest = baseline.load_json(tmp_path / "harness" / "v2" / "manifest.json")
    envelope, summary, artifacts = baseline._artifact_integrity(tmp_path, manifest, folder)
    rows = baseline.validate_rows(tmp_path, folder, summary, live=False)
    hunks = baseline.parse_hunks((folder / "preexisting.hunks.patch").read_bytes())
    assert envelope["baseline_summary_sha256"] == baseline.sha256_file(
        folder / "baseline-summary.json"
    )
    assert artifacts["preexisting.hunks.patch"] == baseline.sha256_file(
        folder / "preexisting.hunks.patch"
    )
    assert rows["row_count"] == 1
    assert hunks["hunk_count"] == 1


def test_mutated_predecessor_is_detected(tmp_path: Path) -> None:
    folder, target = _write_fixture(tmp_path)
    summary = baseline.load_json(folder / "baseline-summary.json")
    target.write_text("changed", encoding="utf-8")
    rows = baseline.validate_rows(tmp_path, folder, summary, live=True)
    assert rows["live_mismatch_count"] == 1
    assert rows["live_mismatches"][0]["reason"] in {"size_changed", "mtime_changed", "content_changed"}


def test_missing_predecessor_is_detected(tmp_path: Path) -> None:
    folder, target = _write_fixture(tmp_path)
    summary = baseline.load_json(folder / "baseline-summary.json")
    target.unlink()
    rows = baseline.validate_rows(tmp_path, folder, summary, live=True)
    assert rows["live_mismatch_count"] == 1
    assert rows["live_mismatches"][0]["reason"] == "existence_changed"


def test_corrupt_manifest_row_is_rejected(tmp_path: Path) -> None:
    folder, _ = _write_fixture(tmp_path)
    with gzip.open(folder / "preimage-files.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("bad\theader\n")
    summary = baseline.load_json(folder / "baseline-summary.json")
    with pytest.raises(baseline.BaselineError, match="header mismatch"):
        baseline.validate_rows(tmp_path, folder, summary, live=False)


def test_explicit_allowed_change_records_both_hashes_and_preserves_attributes(tmp_path: Path) -> None:
    folder, target = _write_fixture(tmp_path)
    summary = baseline.load_json(folder / "baseline-summary.json")
    target.write_text("authorized change", encoding="utf-8")
    rows = baseline.validate_rows(
        tmp_path, folder, summary, live=True, allowed_changes={"preexisting.txt"}
    )
    assert rows["live_mismatch_count"] == 0
    assert rows["allowed_changes"][0]["preimage_sha256"] != rows["allowed_changes"][0]["postimage_sha256"]


def test_unused_allowed_change_is_rejected(tmp_path: Path) -> None:
    folder, _ = _write_fixture(tmp_path)
    summary = baseline.load_json(folder / "baseline-summary.json")
    with pytest.raises(baseline.BaselineError, match="absent from baseline"):
        baseline.validate_rows(
            tmp_path, folder, summary, live=True, allowed_changes={"not-present.txt"}
        )
