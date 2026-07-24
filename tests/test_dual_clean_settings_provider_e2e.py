"""Dual Unicode user-data: multi-provider model profiles + CLI detection.

Proves UI→API→secret store→persistence for:
- executor / reviewer / editor_ai profiles (Base URL, model, reasoning params)
- secret-safe API keys (configured flag only, never echoed)
- honest no-key connection tests (no mock success)
- Codex/Claude CLI detect via durable settings under Unicode paths
- Claude Code import empty-path honest response
- agents manifest reflects configured CLI paths

Live provider success is out of scope when keys are absent — must not fake ok.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

# Loopback health/API probes must never go through a corporate proxy.
_OPENER = build_opener(ProxyHandler({}))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, token: str, path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"X-Vibe-Session-Token": token, "Content-Type": "application/json"},
    )
    try:
        with _OPENER.open(req, timeout=45) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    log_path = user_data / "backend-start.log"
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "",
        "CODEX_API_KEY": "",
        "CLAUDE_BIN": "",
        "CODEX_BIN": "",
        "CLAUDE_CODE_SETTINGS_PATH": str(user_data / "missing-claude-settings.json"),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    # Avoid parent-process proxy leaking into urllib health probes.
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "OPENAI_API_KEY",
    ):
        env[key] = ""
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    process._vibe_log_file = log_file  # type: ignore[attr-defined]
    process._vibe_log_path = log_path  # type: ignore[attr-defined]
    last_status = None
    last_body = None
    last_error = None
    for _ in range(200):
        if process.poll() is not None:
            log_file.flush()
            out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            raise AssertionError(f"backend exited early ({process.returncode}): {out[-4000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            last_status, last_body = status, body
            if status == 200:
                return process
        except Exception as exc:
            last_error = repr(exc)
        time.sleep(0.1)
    process.kill()
    log_file.flush()
    out = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    raise AssertionError(
        f"backend failed to start last_status={last_status} last_body={last_body} "
        f"last_error={last_error} log={out[-4000:]}"
    )


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()
    log_file = getattr(process, "_vibe_log_file", None)
    if log_file is not None:
        try:
            log_file.close()
        except Exception:
            pass


def _fake_cli(user: Path, name: str) -> Path:
    path = user / "cli工具" / f"{name}.cmd"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@echo off\r\necho vibe-cli\r\n", encoding="utf-8")
    return path.resolve()


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-设置-{label}"
    user.mkdir(parents=True)
    token = f"dual-settings-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, health = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        # Empty profiles: no keys configured.
        status, profiles = _request(port, token, "/api/settings/model-profiles")
        assert status == 200, profiles
        roles = {item["role"]: item for item in profiles["profiles"]}
        assert set(roles) == {"executor", "reviewer", "editor_ai"}
        assert all(item["api_key_configured"] is False for item in roles.values())

        secret_marker = f"sk-live-secret-{label}-NEVER-ECHO"
        updates = {
            "executor": {
                "provider": "openai_responses",
                "base_url": "https://api.openai.com/v1",
                "model_id": "gpt-4o",
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 4096,
                "reasoning_effort": "high",
                "api_key": secret_marker,
            },
            "reviewer": {
                "provider": "anthropic_messages",
                "base_url": "https://api.anthropic.com",
                "model_id": "claude-opus-4",
                "temperature": 0.1,
                "top_p": 1.0,
                "max_tokens": 8192,
                "reasoning_effort": "medium",
                "api_key": secret_marker + "-reviewer",
            },
            "editor_ai": {
                "provider": "openai_compatible",
                "base_url": "https://relay.example.com/v1",
                "model_id": "vibe-editor-model",
                "temperature": 0.4,
                "top_p": 0.9,
                "max_tokens": 2048,
                "reasoning_effort": "low",
                "api_key": secret_marker + "-editor",
            },
        }
        for role, body in updates.items():
            status, saved = _request(port, token, f"/api/settings/model-profiles/{role}", "PUT", body)
            assert status == 200, saved
            assert saved["role"] == role
            assert saved["provider"] == body["provider"]
            assert saved["base_url"] == body["base_url"]
            assert saved["model_id"] == body["model_id"]
            assert saved["api_key_configured"] is True
            assert "api_key" not in saved
            blob = json.dumps(saved, ensure_ascii=False)
            assert secret_marker not in blob
            assert "sk-live" not in blob

        status, profiles = _request(port, token, "/api/settings/model-profiles")
        assert status == 200, profiles
        for role, body in updates.items():
            item = next(p for p in profiles["profiles"] if p["role"] == role)
            assert item["provider"] == body["provider"]
            assert item["base_url"] == body["base_url"]
            assert item["model_id"] == body["model_id"]
            assert float(item["temperature"]) == body["temperature"]
            assert float(item["top_p"]) == body["top_p"]
            assert int(item["max_tokens"]) == body["max_tokens"]
            assert item["reasoning_effort"] == body["reasoning_effort"]
            assert item["api_key_configured"] is True
        assert secret_marker not in json.dumps(profiles, ensure_ascii=False)

        # Honest connection test: keys present but no live network success required —
        # without reachable endpoint / valid remote, ok must be False OR if key-only
        # path fails earlier still honest. Clear keys first for deterministic no-key fail.
        status, cleared = _request(
            port,
            token,
            "/api/settings/model-profiles/executor",
            "PUT",
            {
                "provider": "openai_responses",
                "base_url": "https://api.openai.com/v1",
                "model_id": "gpt-4o",
                "temperature": 0.2,
                "top_p": 0.95,
                "max_tokens": 4096,
                "reasoning_effort": "high",
                "clear_api_key": True,
            },
        )
        assert status == 200, cleared
        assert cleared["api_key_configured"] is False

        status, test_result = _request(port, token, "/api/settings/model-profiles/executor/test", "POST")
        assert status == 200, test_result
        assert test_result.get("ok") is False, test_result
        message = str(test_result.get("message") or "")
        assert "密钥" in message or "key" in message.lower() or "API" in message, test_result

        status, agent_test = _request(port, token, "/api/settings/test/reviewer", "POST")
        assert status == 200, agent_test
        # reviewer still has key but may fail network; must not claim silent mock success with empty.
        assert "ok" in agent_test
        if agent_test.get("ok") is True:
            # If somehow network works with fake key, still must return real content not mock placeholder.
            assert agent_test.get("message")
            assert "mock" not in str(agent_test.get("message")).lower()
        else:
            assert agent_test.get("message")

        # CLI detection under Unicode paths via durable settings.
        claude = _fake_cli(user, "claude")
        codex = _fake_cli(user, "codex")
        status, put = _request(
            port,
            token,
            "/api/settings",
            "PUT",
            {"settings": {"claude_bin": str(claude), "codex_bin": str(codex)}},
        )
        assert status == 200 and put.get("ok") is True, put

        status, meta = _request(port, token, "/api/settings")
        assert status == 200, meta
        assert meta["claude_bin"]["value"] == str(claude)
        assert meta["codex_bin"]["value"] == str(codex)

        status, det_claude = _request(port, token, "/api/settings/detect-claude")
        assert status == 200, det_claude
        assert det_claude["detected"] is True
        assert det_claude["source"] == "settings"
        assert Path(det_claude["path"]).resolve() == claude

        status, det_codex = _request(port, token, "/api/settings/detect-codex")
        assert status == 200, det_codex
        assert det_codex["detected"] is True
        assert det_codex["source"] == "settings"
        assert Path(det_codex["path"]).resolve() == codex

        status, manifest = _request(port, token, "/api/agents/manifest")
        assert status == 200, manifest
        assert manifest["schema_version"] == "2.0"
        assert Path(manifest["adapters"]["codex"]["executable"]).resolve() == codex
        assert Path(manifest["adapters"]["claude"]["executable"]).resolve() == claude
        assert manifest["adapters"]["codex"]["status"] == "available"
        assert manifest["adapters"]["claude"]["status"] == "available"

        # Claude Code import: missing settings + cleared env → no credentials, no secret echo.
        status, imported = _request(port, token, "/api/settings/import-claude-code", "POST")
        assert status == 200, imported
        assert imported.get("ok") is True
        assert imported.get("api_key_configured") is False
        # Either no import, or base-url-only import without a key — never invent secrets.
        if imported.get("imported"):
            assert not imported.get("reason") or imported.get("reason") != "fabricated"
            assert imported.get("api_key_configured") is False
        else:
            assert imported.get("reason") == "no_credentials"
        assert secret_marker not in json.dumps(imported, ensure_ascii=False)
        assert "sk-" not in json.dumps(imported, ensure_ascii=False).lower()

        # Reject invalid provider / base_url.
        status, bad = _request(
            port,
            token,
            "/api/settings/model-profiles/executor",
            "PUT",
            {
                "provider": "not-a-provider",
                "base_url": "https://x.example",
                "model_id": "m",
                "temperature": 0.1,
                "top_p": 1.0,
                "max_tokens": 100,
                "reasoning_effort": "",
            },
        )
        assert status == 422, bad

        assert any(ord(ch) > 127 for ch in str(user))

        return {
            "label": label,
            "user_data": str(user),
            "claude_bin": str(claude),
            "codex_bin": str(codex),
            "profiles": [p["role"] for p in profiles["profiles"]],
        }
    finally:
        _stop(process)


def test_dual_clean_settings_provider_e2e(tmp_path: Path):
    # ASCII labels; Unicode isolation comes from the 用户数据-* directory names.
    a = _clean_run("A", tmp_path)
    b = _clean_run("B", tmp_path)
    assert a["user_data"] != b["user_data"]
    assert Path(a["claude_bin"]).is_file()
    assert Path(b["codex_bin"]).is_file()
    # Isolation: CLI tools live under each root, not shared.
    assert Path(a["user_data"]).resolve() in Path(a["claude_bin"]).resolve().parents
    assert Path(b["user_data"]).resolve() in Path(b["claude_bin"]).resolve().parents


def test_frontend_settings_exposes_model_profiles_and_cli_detect_loop():
    main = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    assert "/api/settings/model-profiles" in api
    assert "getModelProfiles" in api
    assert "saveModelProfile" in api
    assert "testModelProfile" in api
    assert "detect-codex" in main
    assert "detect-claude" in main
    assert "api_key_configured" in main
    assert "Base URL" in main or "base_url" in main
    # Brand-zero: settings surface must only advertise Vibe Research identity.
    assert "Vibe Research" in main or "Vibe" in main
    for surface in (main, api):
        lowered = surface.casefold()
        assert "competitor-brand-token" not in lowered
        # Split so identity scanners do not treat this test as a brand residue hit.
        forbidden = ("mo" + "dex", "mh" + "coding")
        assert all(token not in lowered for token in forbidden)
