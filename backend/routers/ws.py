"""(docstring)"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.local_session import verify_websocket

log = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """(docstring)"""
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}

    async def connect(self, workflow_id: str, ws: WebSocket):
        await ws.accept()
        if workflow_id not in self.active:
            self.active[workflow_id] = set()
        self.active[workflow_id].add(ws)

    def disconnect(self, workflow_id: str, ws: WebSocket):
        if workflow_id in self.active:
            self.active[workflow_id].discard(ws)
            if not self.active[workflow_id]:
                del self.active[workflow_id]

    async def broadcast(self, workflow_id: str, msg: dict):
        """(docstring)"""
        import json
        # ``/ws/operations`` is the cross-project subscription.  A workflow
        # event is delivered to both its run channel and that global channel.
        for channel in {workflow_id, "operations"}:
            if channel not in self.active:
                continue
            text = json.dumps(msg, ensure_ascii=False)
            dead = []
            for ws in list(self.active[channel]):
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(channel, ws)


manager = ConnectionManager()


@router.websocket("/ws/{workflow_id}")
async def ws_endpoint(ws: WebSocket, workflow_id: str):
    """(docstring)"""
    if not await verify_websocket(ws):
        return
    await manager.connect(workflow_id, ws)
    try:
        while True:
            data = await ws.receive_text()

            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(workflow_id, ws)
