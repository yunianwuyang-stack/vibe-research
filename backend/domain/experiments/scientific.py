"""Scientific result admission derived from replayable artifacts, never model booleans."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class ScientificVerdict:
    accepted: bool
    issues: tuple[str, ...]
    derived: Mapping[str, Any]


def derive_ml_verdict(runs: Sequence[Mapping[str, Any]], *, metric: str,
                      direction: str = "higher") -> ScientificVerdict:
    """Derive multi-seed, baseline, ablation, leakage and calibration checks."""
    issues: list[str] = []
    if direction not in {"higher", "lower"}:
        issues.append("invalid_metric_direction")
    real = [r for r in runs if r.get("status") == "completed" and r.get("simulated") is False]
    seeds = {r.get("seed") for r in real if isinstance(r.get("seed"), int)}
    if len(seeds) < 2:
        issues.append("insufficient_real_seeds")
    by_variant: dict[str, list[float]] = {}
    for run in real:
        variant = str(run.get("variant") or "")
        value = run.get("metrics", {}).get(metric) if isinstance(run.get("metrics"), Mapping) else None
        if variant and isinstance(value, (int, float)) and math.isfinite(value):
            by_variant.setdefault(variant, []).append(float(value))
    for required in ("candidate", "baseline", "ablation"):
        if not by_variant.get(required):
            issues.append(f"missing_real_{required}")
    if any(run.get("train_ids_sha256") == run.get("test_ids_sha256") for run in real):
        issues.append("data_leakage_detected")
    if any("calibration_error" not in run.get("metrics", {}) for run in real):
        issues.append("calibration_not_computed")
    means = {name: sum(values) / len(values) for name, values in by_variant.items()}
    if "candidate" in means and "baseline" in means:
        delta = means["candidate"] - means["baseline"]
        if direction == "lower":
            delta = -delta
    else:
        delta = None
    return ScientificVerdict(not issues, tuple(dict.fromkeys(issues)), {
        "seed_count": len(seeds), "variant_means": means,
        "candidate_improvement": delta, "source_run_count": len(real),
    })


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    if not p_values or any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be in [0,1]")
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, (index, p_value) in enumerate(indexed):
        running = max(running, min(1.0, (total - rank) * p_value))
        adjusted[index] = running
    return adjusted


def adjudicate_math_claim(*, claim: str, verifier: str, artifact_hash: str | None,
                           replayable: bool, counterexample: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not claim.strip():
        raise ValueError("claim is required")
    formal = verifier in {"lean", "coq", "isabelle", "sympy"}
    proved = formal and replayable and isinstance(artifact_hash, str) and len(artifact_hash) == 64 and not counterexample
    return {"claim": claim, "verifier": verifier, "status": "proved" if proved else (
        "refuted" if counterexample else "unverified"), "artifact_hash": artifact_hash,
        "replayable": replayable, "counterexample": counterexample}


def admit_qualitative_corpus(*, source_uri: str, source_sha256: str, rights: Mapping[str, Any],
                             coding_scheme_version: str, negative_cases: Sequence[str],
                             reflexivity_note: str, generated_participants: bool = False) -> dict[str, Any]:
    if generated_participants:
        raise ValueError("fictional participant material is prohibited")
    required_rights = all(bool(rights.get(key)) for key in ("license", "allowed_use", "retention"))
    complete = (bool(source_uri.strip()) and len(source_sha256) == 64 and required_rights
                and bool(coding_scheme_version.strip()) and bool(negative_cases)
                and bool(reflexivity_note.strip()))
    if not complete:
        raise ValueError("qualitative corpus provenance is incomplete")
    payload = {"source_uri": source_uri, "source_sha256": source_sha256,
               "rights": dict(rights), "coding_scheme_version": coding_scheme_version,
               "negative_cases": list(negative_cases), "reflexivity_note": reflexivity_note}
    return {**payload, "lineage_sha256": _sha(_canonical(payload)), "status": "accepted"}


def verify_execution_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Re-hash receipt-bound files; one changed byte invalidates admission."""
    root = Path(bundle_dir)
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    issues: list[str] = []
    for relative, expected in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file() or _sha(path.read_bytes()) != expected:
            issues.append(f"tampered:{relative}")
    return {"passed": not issues, "issues": issues, "checked": len(manifest.get("files", {}))}


def write_execution_bundle(bundle_dir: str | Path, files: Sequence[str]) -> dict[str, Any]:
    root = Path(bundle_dir)
    hashes = {name: _sha((root / name).read_bytes()) for name in files}
    manifest = {"files": hashes, "coverage": 1.0}
    (root / "bundle-manifest.json").write_bytes(_canonical(manifest))
    return manifest


def blocked_data_receipt(reason_codes: Sequence[str]) -> dict[str, Any]:
    """Return only non-sensitive reason codes; never echo dataset metadata or PII."""
    allowed = {"missing_purpose", "missing_jurisdiction", "retention_invalid",
               "pii_not_approved", "license_unverified", "consent_unverified"}
    return {"status": "blocked", "reason_codes": [code for code in reason_codes if code in allowed]}
