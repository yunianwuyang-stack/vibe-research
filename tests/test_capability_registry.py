from __future__ import annotations

import pytest


def test_registry_reports_required_shape_and_blocked_is_explicit(monkeypatch):
    import services.capability_registry as registry

    monkeypatch.setattr(registry.shutil, "which", lambda command: None)
    result = registry.build_registry()
    assert result["schema_version"] == "1.0"
    assert set(result["capabilities"]) == set(registry.CAPABILITIES)
    assert result["capabilities"]["python"]["status"] == "blocked"
    with pytest.raises(RuntimeError, match="CAPABILITY_BLOCKED:python"):
        registry.require(result, "python")


def test_registry_available_entry_has_path_version_and_hash(monkeypatch, tmp_path):
    import services.capability_registry as registry

    executable = tmp_path / "fake-tool.exe"
    executable.write_bytes(b"tool")
    monkeypatch.setattr(registry, "CAPABILITIES", {"python": "python"})
    monkeypatch.setattr(registry.shutil, "which", lambda command: str(executable))
    monkeypatch.setattr(registry, "_version", lambda command: "Python 3.test")
    result = registry.build_registry()
    entry = registry.require(result, "python")
    assert entry["status"] == "available" and entry["version"] == "Python 3.test" and entry["hash"]
