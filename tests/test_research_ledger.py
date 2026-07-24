"""Contracts for durable, evidence-native run persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain import Approval, Decision, Project
from infrastructure.persistence.research_ledger import ArtifactIndex, ArtifactIntegrityError, DecisionLedger, RunManifestStore


def test_manifest_replacement_is_valid_json_and_contains_run_identity(tmp_path: Path) -> None:
    store = RunManifestStore(tmp_path)
    destination = store.write("run-1", {"inputs": ["a"], "status": "completed"})
    assert json.loads(destination.read_text(encoding="utf-8"))["run_id"] == "run-1"
    store.write("run-1", {"inputs": ["b"]})
    assert store.read("run-1")["inputs"] == ["b"]
    assert not list(destination.parent.glob(".run-1.json.*"))


def test_artifact_index_records_provenance_and_detects_tampering(tmp_path: Path) -> None:
    file = tmp_path / "result.csv"; file.write_text("value\n1\n", encoding="utf-8")
    index = ArtifactIndex(tmp_path)
    artifact = index.register(file, run_id="run-1", schema_version="1.0", producer="stats", input_hashes=("a" * 64,))
    assert artifact.producer == "stats" and artifact.input_hashes == ("a" * 64,)
    index.verify(artifact)
    file.write_text("value\n2\n", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError): index.verify(artifact)


def test_artifact_index_decodes_percent_encoded_unicode_file_uri(tmp_path: Path) -> None:
    unicode_root = tmp_path / "博士生 空间" / "证据"
    unicode_root.mkdir(parents=True)
    file = unicode_root / "结果.csv"
    file.write_text("value\n1\n", encoding="utf-8")

    artifact = ArtifactIndex(unicode_root).register(
        file, run_id="unicode-run", schema_version="1.0", producer="stats", input_hashes=("b" * 64,)
    )

    assert "%" in artifact.uri
    ArtifactIndex(unicode_root).verify(artifact)


def test_decision_ledger_is_append_only_and_summary_excludes_unapproved_drafts(tmp_path: Path) -> None:
    project = Project("Ledger")
    approved = Decision(project.id, "scope", "Approved boundary")
    draft = Decision(project.id, "draft", "Not approved")
    ledger = DecisionLedger(tmp_path)
    ledger.append(approved); first = ledger.path.read_text(encoding="utf-8")
    ledger.append(draft); second = ledger.path.read_text(encoding="utf-8")
    assert second.startswith(first) and len(second.splitlines()) == 2
    assert ledger.approved_summary([Approval(approved.id, "supervisor", "approved")]) == [json.loads(first)]
