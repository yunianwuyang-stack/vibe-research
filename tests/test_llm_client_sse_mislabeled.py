"""Regression: mislabeled text/event-stream JSON must decode as chat.completion."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_decode_mislabeled_event_stream_json_chat_completion():
    from services.llm_client import _decode_api_response, _extract_content, _body_looks_like_sse

    raw = (
        b'{"id":"x","object":"chat.completion","choices":['
        b'{"index":0,"message":{"role":"assistant","content":"Hello"},'
        b'"finish_reason":"stop"}]}'
    )
    assert _body_looks_like_sse(raw) is False
    result = _decode_api_response(raw, "text/event-stream; charset=utf-8")
    assert result["object"] == "chat.completion"
    assert _extract_content(result) == "Hello"


def test_decode_real_sse_responses_still_works():
    from services.llm_client import _decode_api_response, _extract_responses_content, _body_looks_like_sse

    raw = (
        b'data: {"type":"response.completed","response":{'
        b'"object":"response","output":[{"type":"message","role":"assistant",'
        b'"content":[{"type":"output_text","text":"Hi"}]}]}}\n\n'
    )
    assert _body_looks_like_sse(raw) is True
    result = _decode_api_response(raw, "application/json")
    assert _extract_responses_content(result) == "Hi"
