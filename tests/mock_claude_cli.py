"""Small stream-json CLI shim exercising ClaudeRunner's real subprocess path."""
from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    prompt = sys.stdin.read()
    mode = os.environ.get("MOCK_CLAUDE_MODE", "success")
    if mode == "timeout":
        time.sleep(5)
        return 0
    if mode == "error":
        print("simulated cli error", file=sys.stderr, flush=True)
        return 7

    print(json.dumps({"type": "assistant", "text": "STREAM_TEXT", "session_id": "session-mock-1"}), flush=True)
    print(json.dumps({
        "type": "result",
        "result": f"CLI_OK stdin={len(prompt)}",
        "session_id": "session-mock-1",
    }), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
