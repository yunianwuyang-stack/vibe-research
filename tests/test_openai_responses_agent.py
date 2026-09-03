"""Regression tests for OpenAIResponsesAgent request payload hygiene.

Bug: workflow fb4f4e5b7272 comp-paper-zh kept failing with
``400 Unknown parameter: 'input[N].status'`` from the a6api relay (wrapped
as a misleading "upstream_unavailable").  Root cause: ``_continuation_items``
replayed Responses API output items verbatim into the next request's
``input`` — including the server-side ``status`` field that strict
OpenAI-compatible relays reject on input.
"""
from __future__ import annotations

import pytest

from services.openai_responses_agent import OpenAIResponsesAgent


@pytest.mark.unit
def test_continuation_items_strip_status_but_preserve_content() -> None:
    response = {
        "output": [
            {
                "type": "message", "id": "msg_1", "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hello"}],
            },
            {
                "type": "function_call", "id": "fc_1", "status": "completed",
                "call_id": "call_1", "name": "run_command",
                "arguments": '{"command":"python3 x.py"}',
            },
            {
                "type": "reasoning", "id": "rs_1",
                "summary": [{"type": "summary_text", "text": "thinking"}],
            },
        ]
    }
    items = OpenAIResponsesAgent._continuation_items(response)
    assert len(items) == 3
    for item in items:
        assert "status" not in item, "response-only 'status' must be stripped"
    # Everything else survives verbatim.
    assert items[0]["type"] == "message" and items[0]["id"] == "msg_1"
    assert items[0]["content"][0]["text"] == "hello"
    assert items[1]["call_id"] == "call_1" and items[1]["name"] == "run_command"
    assert items[2]["type"] == "reasoning" and items[2]["summary"]


@pytest.mark.unit
def test_continuation_items_tolerate_malformed_output() -> None:
    assert OpenAIResponsesAgent._continuation_items({}) == []
    assert OpenAIResponsesAgent._continuation_items({"output": "nope"}) == []
    # Non-dict entries are skipped, dicts still cleaned.
    items = OpenAIResponsesAgent._continuation_items(
        {"output": ["junk", {"type": "message", "status": "completed"}]}
    )
    assert items == [{"type": "message"}]
