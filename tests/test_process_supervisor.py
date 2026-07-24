from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


def test_process_supervisor_rejects_escape_and_dangerous_flag(tmp_path):
    from services.process_supervisor import ProcessSupervisor

    supervisor = ProcessSupervisor(tmp_path, {"python"})
    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(supervisor.run("bad", ["python", "-c", "print(1)"], tmp_path.parent))
    with pytest.raises(ValueError, match="Dangerous"):
        asyncio.run(supervisor.run("bad", ["python", "--dangerously-skip-permissions"], tmp_path))


def test_process_supervisor_success_and_timeout(tmp_path):
    from services.process_supervisor import ProcessSupervisor

    supervisor = ProcessSupervisor(tmp_path, {Path(sys.executable).name})
    success = asyncio.run(supervisor.run("ok", [sys.executable, "-c", "print('ok')"], tmp_path))
    assert success["returncode"] == 0 and success["stdout"].strip() == "ok"
    timed_out = asyncio.run(supervisor.run("slow", [sys.executable, "-c", "import time; time.sleep(2)"], tmp_path, timeout=0.05))
    assert timed_out["returncode"] == -1 and "timed out" in timed_out["stderr"]
