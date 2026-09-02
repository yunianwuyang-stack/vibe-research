"""Regression tests for the failure-class-aware step retry policy.

Bug context: workflow fb4f4e5b7272 comp-paper-zh burned its whole 8-attempt
budget in ~9 minutes against a multi-wave upstream relay outage (HTTP 504 /
upstream_unavailable / DNS getaddrinfo), because the retry loop had no
backoff and treated infrastructure failures the same as deterministic ones.
The fix classifies failures: transient ones get a long time-boxed window with
exponential backoff; permanent ones (sandbox denials, payload limits, auth,
content gates) still fail fast to avoid futile token burn.
"""
from __future__ import annotations

import pytest

from services.workflow_engine import (
    _classify_step_error,
    _transient_backoff_s,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "API 返回 HTTP 504: ",
        "API 返回 HTTP 502 upstream_unavailable",
        # The a6api relay's 400 body still carries upstream_unavailable.
        'API 返回 HTTP 400: {"error":{"code":"upstream_unavailable"}}',
        "OpenAI Responses stream failed: {\"code\": \"upstream_unavailable\"}",
        "[Errno 11001] getaddrinfo failed",
        "API 返回 HTTP 429: rate limited",
        "[WinError 10060] 连接尝试失败",
        "Connection reset by peer",
        "Remote end closed connection without response",
    ],
)
def test_transient_failures_are_classified_transient(text: str) -> None:
    assert _classify_step_error(text) == "transient"


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "ValueError: command not allowlisted: wc",
        "WorkspaceBoundaryError: path escapes workspace",
        "CAPABILITY_BLOCKED:shared-scripts:mount_failed:could not remove",
        # Payload-limit rejections will fail identically on every retry, so
        # they must NOT enter the patient transient path — even when the HTTP
        # status itself looks transient (502 + payload_limit happened for real).
        "API 返回 HTTP 502 upstream_unavailable (smart_route payload_limit)",
        "API 返回 HTTP 401: invalid api key",
        "interpreter inline and module execution are not allowlisted",
    ],
)
def test_permanent_failures_are_classified_permanent(text: str) -> None:
    assert _classify_step_error(text) == "permanent"


@pytest.mark.unit
def test_unknown_and_empty_fail_closed_to_unknown() -> None:
    assert _classify_step_error("") == "unknown"
    assert _classify_step_error("   ") == "unknown"
    assert _classify_step_error("step produced no primary_output") == "unknown"


@pytest.mark.unit
def test_transient_backoff_is_flat_20s() -> None:
    # Flat delay (not exponential): the failed attempt itself already spends
    # ~60s waiting on the hung upstream, so the sleep is not the pacing
    # bottleneck — a short predictable delay resumes work as soon as the
    # relay recovers.
    for n in (1, 2, 5, 24, 120):
        assert _transient_backoff_s(n) == 20.0
