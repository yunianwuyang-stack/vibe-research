from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


async def setup(tmp_path: Path, monkeypatch, script: str):
    import services.agent_bundle as bundle
    import services.agent_tasks as tasks
    import services.research_contracts as contracts
    import services.state_store as store

    store.DB_PATH = tmp_path / "vibe.db"
    tasks.WORKSPACES_DIR = tmp_path / "workspaces"
    executable = tmp_path / "agent.exe"
    executable.write_text("placeholder")
    wrapper = tmp_path / "agent.py"
    wrapper.write_text(script, encoding="utf-8")
    monkeypatch.setattr(tasks, "build_adapter_manifest", lambda **_kwargs: {"adapters": {"codex": {"status": "available", "executable": sys.executable}}})
    monkeypatch.setattr(tasks, "_command", lambda adapter, executable, workspace: [sys.executable, str(wrapper)])
    monkeypatch.setattr(tasks, "_structured_output", lambda adapter, stdout: ([{"type":"result","payload":{}}], stdout.strip(), {"output_tokens":1}))
    await store.init_db()
    project = await contracts.create_contract("Agent", "Summarize evidence", "read-only task")
    return tasks, project["id"]


async def wait_terminal(tasks, task_id: str):
    for _ in range(100):
        value = await tasks._read(task_id)
        if value["status"] not in {"queued", "running", "cancelling"}:
            return value
        await asyncio.sleep(.03)
    raise AssertionError("Agent task did not finish")


def test_agent_task_persists_redacted_audit_and_recovers(tmp_path, monkeypatch):
    async def go():
        script = "import json;print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'token=secret answer'}}));print(json.dumps({'type':'turn.completed','usage':{'output_tokens':1}}))"
        tasks, project_id = await setup(tmp_path, monkeypatch, script)
        started = await tasks.start(project_id, "codex", "summarize")
        completed = await wait_terminal(tasks, started["id"])
        assert completed["status"] == "completed" and "[REDACTED]" in completed["result"]["stdout"]
        assert completed["result"]["final_text"] and Path(completed["result"]["artifact_path"]).is_file()
        assert len(completed["result"]["artifact_sha256"]) == 64
        audit = json.loads(Path(completed["audit_path"]).read_text(encoding="utf-8"))
        assert [event["event"] for event in audit["events"]] == ["started", "completed"]
        assert (await tasks.list_tasks(project_id))[0]["id"] == completed["id"]
        await tasks.recover_interrupted()
        assert (await tasks._read(completed["id"]))["status"] == "completed"
    asyncio.run(go())


def test_agent_task_can_cancel_and_retry(tmp_path, monkeypatch):
    async def go():
        tasks, project_id = await setup(tmp_path, monkeypatch, "import time,sys;time.sleep(10);print(sys.argv[-1])")
        started = await tasks.start(project_id, "codex", "long task", timeout=20)
        for _ in range(50):
            if (await tasks._read(started["id"]))["status"] == "running": break
            await asyncio.sleep(.02)
        cancelled = await tasks.cancel(started["id"])
        assert cancelled["status"] == "cancelled"
        retried = await tasks.retry(started["id"])
        assert retried["retry_of"] == started["id"] and retried["status"] in {"queued", "running"}
        await tasks.cancel(retried["id"])
    asyncio.run(go())


def test_agent_unavailable_and_restart_are_explicit(tmp_path, monkeypatch):
    async def go():
        tasks, project_id = await setup(tmp_path, monkeypatch, "print('ok')")
        monkeypatch.setattr(tasks, "build_adapter_manifest", lambda **_kwargs: {"adapters": {"codex": {"status": "unavailable", "action": {"kind": "official_login"}}}})
        with pytest.raises(HTTPException) as error:
            await tasks.start(project_id, "codex", "task")
        assert error.value.status_code == 503
        db = await tasks.get_db()
        try:
            await db.execute("INSERT INTO agent_tasks (id,project_id,adapter,prompt,status,workspace_path) VALUES (?,?,?,?,?,?)", ("lost", project_id, "codex", "task", "running", str(tmp_path)))
            await db.commit()
        finally: await db.close()
        await tasks.recover_interrupted()
        assert (await tasks._read("lost"))["status"] == "interrupted"
    asyncio.run(go())


def test_official_commands_are_noninteractive_and_never_bypass_permissions(tmp_path):
    from services.agent_tasks import _command
    codex = _command("codex", "codex.cmd", tmp_path)
    claude = _command("claude", "claude.cmd", tmp_path)
    assert "exec" in codex and "--json" in codex and codex[codex.index("--sandbox") + 1] == "read-only"
    assert "--ignore-rules" in codex and not any("dangerously" in value for value in codex)
    assert "--print" in claude and claude[claude.index("--permission-mode") + 1] == "plan"
    assert "--tools=" in claude and not any("dangerously" in value for value in claude)
    mcp_flag = claude.index("--mcp-config")
    mcp_path = Path(claude[mcp_flag + 1])
    assert mcp_path.is_file()
    assert "mcpServers" in mcp_path.read_text(encoding="utf-8")
    assert not claude[mcp_flag + 1].startswith("{")
