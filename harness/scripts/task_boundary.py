from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Mapping, Sequence


def _normalize(value: str) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {".", "..", ""} for part in normalized.split("/")):
        return None
    return normalized


def _matches(path: str, pattern: str) -> bool:
    normalized_path = _normalize(path)
    normalized_pattern = _normalize(pattern)
    if normalized_path is None or normalized_pattern is None:
        return False
    if normalized_pattern.endswith("/**"):
        directory = normalized_pattern[:-3].rstrip("/")
        return normalized_path == directory or normalized_path.startswith(directory + "/")
    return fnmatchcase(normalized_path, normalized_pattern)


def evaluate_allowed_paths(
    before: Mapping[str, str], after: Mapping[str, str], allowed: Sequence[str]
) -> dict[str, object]:
    paths = list(before) + list(after)
    normalized_paths = [_normalize(path) for path in paths]
    normalized_allowed = [_normalize(pattern) for pattern in allowed]
    if any(path is None for path in normalized_paths) or any(pattern is None for pattern in normalized_allowed):
        return {
            "verdict": "INVALID",
            "changed_paths": [],
            "violations": [],
            "numerator": 0,
            "denominator": 0,
        }

    normalized_before = {normalized: before[original] for original, normalized in zip(before, normalized_paths[: len(before)])}
    normalized_after = {normalized: after[original] for original, normalized in zip(after, normalized_paths[len(before) :])}
    changed_paths = sorted(
        path for path in set(normalized_before) | set(normalized_after) if normalized_before.get(path) != normalized_after.get(path)
    )
    violations = [path for path in changed_paths if not any(_matches(path, pattern) for pattern in normalized_allowed)]
    denominator = len(changed_paths)
    numerator = denominator - len(violations)
    verdict = "INVALID" if denominator == 0 else "PASS" if not violations else "FAIL"
    return {
        "verdict": verdict,
        "changed_paths": changed_paths,
        "violations": violations,
        "numerator": numerator,
        "denominator": denominator,
    }
