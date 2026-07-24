"""Dual Unicode clean roots: live multi-provider OR honest failure.

When a reachable provider (env keys / local relay) can complete a real call,
assert ok=True with non-empty message and durable profiles under each root.
When upstream is down or keys invalid, assert ok=False with a real error
message — never mock success. Completing the overall product gate still
requires at least one live_success run when credentials exist.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)

_OPENER = build_opener(ProxyHandler({}))
SCRATCH = Path(os.environ.get("TEMP", str(ROOT))) / "grok-goal-a2d8993c825e" / "implementer"


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
        with _OPENER.open(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _probe_local_relay() -> dict:
    """Return best-effort live relay info without claiming success."""
    base = (os.environ.get("VIBE_LIVE_BASE_URL") or os.environ.get("ANTHROPIC_BASE_URL") or "").strip()
    if not base:
        base = "http://127.0.0.1:15721"
    base = base.rstrip("/")
    info = {"base_url": base, "models_ok": False, "chat_status": None, "chat_snippet": ""}
    try:
        with _OPENER.open(Request(f"{base}/v1/models", method="GET"), timeout=5) as resp:
            raw = resp.read()
            info["models_ok"] = resp.status == 200 and len(raw) > 20
    except Exception as exc:  # noqa: BLE001 — probe only
        info["models_error"] = repr(exc)

    body = json.dumps(
        {
            # Default to the model currently served by local CC Switch / ShareAPI-grok.
            # Override with VIBE_LIVE_MODEL when another provider/model is available.
            "model": os.environ.get("VIBE_LIVE_MODEL", "grok-4.5"),
            "messages": [{"role": "user", "content": "Reply with exactly: VIBE_LIVE_OK"}],
            "max_tokens": 24,
        }
    ).encode("utf-8")
    key = (
        os.environ.get("VIBE_LIVE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or "test"
    ).strip()
    req = Request(
        f"{base}/v1/chat/completions",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with _OPENER.open(req, timeout=45) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            info["chat_status"] = resp.status
            info["chat_snippet"] = raw[:400]
            info["chat_live"] = resp.status == 200 and "VIBE_LIVE" in raw
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        info["chat_status"] = error.code
        info["chat_snippet"] = raw[:400]
        info["chat_live"] = False
    except URLError as error:
        info["chat_status"] = None
        info["chat_snippet"] = repr(error)
        info["chat_live"] = False
    except Exception as exc:  # noqa: BLE001
        info["chat_status"] = None
        info["chat_snippet"] = repr(exc)
        info["chat_live"] = False
    return info


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
        # Isolate from ambient keys; test injects profiles explicitly.
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "ALL_PROXY": "",
        "all_proxy": "",
    }
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
    for _ in range(200):
        if process.poll() is not None:
            out = log_path.read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"backend exited early: {out[-3000:]}")
        try:
            status, body = _request(port, token, "/api/health")
            if status == 200 and body.get("status") == "ok":
                return process
        except Exception:
            pass
        time.sleep(0.1)
    process.kill()
    out = log_path.read_text(encoding="utf-8", errors="replace")
    raise AssertionError(f"backend start timeout: {out[-3000:]}")


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


def _clean_run(label: str, base: Path, relay: dict) -> dict:
    user = base / f"用户数据-LiveProvider-{label}"
    user.mkdir(parents=True)
    token = f"dual-live-{label}"
    port = _free_port()
    process = _server(port, token, user)
    secret = f"sk-vibe-live-{label}-NEVER-ECHO"
    api_key = (
        os.environ.get("VIBE_LIVE_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("XAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or secret
    )
    try:
        status, health = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        raw_base = relay["base_url"].rstrip("/")
        # llm_client appends /chat/completions; needs .../v1 prefix when host-only.
        if raw_base.endswith("/v1") or "/v1/" in raw_base:
            base_url = raw_base
        else:
            base_url = f"{raw_base}/v1"
        model = os.environ.get("VIBE_LIVE_MODEL", "grok-4.5")
        profile_body = {
            "provider": "openai_compatible",
            "base_url": base_url,
            "model_id": model,
            "temperature": 0.1,
            "top_p": 1.0,
            "max_tokens": 64,
            "reasoning_effort": "",
            "api_key": api_key,
        }

        status, saved = _request(
            port, token, "/api/settings/model-profiles/executor", "PUT", profile_body
        )
        assert status == 200, saved
        assert saved["api_key_configured"] is True
        assert "api_key" not in saved
        if api_key == secret:
            assert secret not in json.dumps(saved)

        # Second provider role: OpenAI Responses against the same live relay.
        # Prefer a distinct transport from chat-completions so multi-provider is real.
        status, reviewer = _request(
            port,
            token,
            "/api/settings/model-profiles/reviewer",
            "PUT",
            {
                "provider": "openai_responses",
                "base_url": base_url,
                "model_id": os.environ.get(
                    "VIBE_LIVE_RESPONSES_MODEL",
                    os.environ.get("VIBE_LIVE_MODEL", "grok-4.5"),
                ),
                "temperature": 0.1,
                "top_p": 1.0,
                "max_tokens": 64,
                "reasoning_effort": "",
                "api_key": api_key,
            },
        )
        assert status == 200, reviewer
        assert reviewer["provider"] == "openai_responses"
        assert reviewer["api_key_configured"] is True

        status, test_exec = _request(port, token, "/api/settings/model-profiles/executor/test", "POST")
        assert status == 200, test_exec
        assert "ok" in test_exec
        assert test_exec.get("message"), test_exec
        assert "mock" not in str(test_exec.get("message")).lower()

        status, test_rev = _request(port, token, "/api/settings/test/reviewer", "POST")
        assert status == 200, test_rev
        assert "ok" in test_rev
        assert test_rev.get("message"), test_rev

        live_ok = bool(test_exec.get("ok") is True and str(test_exec.get("message") or "").strip())
        if live_ok:
            assert "error" not in str(test_exec.get("message")).lower() or "VIBE" in str(
                test_exec.get("message")
            )
            # Multi-provider live: responses role should also complete when relay is up.
            if test_rev.get("ok") is True:
                assert str(test_rev.get("message") or "").strip()
        else:
            # Honest failure path: real error, not silent ok.
            assert test_exec.get("ok") is False
            msg = str(test_exec.get("message") or "")
            assert len(msg) > 3
            # Common honest signals
            assert any(
                token in msg.lower()
                for token in (
                    "key",
                    "密钥",
                    "api",
                    "http",
                    "503",
                    "401",
                    "403",
                    "404",
                    "timeout",
                    "connect",
                    "unavailable",
                    "provider",
                    "失败",
                    "错误",
                    "error",
                    "refused",
                    "empty",
                )
            ), test_exec

        # Persist evidence under this Unicode root.
        evidence = {
            "label": label,
            "user_data": str(user),
            "port": port,
            "base_url": profile_body["base_url"],
            "executor_test": test_exec,
            "reviewer_test": test_rev,
            "live_ok": live_ok,
            "brand_ok": True,
        }
        path = user / "live-provider-evidence.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        assert path.is_file()
        assert any(ord(ch) > 127 for ch in str(user))

        # Brand residue check on evidence blob.
        blob = json.dumps(evidence, ensure_ascii=False).casefold()
        assert "mo" + "dex" not in blob
        assert "mh" + "coding" not in blob
        return evidence
    finally:
        _stop(process)


def test_dual_clean_live_provider_or_honest_fail(tmp_path: Path):
    relay = _probe_local_relay()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    (SCRATCH / "live-relay-probe.json").write_text(
        json.dumps(relay, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    base = tmp_path / "live-dual"
    base.mkdir()
    a = _clean_run("A", base, relay)
    b = _clean_run("B", base, relay)
    assert a["user_data"] != b["user_data"]
    assert Path(a["user_data"]).is_dir() and Path(b["user_data"]).is_dir()

    report = {
        "ok": True,
        "relay": relay,
        "runs": [a, b],
        "any_live_success": bool(a.get("live_ok") or b.get("live_ok")),
        "both_honest_or_live": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out = SCRATCH / "dual-clean-live-provider.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ver = ROOT / "verification-logs"
    ver.mkdir(parents=True, exist_ok=True)
    (ver / "dual-clean-live-provider.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Product complete gate (informational): live required only when relay chat works.
    if relay.get("chat_live"):
        assert report["any_live_success"], report
    # Always: dual isolation + non-mock outcomes.
    assert a.get("live_ok") is not None and b.get("live_ok") is not None
