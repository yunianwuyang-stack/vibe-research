"""Deterministic local OpenAI/Anthropic-compatible relay used by integration tests."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    server_version = "VibeMockRelay/1.0"

    def log_message(self, fmt, *args):
        return

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, payload: dict) -> None:
        log_path = os.environ.get("MOCK_RELAY_LOG", "")
        if not log_path:
            return
        record = {
            "method": self.command,
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "payload": payload,
        }
        with Path(log_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _anthropic_messages(self, payload: dict) -> None:
        text = "BUNDLED_CLAUDE_RELAY_OK"
        message_id = "msg_mock_bundled_cli"
        if not payload.get("stream", False):
            self._json(200, {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": str(payload.get("model", "mock-claude")),
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            })
            return

        events = [
            ("message_start", {"type": "message_start", "message": {
                "id": message_id, "type": "message", "role": "assistant",
                "model": str(payload.get("model", "mock-claude")), "content": [],
                "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            }}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta", "text": text}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {
                "stop_reason": "end_turn", "stop_sequence": None,
            }, "usage": {"output_tokens": 5}}),
            ("message_stop", {"type": "message_stop"}),
        ]
        body = "".join(
            f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            for event, data in events
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"error": {"message": "invalid json"}})
            return

        self._record(payload)
        if "/messages" in self.path:
            self._anthropic_messages(payload)
            return

        model = str(payload.get("model", ""))
        if model == "mock-http-error":
            self._json(503, {"error": {"message": "simulated relay failure"}})
            return
        if model == "mock-malformed":
            self._json(200, {"unexpected": True})
            return
        if model == "mock-timeout":
            time.sleep(2.0)
            self._json(200, {"choices": [{"message": {"content": "TOO_LATE"}}]})
            return

        messages = payload.get("messages") or []
        content = messages[-1].get("content") if messages else ""
        if isinstance(content, list):
            image_blocks = [part for part in content if isinstance(part, dict) and part.get("type") == "image_url"]
            text = next((part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"), "")
            reply = f"VISION_OK blocks={len(image_blocks)} context={text[-80:]}"
        else:
            reply = f"TEXT_OK prompt={str(content)[-80:]}"
        self._json(200, {"id": "mock-chat", "choices": [{"message": {"role": "assistant", "content": reply}}]})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
