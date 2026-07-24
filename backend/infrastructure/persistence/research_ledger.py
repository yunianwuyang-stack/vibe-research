"""Atomic run manifests, tamper-evident artifact index, and append-only decisions."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from domain import Approval, Artifact, Decision
from domain.serialization import entity_to_dict


class ArtifactIntegrityError(ValueError):
    """Raised when an artifact no longer matches the recorded digest."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_json(path: str | Path, value: dict[str, Any]) -> None:
    """Replace a JSON document atomically, so readers never observe a partial file."""
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


class RunManifestStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def write(self, run_id: str, manifest: dict[str, Any]) -> Path:
        if not run_id.strip():
            raise ValueError("run id must not be empty")
        payload = {"schema_version": "1.0", "run_id": run_id, **manifest}
        destination = self.root / "manifests" / f"{run_id}.json"
        atomic_write_json(destination, payload)
        return destination

    def read(self, run_id: str) -> dict[str, Any]:
        return json.loads((self.root / "manifests" / f"{run_id}.json").read_text(encoding="utf-8"))


class ArtifactIndex:
    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / "artifacts.json"

    def register(self, artifact_path: str | Path, *, run_id: str, schema_version: str, producer: str, input_hashes: Iterable[str] = ()) -> Artifact:
        path = Path(artifact_path)
        artifact = Artifact(run_id, path.resolve().as_uri(), sha256_file(path), schema_version, producer, tuple(input_hashes))
        current = self._load(); current[str(artifact.id)] = entity_to_dict(artifact)
        atomic_write_json(self.path, {"schema_version": "1.0", "artifacts": current})
        return artifact

    def verify(self, artifact: Artifact) -> None:
        parsed = urlsplit(artifact.uri)
        if parsed.scheme.lower() != "file" or parsed.query or parsed.fragment or parsed.netloc not in {"", "localhost"}:
            raise ArtifactIntegrityError(f"unsupported artifact URI: {artifact.id}")
        decoded_path = unquote(parsed.path)
        if os.name == "nt" and len(decoded_path) >= 3 and decoded_path[0] == "/" and decoded_path[2] == ":":
            decoded_path = decoded_path[1:]
        if not decoded_path:
            raise ArtifactIntegrityError(f"empty artifact URI path: {artifact.id}")
        path = Path(decoded_path)
        if sha256_file(path) != artifact.sha256:
            raise ArtifactIntegrityError(f"artifact hash mismatch: {artifact.id}")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists(): return {}
        return json.loads(self.path.read_text(encoding="utf-8"))["artifacts"]


class DecisionLedger:
    """Append-only JSONL ledger plus an approval-filtered public summary."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root); self.path = self.root / "decisions.jsonl"

    def append(self, decision: Decision) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record = entity_to_dict(decision)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush(); os.fsync(handle.fileno())

    def approved_summary(self, approvals: Iterable[Approval]) -> list[dict[str, Any]]:
        allowed = {str(item.entity_id) for item in approvals if item.decision == "approved"}
        if not self.path.exists(): return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip() and json.loads(line).get("id") in allowed]
