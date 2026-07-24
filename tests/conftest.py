from __future__ import annotations

from pathlib import Path

import pytest


LANES = ("unit", "contract", "integration", "live_provider", "desktop", "release", "private_eval")


def _lane(item: pytest.Item) -> str:
    path = Path(str(item.path)).name.lower()
    node = item.nodeid.lower()
    if "private_eval" in node or "held_out" in node:
        return "private_eval"
    if any(token in node for token in ("live_provider", "real_literature_transport", "real_cli_agent_invocation")):
        return "live_provider"
    if any(token in path for token in ("dual_clean", "desktop_e2e", "electron_", "packaged_gui")):
        return "desktop"
    if any(
        token in path
        for token in (
            "release", "installer", "runtime_layout", "packaged_runtime", "license_artifacts",
            "product_identity", "updater_rollback", "linux_package", "source_snapshot",
        )
    ):
        return "release"
    if any(token in path for token in ("http_e2e", "real_uvicorn", "r01_", "research_quality_loop", "full_pipeline")):
        return "integration"
    if any(token in path for token in ("contract", "_api", "security_", "upload_limits", "migration_")):
        return "contract"
    return "unit"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        selected = _lane(item)
        item.add_marker(getattr(pytest.mark, selected))
        assigned = [name for name in LANES if item.get_closest_marker(name) is not None]
        if assigned != [selected]:
            raise pytest.UsageError(f"test must belong to exactly one lane: {item.nodeid}: {assigned}")
