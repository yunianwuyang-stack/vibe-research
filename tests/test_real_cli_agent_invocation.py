"""Real Codex/Claude CLI invocation — never mock success without credentials."""
from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _which_cli(name: str) -> str | None:
    return shutil.which(name)


@pytest.mark.parametrize("adapter", ["codex", "claude"])
def test_real_cli_agent_task_produces_audit_not_fake_success(tmp_path, monkeypatch, adapter):
    executable = _which_cli(adapter)
    if not executable:
        pytest.skip(f"{adapter} CLI not installed on PATH")

    import services.agent_tasks as agent_tasks
    import services.research_contracts as contracts
    import services.state_store as store
    from services.agent_bundle import build_adapter_manifest

    store.DB_PATH = tmp_path / "vibe.db"
    monkeypatch.setattr(agent_tasks, "WORKSPACES_DIR", tmp_path / "workspaces")
    (tmp_path / "workspaces").mkdir(parents=True)

    # Force discovery of the real host CLI rather than a packaged fake.
    monkeypatch.setenv(f"{adapter.upper()}_BIN", executable)
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("VIBE_PACKAGED_RUNTIME", raising=False)

    manifest = build_adapter_manifest(
        configured_overrides={adapter: executable},
    )
    entry = manifest["adapters"].get(adapter) or {}
    if entry.get("status") != "available":
        pytest.skip(f"{adapter} discovered but not available: {entry.get('reason')}")
    assert Path(entry["executable"]).is_file()

    async def go():
        await store.init_db()
        project = await contracts.create_contract(
            f"CLI {adapter}",
            "Does the real local CLI run end-to-end?",
            "local probe only",
        )
        project_id = project["id"]

        task = await agent_tasks.start(
            project_id,
            adapter,
            "Reply with exactly: VIBE_CLI_PROBE",
            timeout=45,
        )
        assert task["status"] in {"queued", "running", "completed", "failed", "cancelled", "interrupted"}
        assert task["adapter"] == adapter
        assert Path(task["workspace_path"]).is_dir()

        deadline = time.time() + 55
        current = task
        while current["status"] in {"queued", "running", "cancelling"} and time.time() < deadline:
            await asyncio.sleep(0.25)
            current = await agent_tasks._read(task["id"])

        # Must terminate. Success requires a real final_text artifact; failure must
        # be honest (no silent mock, no fake completed without audit trail).
        assert current["status"] in {"completed", "failed", "cancelled", "interrupted"}, current
        assert current["status"] != "queued"
        command = current.get("command") or []
        assert command and command[0], current
        assert Path(command[0]).is_file() or shutil.which(str(command[0]))

        if current["status"] == "completed":
            result = current.get("result") or {}
            assert result.get("final_text"), "completed CLI task must carry final_text"
            assert result.get("artifact_sha256") and len(result["artifact_sha256"]) == 64
            artifact = Path(result.get("artifact_path") or (Path(current["workspace_path"]) / "agent-response.txt"))
            assert artifact.is_file()
            assert artifact.read_text(encoding="utf-8").strip()
        else:
            # Honest failure path: process was attempted and a reason is recorded.
            assert current.get("failure_reason") or (current.get("result") or {}).get("stderr") is not None
            audit = Path(current.get("audit_path") or "")
            if audit and audit.is_file():
                text = audit.read_text(encoding="utf-8")
                assert "returncode" in text or adapter in text

    asyncio.run(go())
