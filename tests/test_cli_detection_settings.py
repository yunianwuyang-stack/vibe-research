"""Codex/Claude CLI detection and durable settings form a real UI→API loop."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Full-suite collection may import test_backend first, which sets VIBE_DESKTOP=1.
# Desktop mode enforces the loopback session boundary; keep a fixed token so this
# contract still exercises the real settings router under either layout.
CLI_SESSION_TOKEN = "cli-detect-session-token"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import services.state_store as store
    import services.secret_store as secrets
    from services.local_session import TOKEN_ENV, TOKEN_HEADER

    store.DB_PATH = tmp_path / "cli-detect.db"
    secrets._STORE = None  # type: ignore[attr-defined]
    monkeypatch.setenv("VIBE_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setenv(TOKEN_ENV, CLI_SESSION_TOKEN)
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.delenv("VIBE_PACKAGED_RUNTIME", raising=False)
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)

    import asyncio
    from main import app

    asyncio.run(store.init_db())
    client = TestClient(app)
    client.headers.update({TOKEN_HEADER: CLI_SESSION_TOKEN})
    return client


def _fake_cli(tmp_path: Path, name: str) -> Path:
    path = tmp_path / f"{name}.exe"
    path.write_text("@echo off\r\n", encoding="utf-8")
    return path


def test_detect_claude_and_codex_respect_settings_env_and_path(client, tmp_path, monkeypatch):
    import services.state_store as store
    import asyncio

    # Neither CLI is discoverable initially.
    monkeypatch.setattr("routers.settings.shutil.which", lambda command: None)
    missing_claude = client.get("/api/settings/detect-claude").json()
    missing_codex = client.get("/api/settings/detect-codex").json()
    assert missing_claude == {"detected": False, "path": None, "source": None}
    assert missing_codex == {"detected": False, "path": None, "source": None}

    claude = _fake_cli(tmp_path, "claude")
    codex = _fake_cli(tmp_path, "codex")

    # Settings take precedence once persisted.
    asyncio.run(store.save_settings({"claude_bin": str(claude), "codex_bin": str(codex)}))
    saved_claude = client.get("/api/settings/detect-claude").json()
    saved_codex = client.get("/api/settings/detect-codex").json()
    assert saved_claude["detected"] is True
    assert saved_claude["source"] == "settings"
    assert Path(saved_claude["path"]) == claude.resolve()
    assert saved_codex["detected"] is True
    assert saved_codex["source"] == "settings"
    assert Path(saved_codex["path"]) == codex.resolve()

    # Environment overrides are used when no durable setting exists.
    asyncio.run(store.save_settings({"claude_bin": "", "codex_bin": ""}))
    monkeypatch.setenv("CLAUDE_BIN", str(claude))
    monkeypatch.setenv("CODEX_BIN", str(codex))
    env_claude = client.get("/api/settings/detect-claude").json()
    env_codex = client.get("/api/settings/detect-codex").json()
    assert env_claude["detected"] is True and env_claude["source"] == "environment"
    assert Path(env_claude["path"]).resolve() == claude.resolve()
    assert env_codex["detected"] is True and env_codex["source"] == "environment"
    assert Path(env_codex["path"]).resolve() == codex.resolve()

    # PATH discovery is the last fallback.
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.delenv("CODEX_BIN", raising=False)

    def which(command: str):
        if command == "claude":
            return str(claude)
        if command == "codex":
            return str(codex)
        return None

    monkeypatch.setattr("routers.settings.shutil.which", which)
    path_claude = client.get("/api/settings/detect-claude").json()
    path_codex = client.get("/api/settings/detect-codex").json()
    assert path_claude["detected"] is True and path_claude["source"] == "path"
    assert path_codex["detected"] is True and path_codex["source"] == "path"


def test_settings_persist_codex_bin_and_feed_agent_manifest(client, tmp_path, monkeypatch):
    import services.agent_bundle as bundle

    codex = _fake_cli(tmp_path, "codex")
    claude = _fake_cli(tmp_path, "claude")

    # Avoid packaged runtime so the override path is the one under test.
    monkeypatch.setattr(bundle, "_default_runtime_root", lambda: None)
    monkeypatch.setattr(bundle, "_version", lambda executable: "test-1.0" if executable else None)
    monkeypatch.setattr("services.agent_bundle.shutil.which", lambda command: None)

    put = client.put(
        "/api/settings",
        json={"settings": {"codex_bin": str(codex), "claude_bin": str(claude)}},
    )
    assert put.status_code == 200
    assert put.json()["ok"] is True

    metadata = client.get("/api/settings").json()
    assert metadata["codex_bin"]["value"] == str(codex)
    assert metadata["claude_bin"]["value"] == str(claude)
    # Secrets stay secret; CLI paths are not secret values.
    assert "api_key" not in str(metadata).lower() or "configured" in str(metadata)

    manifest = client.get("/api/agents/manifest").json()
    assert manifest["schema_version"] == "2.0"
    assert manifest["adapters"]["codex"]["status"] == "available"
    assert Path(manifest["adapters"]["codex"]["executable"]).resolve() == codex.resolve()
    assert manifest["adapters"]["claude"]["status"] == "available"
    assert Path(manifest["adapters"]["claude"]["executable"]).resolve() == claude.resolve()


def test_frontend_settings_surface_exposes_codex_detection_loop():
    source = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    assert "/api/settings/detect-codex" in source
    assert "codex_bin" in source
    assert "detectCodex" in source
    assert "Codex CLI" in source
    assert "/api/settings/detect-claude" in source
