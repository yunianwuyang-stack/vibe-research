"""Loopback session token and strict desktop Origin policy."""
from __future__ import annotations

import hmac
import os
import secrets

from fastapi import HTTPException, Request, WebSocket

TOKEN_ENV = "VIBE_LOCAL_SESSION_TOKEN"
TOKEN_HEADER = "X-Vibe-Session-Token"
DESKTOP_ORIGIN = "app://vibe-research"


def desktop_origin() -> str:
    """Return the one renderer origin authorised for this desktop launch.

    The packaged desktop shell serves the SPA from its loopback FastAPI
    server.  Its browser therefore sends ``http://127.0.0.1:<port>`` as the
    Origin, rather than the custom-app origin used by early development
    builds.  Electron provides this value at launch; retaining a fixed,
    per-launch allow-list keeps the loopback API private without rejecting
    every real renderer request.
    """
    return os.environ.get("VIBE_DESKTOP_ORIGIN", DESKTOP_ORIGIN)


def session_token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        token = secrets.token_urlsafe(32)
        os.environ[TOKEN_ENV] = token
    return token


def verify_request(request: Request) -> None:
    if not hmac.compare_digest(request.headers.get(TOKEN_HEADER, ""), session_token()):
        raise HTTPException(status_code=401, detail="local_session_required")
    origin = request.headers.get("origin")
    if origin and origin != desktop_origin():
        raise HTTPException(status_code=403, detail="origin_not_allowed")


async def verify_websocket(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    token = ws.query_params.get("session_token", "")
    if origin != desktop_origin() or not hmac.compare_digest(token, session_token()):
        await ws.close(code=1008)
        return False
    return True
