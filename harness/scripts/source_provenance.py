from __future__ import annotations

from typing import Any, Mapping, Sequence


DIRECT_REUSE_LICENSES = {"MIT", "Apache-2.0", "CC0-1.0"}
REQUIRED_FIELDS = {
    "source_repository",
    "upstream_commit",
    "source_path",
    "license_expression",
    "reuse_mode",
    "decision",
    "obligations",
    "resolved_obligations",
    "license_decision_receipt",
}


def _source_id(source: Mapping[str, Any]) -> str:
    return f"{source['source_repository']}@{source['upstream_commit']}:{source['source_path']}"


def evaluate_source_provenance(sources: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if not sources:
        return {
            "verdict": "INVALID",
            "reasons": ["source_provenance_empty"],
            "numerator": 0,
            "denominator": 0,
        }

    reasons: list[str] = []
    accepted = 0
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != REQUIRED_FIELDS:
            reasons.append("source_provenance_schema")
            continue
        if not all(isinstance(source[key], str) and source[key] for key in (
            "source_repository", "upstream_commit", "source_path", "license_expression", "reuse_mode", "decision"
        )):
            reasons.append("source_provenance_identity")
            continue
        identifier = _source_id(source)
        receipt = source["license_decision_receipt"]
        if not isinstance(receipt, Mapping) or not isinstance(receipt.get("canonical_sha256"), str):
            reasons.append(f"missing_license_decision_receipt:{identifier}")
            continue
        if source["reuse_mode"] == "direct_reuse" and source["license_expression"] not in DIRECT_REUSE_LICENSES:
            reasons.append(f"incompatible_direct_reuse:{identifier}:{source['license_expression']}")
            continue
        obligations = source["obligations"]
        resolved = source["resolved_obligations"]
        if not isinstance(obligations, list) or not isinstance(resolved, list) or not all(isinstance(item, str) for item in obligations + resolved):
            reasons.append(f"source_provenance_obligations:{identifier}")
            continue
        unresolved = sorted(set(obligations) - set(resolved))
        if unresolved:
            reasons.append(f"unresolved_obligations:{identifier}:{','.join(unresolved)}")
            continue
        accepted += 1

    return {
        "verdict": "PASS" if not reasons else "BLOCKED",
        "reasons": reasons,
        "numerator": accepted,
        "denominator": len(sources),
    }
