"""Fail-closed transport, execution, and assurance state projection."""
from __future__ import annotations

from typing import Any, Mapping


def project_state_planes(row: Mapping[str, Any]) -> dict[str, str]:
    status = str(row.get("status") or "pending")
    error = str(row.get("error_message") or "").strip()
    if status == "completed":
        return {
            "transport": "succeeded",
            "execution": "succeeded",
            "assurance": "pending",
            "root_cause": "assurance_not_yet_verified",
            "remediation": "Run assurance checks before treating outputs as verified.",
        }
    if status in {"failed", "cancelled"}:
        transport = "failed" if any(
            token in error.lower() for token in ("transport", "provider", "connection", "timeout")
        ) else "succeeded"
        return {
            "transport": transport,
            "execution": "failed",
            "assurance": "blocked",
            "root_cause": error or "workflow_execution_failed",
            "remediation": "Resolve the reported failure before rerunning or publishing outputs.",
        }
    return {
        "transport": "unknown",
        "execution": "in_progress",
        "assurance": "blocked",
        "root_cause": error or "workflow_not_terminal",
        "remediation": "Wait for execution to finish; intermediate artifacts are not publishable.",
    }
