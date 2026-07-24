from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


def app_with_guard():
    from services.local_session import DESKTOP_ORIGIN, TOKEN_ENV, TOKEN_HEADER, verify_request
    os.environ[TOKEN_ENV] = "test-local-token"
    app = FastAPI()

    @app.middleware("http")
    async def guard(request, call_next):
        try:
            verify_request(request)
        except Exception as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"ok": True}
    return app, DESKTOP_ORIGIN, TOKEN_HEADER


def test_local_session_rejects_missing_token_and_foreign_origin():
    app, origin, header = app_with_guard()
    client = TestClient(app)
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={header: "test-local-token", "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/health", headers={header: "test-local-token", "Origin": origin}).status_code == 200


def test_source_has_no_wildcard_cors_and_electron_generates_token():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    backend = (root / "backend" / "main.py").read_text(encoding="utf-8")
    electron = (root / "main.js").read_text(encoding="utf-8")
    preload = (root / "preload.js").read_text(encoding="utf-8")
    assert "allow_origins=[\"*\"]" not in backend
    assert "randomBytes(32)" in electron and "VIBE_LOCAL_SESSION_TOKEN" in electron
    assert "localSessionToken" in preload
