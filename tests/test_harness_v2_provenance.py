from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


MODULE_PATH = Path(__file__).parents[1] / "harness" / "v2" / "scripts" / "provenance.py"
SPEC = importlib.util.spec_from_file_location("harness_v2_provenance", MODULE_PATH)
assert SPEC and SPEC.loader
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)

MIT_TEXT = """MIT License

Copyright (c) Fixture

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction.
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _repo(
    path: Path,
    *,
    origin: str = "https://github.com/example/fixture.git",
    license_file: bool = True,
) -> None:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "fixture@example.invalid")
    _git(path, "config", "user.name", "Fixture")
    _git(path, "remote", "add", "origin", origin)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    if license_file:
        (path / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "fixture")


def _source(repo: Path, *, source_id: str = "SRC-FIXTURE", spdx: str = "MIT") -> dict[str, object]:
    files = []
    if (repo / "LICENSE").exists():
        files.append(
            {
                "path": "LICENSE",
                "sha256": provenance.sha256_file(repo / "LICENSE"),
                "size": (repo / "LICENSE").stat().st_size,
            }
        )
    return {
        "id": source_id,
        "directory": repo.name,
        "origin": provenance.normalize_origin(_git(repo, "remote", "get-url", "origin")),
        "expected_commit": _git(repo, "rev-parse", "HEAD"),
        "expected_git_status_sha256": provenance.EMPTY_SHA256,
        "expected_git_status_entry_count": 0,
        "root_license": {
            "spdx": spdx,
            "scope": provenance.ROOT_LICENSE_SCOPE,
            "files": files,
        },
    }


def _registry(reference_root: str, sources: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "reference_root": reference_root,
        "expected_source_count": len(sources),
        "default_artifact_reuse": "forbidden_until_verified_artifact_decision",
        "sources": sources,
        "decision_rules": provenance.EXPECTED_DECISION_RULES,
        "hard_clean_room_isolation_at_bootstrap": False,
        "task_level_artifact_decision_coverage_required": True,
    }


def _root(tmp_path: Path, registry: dict[str, object]) -> Path:
    root = tmp_path / "product"
    path = root / "harness" / "v2" / "registry"
    path.mkdir(parents=True)
    (path / "reference-sources.json").write_text(
        json.dumps(registry, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    return root


def _fixture(tmp_path: Path, *, license_file: bool = True) -> tuple[Path, Path]:
    refs = tmp_path / "refs"
    refs.mkdir()
    repo = refs / "fixture"
    _repo(repo, license_file=license_file)
    spdx = "MIT" if license_file else "NOASSERTION"
    root = _root(tmp_path, _registry("../refs", [_source(repo, spdx=spdx)]))
    return root, repo


def _read_registry(root: Path) -> dict[str, object]:
    return json.loads(
        (root / "harness" / "v2" / "registry" / "reference-sources.json").read_text(
            encoding="utf-8"
        )
    )


def _write_registry(root: Path, registry: dict[str, object]) -> None:
    (root / "harness" / "v2" / "registry" / "reference-sources.json").write_text(
        json.dumps(registry, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def _state_paths(root: Path) -> dict[str, Path]:
    return provenance._paths(root.resolve())


def test_snapshot_is_deterministic_pinned_and_host_path_free(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    first_lock, first_decisions = provenance.build_snapshot(root)
    second_lock, second_decisions = provenance.build_snapshot(root)
    first = provenance.canonical_json([first_lock, first_decisions])
    second = provenance.canonical_json([second_lock, second_decisions])
    assert first == second
    assert first_lock["reference_root"] == "../refs"
    assert "captured_at" not in first.decode("utf-8")
    assert str(tmp_path).encode() not in first
    entry = first_lock["sources"][0]
    assert len(entry["commit"]) == 40
    assert entry["git_status_sha256"] == provenance.EMPTY_SHA256
    assert entry["git_status_entry_count"] == 0
    assert len(entry["license_files"][0]["sha256"]) == 64
    assert first_decisions[0]["implementation_access_allowed"] is False


def test_freeze_and_read_only_validate_are_byte_stable(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    observation_path = tmp_path / "output" / "observation.json"
    first = provenance.freeze(root, observation_path)
    paths = _state_paths(root)
    tracked = [*paths.values(), observation_path]
    first_bytes = {path: path.read_bytes() for path in tracked}
    first_mtimes = {path: path.stat().st_mtime_ns for path in tracked}

    second = provenance.freeze(root, observation_path)
    validated = provenance.validate(root)

    assert first == second == validated
    assert first_bytes == {path: path.read_bytes() for path in tracked}
    assert first_mtimes == {path: path.stat().st_mtime_ns for path in tracked}


def test_commit_drift_is_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    (repo / "README.md").write_text("new commit\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "drift")
    with pytest.raises(provenance.ProvenanceError, match="commit drift"):
        provenance.build_snapshot(root)


def test_dirty_status_drift_is_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    (repo / "UNTRACKED.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="git status drift"):
        provenance.build_snapshot(root)


def test_exact_license_hash_and_size_drift_is_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    (repo / "LICENSE").write_text(MIT_TEXT + "changed\n", encoding="utf-8")
    _git(repo, "add", "LICENSE")
    _git(repo, "commit", "-qm", "license drift")
    registry = _read_registry(root)
    registry["sources"][0]["expected_commit"] = _git(repo, "rev-parse", "HEAD")
    _write_registry(root, registry)
    with pytest.raises(provenance.ProvenanceError, match="root license file drift"):
        provenance.build_snapshot(root)


def test_mislabeled_spdx_is_rejected_independently_of_hash(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    registry = _read_registry(root)
    registry["sources"][0]["root_license"]["spdx"] = "Apache-2.0"
    _write_registry(root, registry)
    with pytest.raises(provenance.ProvenanceError, match="SPDX mismatch"):
        provenance.build_snapshot(root)


def test_origin_drift_is_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    _git(repo, "remote", "set-url", "origin", "https://github.com/other/repo.git")
    with pytest.raises(provenance.ProvenanceError, match="origin mismatch"):
        provenance.build_snapshot(root)


def test_license_presence_drift_from_noassertion_is_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path, license_file=False)
    (repo / "LICENSE").write_text(MIT_TEXT, encoding="utf-8")
    _git(repo, "add", "LICENSE")
    _git(repo, "commit", "-qm", "unexpected license")
    registry = _read_registry(root)
    registry["sources"][0]["expected_commit"] = _git(repo, "rev-parse", "HEAD")
    _write_registry(root, registry)
    with pytest.raises(provenance.ProvenanceError, match="root license file drift"):
        provenance.build_snapshot(root)


def test_absolute_reference_root_and_noncanonical_origin_are_rejected(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    registry = _read_registry(root)
    registry["reference_root"] = str(repo.parent.resolve())
    with pytest.raises(provenance.ProvenanceError, match="relative"):
        provenance.validate_registry(registry)
    registry["reference_root"] = "../refs"
    registry["sources"][0]["origin"] += ".git"
    with pytest.raises(provenance.ProvenanceError, match="not canonical"):
        provenance.validate_registry(registry)


def test_registry_requires_full_commit_clean_pin_and_exact_scope(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    registry = _read_registry(root)
    source = registry["sources"][0]
    source["expected_commit"] = source["expected_commit"][:12]
    with pytest.raises(provenance.ProvenanceError, match="full commit"):
        provenance.validate_registry(registry)
    source["expected_commit"] = "a" * 40
    source["expected_git_status_entry_count"] = 1
    with pytest.raises(provenance.ProvenanceError, match="pinned clean"):
        provenance.validate_registry(registry)
    source["expected_git_status_entry_count"] = 0
    source["root_license"]["scope"] = "whole_repository"
    with pytest.raises(provenance.ProvenanceError, match="license scope"):
        provenance.validate_registry(registry)


def test_truncated_ledger_is_not_silently_repaired(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    observation_path = tmp_path / "observation.json"
    provenance.freeze(root, observation_path)
    paths = _state_paths(root)
    ledger = paths["ledger"].read_bytes()
    paths["ledger"].write_bytes(b"")
    anchor_before = paths["anchor"].read_bytes()
    with pytest.raises(provenance.ProvenanceError, match="anchor mismatch"):
        provenance.freeze(root, observation_path)
    assert paths["ledger"].read_bytes() == b""
    assert paths["anchor"].read_bytes() == anchor_before
    assert ledger


def test_reordered_ledger_is_rejected(tmp_path: Path) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    repo_a = refs / "a"
    repo_b = refs / "b"
    _repo(repo_a, origin="https://github.com/example/a.git")
    _repo(repo_b, origin="https://github.com/example/b.git")
    root = _root(
        tmp_path,
        _registry(
            "../refs",
            [_source(repo_a, source_id="SRC-A"), _source(repo_b, source_id="SRC-B")],
        ),
    )
    observation_path = tmp_path / "observation.json"
    provenance.freeze(root, observation_path)
    paths = _state_paths(root)
    lines = paths["ledger"].read_bytes().splitlines(keepends=True)
    reordered = lines[1] + lines[0]
    paths["ledger"].write_bytes(reordered)
    with pytest.raises(provenance.ProvenanceError, match="sequence mismatch|prev_hash mismatch"):
        provenance.validate(root)
    assert paths["ledger"].read_bytes() == reordered


def test_rehashed_ledger_content_is_caught_by_anchor(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    provenance.freeze(root, tmp_path / "observation.json")
    paths = _state_paths(root)
    event = json.loads(paths["ledger"].read_text(encoding="utf-8"))
    decision = provenance._decision_from_event(event)
    decision["reason"] = "tampered-and-rehashed"
    replacement = provenance._make_event(decision, 1, provenance.GENESIS_EVENT_HASH)
    paths["ledger"].write_bytes(provenance.canonical_json(replacement) + b"\n")
    with pytest.raises(provenance.ProvenanceError, match="anchor mismatch"):
        provenance.validate(root)


def test_ledger_conflict_prevalidation_leaves_all_outputs_unchanged(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    _, decisions = provenance.build_snapshot(root)
    conflict = dict(decisions[0], status="changed")
    _, state = provenance._extend_ledger(provenance._parse_chained_ledger(b""), [conflict])
    paths = _state_paths(root)
    paths["ledger"].parent.mkdir(parents=True)
    paths["ledger"].write_bytes(state["raw"])
    paths["anchor"].write_bytes(
        provenance.canonical_json(provenance._committed_anchor(state)) + b"\n"
    )
    before = {name: path.read_bytes() for name, path in paths.items() if path.exists()}
    observation_path = tmp_path / "observation.json"

    with pytest.raises(provenance.ProvenanceError, match="decision drift"):
        provenance.freeze(root, observation_path)

    assert not paths["lock"].exists()
    assert not paths["bootstrap"].exists()
    assert not observation_path.exists()
    assert before == {name: path.read_bytes() for name, path in paths.items() if path.exists()}


def test_staging_failure_precedes_every_authoritative_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _fixture(tmp_path)
    paths = _state_paths(root)
    observation_path = tmp_path / "observation.json"
    calls = 0
    real_stage = provenance._stage_write

    def fail_second_stage(path: Path, payload: bytes) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected staging failure")
        return real_stage(path, payload)

    monkeypatch.setattr(provenance, "_stage_write", fail_second_stage)
    with pytest.raises(OSError, match="injected staging failure"):
        provenance.freeze(root, observation_path)

    assert not any(path.exists() for path in paths.values())
    assert not observation_path.exists()


def test_pending_append_crash_is_completed_without_tail_deletion(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    _, decisions = provenance.build_snapshot(root)
    base = provenance._parse_chained_ledger(b"")
    append_payload, target = provenance._extend_ledger(base, decisions)
    pending = provenance._pending_anchor(base, target, append_payload, None)
    paths = _state_paths(root)
    paths["ledger"].parent.mkdir(parents=True)
    prefix = append_payload[: len(append_payload) // 2]
    paths["ledger"].write_bytes(prefix)
    paths["anchor"].write_bytes(provenance.canonical_json(pending) + b"\n")

    observation = provenance.freeze(root, tmp_path / "observation.json")

    assert paths["ledger"].read_bytes() == append_payload
    assert paths["ledger"].read_bytes().startswith(prefix)
    assert json.loads(paths["anchor"].read_text(encoding="utf-8"))["state"] == "committed"
    assert provenance.validate(root) == observation


def test_divergent_pending_tail_fails_closed_without_mutation(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    _, decisions = provenance.build_snapshot(root)
    base = provenance._parse_chained_ledger(b"")
    append_payload, target = provenance._extend_ledger(base, decisions)
    pending = provenance._pending_anchor(base, target, append_payload, None)
    paths = _state_paths(root)
    paths["ledger"].parent.mkdir(parents=True)
    paths["ledger"].write_bytes(b"not-a-prefix")
    paths["anchor"].write_bytes(provenance.canonical_json(pending) + b"\n")
    before_ledger = paths["ledger"].read_bytes()
    before_anchor = paths["anchor"].read_bytes()

    with pytest.raises(provenance.ProvenanceError, match="does not match pending append"):
        provenance.freeze(root, tmp_path / "observation.json")

    assert paths["ledger"].read_bytes() == before_ledger
    assert paths["anchor"].read_bytes() == before_anchor


def test_explicit_legacy_import_preserves_sixteen_lines_and_binds_oracle() -> None:
    expected = [
        {"schema_version": 1, "decision_id": f"LEGACY-{index:02d}", "status": "verified"}
        for index in range(16)
    ]
    raw = b"".join(provenance.canonical_json(item) + b"\n" for item in expected)
    chain, state, legacy_import = provenance.import_legacy_events(raw, expected)
    assert state["event_count"] == 16
    assert len(chain.splitlines()) == 16
    assert legacy_import == {"event_count": 16, "sha256": provenance.sha256_bytes(raw)}
    assert [event["sequence"] for event in state["events"]] == list(range(1, 17))
    assert state["events"][0]["prev_hash"] == provenance.GENESIS_EVENT_HASH
    assert state["events"][-1]["prev_hash"] == state["events"][-2]["event_hash"]
    drifted = [*expected]
    drifted[-1] = dict(drifted[-1], status="changed")
    with pytest.raises(provenance.ProvenanceError, match="legacy decision drift"):
        provenance.import_legacy_events(raw, drifted)


def test_one_time_legacy_migration_is_explicit_and_then_validates(tmp_path: Path) -> None:
    root, repo = _fixture(tmp_path)
    lock, decisions = provenance.build_snapshot(root)
    paths = _state_paths(root)
    paths["ledger"].parent.mkdir(parents=True)
    legacy_lock = {
        "schema_version": 1,
        "captured_at_utc": "2026-01-01T00:00:00+00:00",
        "registry_sha256": "a" * 64,
        "reference_root": str(repo.parent.resolve()),
        "source_count": lock["source_count"],
        "artifact_reuse_allowed_count": lock["artifact_reuse_allowed_count"],
        "sources": lock["sources"],
    }
    paths["lock"].write_bytes(provenance.canonical_json(legacy_lock) + b"\n")
    paths["bootstrap"].write_bytes(provenance._decisions_payload(decisions))
    legacy_decisions = [provenance.LEGACY_ORIGINAL_DECISION, *decisions]
    paths["ledger"].write_bytes(
        b"".join(provenance.canonical_json(item) + b"\n" for item in legacy_decisions)
    )
    observation_path = tmp_path / "legacy-observation.json"

    observation = provenance.migrate_legacy(root, observation_path)

    assert json.loads(paths["lock"].read_text(encoding="utf-8"))["schema_version"] == 2
    assert json.loads(paths["anchor"].read_text(encoding="utf-8"))["legacy_import"][
        "event_count"
    ] == 2
    assert provenance.validate(root) == observation
    with pytest.raises(provenance.ProvenanceError, match="one-time"):
        provenance.migrate_legacy(root, observation_path)


def test_builder_observation_cannot_self_pass_or_claim_core_scope(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    observation_path = tmp_path / "explicit-observation.json"
    observation = provenance.freeze(root, observation_path)
    rendered = observation_path.read_text(encoding="utf-8")
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert observation["verdict"] == "CHECKS_PASSED_PENDING_INDEPENDENT_VERIFICATION"
    assert observation["requirement_ids"] == ["REQ-P0-07"]
    assert observation["implementation_access_allowed"] == 0
    assert observation["implementation_access_allowed_count"] == 0
    assert observation["root_metadata_authorizes_artifact_reuse"] is False
    assert observation["p0_07_pass_claimed"] is False
    assert observation["task_level_artifact_decision_coverage"] == (
        "REQUIRED_NOT_PERFORMED_BY_THIS_BUILDER"
    )
    assert "VERIFIED_PASS" not in rendered
    assert "REQ-P10" not in rendered and "REQ-DOD" not in rendered
    assert "attempt-" not in source
    assert "receipt.json" not in source


def test_validate_rejects_pending_anchor_without_recovery_writes(tmp_path: Path) -> None:
    root, _ = _fixture(tmp_path)
    observation_path = tmp_path / "observation.json"
    provenance.freeze(root, observation_path)
    paths = _state_paths(root)
    state = provenance._parse_chained_ledger(paths["ledger"].read_bytes())
    pending = provenance._pending_anchor(state, state, b"", None)
    paths["anchor"].write_bytes(provenance.canonical_json(pending) + b"\n")
    before = paths["anchor"].read_bytes()
    with pytest.raises(provenance.ProvenanceError, match="validate is read only"):
        provenance.validate(root)
    assert paths["anchor"].read_bytes() == before


def test_real_registry_contains_fifteen_complete_frozen_sources() -> None:
    registry_path = MODULE_PATH.parents[1] / "registry" / "reference-sources.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = provenance.validate_registry(registry)
    assert registry["reference_root"] == "../参考开源仓库"
    assert len(sources) == 15
    assert all(len(source["expected_commit"]) == 40 for source in sources)
    assert all(source["expected_git_status_sha256"] == provenance.EMPTY_SHA256 for source in sources)
    assert all(source["expected_git_status_entry_count"] == 0 for source in sources)
    assert all(source["root_license"]["scope"] == provenance.ROOT_LICENSE_SCOPE for source in sources)
