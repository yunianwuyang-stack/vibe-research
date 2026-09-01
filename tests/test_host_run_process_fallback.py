"""Regression tests for _HostStepRunner._run_process.

Bug: workflow fb4f4e5b7272 paper-figure recovery failed in <200ms with an
empty error message.  Root cause: the backend was served by
``uvicorn --reload`` which forces a SelectorEventLoop on Windows
(uvicorn >= 0.36 loop_factory, bypassing asyncio.set_event_loop_policy).
SelectorEventLoop cannot spawn subprocesses, so every
``asyncio.create_subprocess_exec`` raises a bare ``NotImplementedError``.
``_run_process`` retried once without creationflags and then let the second
exception propagate through ``_probe_figure_execution_channel`` — which was
designed to warn, not kill — turning every recovery into an instant failure.

These tests simulate that environment by making ``create_subprocess_exec``
always raise a bare ``NotImplementedError`` and assert the synchronous
``subprocess.run`` fallback keeps the host step channel alive.
"""
from __future__ import annotations

import asyncio
import sys

import pytest


def _install_broken_asyncio_subprocess(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Make every asyncio.create_subprocess_exec raise bare NotImplementedError,
    exactly like a SelectorEventLoop does (asyncio/base_events.py:533)."""
    calls = {"n": 0}

    async def _boom(*args, **kwargs):
        calls["n"] += 1
        raise NotImplementedError  # bare, no message — the real-world signature

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _boom)
    return calls


@pytest.mark.unit
def test_run_process_sync_fallback_when_loop_cannot_spawn(tmp_path, monkeypatch):
    from services.workflow_engine import _HostStepRunner

    calls = _install_broken_asyncio_subprocess(monkeypatch)

    async def go():
        return await _HostStepRunner._run_process(
            [sys.executable, "-c", "print('ok-sync-fallback')"],
            tmp_path,
            timeout=30.0,
        )

    rc, stdout, stderr = asyncio.run(go())
    # Both async attempts (with and without creationflags) must have been tried
    # before giving up on the asyncio channel.
    assert calls["n"] == 2
    assert rc == 0, f"expected sync fallback to succeed, got rc={rc} stderr={stderr!r}"
    assert "ok-sync-fallback" in stdout


@pytest.mark.unit
def test_run_process_sync_fallback_propagates_nonzero_rc(tmp_path, monkeypatch):
    from services.workflow_engine import _HostStepRunner

    _install_broken_asyncio_subprocess(monkeypatch)

    async def go():
        return await _HostStepRunner._run_process(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            tmp_path,
            timeout=30.0,
        )

    rc, stdout, stderr = asyncio.run(go())
    assert rc == 3
    assert "boom" in stderr


@pytest.mark.unit
def test_run_process_sync_fallback_timeout_returns_124(tmp_path, monkeypatch):
    from services.workflow_engine import _HostStepRunner

    _install_broken_asyncio_subprocess(monkeypatch)

    async def go():
        return await _HostStepRunner._run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            timeout=1.0,
        )

    rc, stdout, stderr = asyncio.run(go())
    assert rc == 124
    assert "timed out" in stderr
