import os
import subprocess
import sys
import time
from pathlib import Path

from harness.v2.scripts.p0_bootstrap import run_supervised


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        probe = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in probe.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_supervisor_times_out_and_kills_child_process_tree(tmp_path: Path) -> None:
    child_pid = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time,pathlib; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid), encoding='utf-8'); "
        "time.sleep(30)"
    )

    result = run_supervised(
        [sys.executable, "-c", code],
        tmp_path,
        deadline_seconds=0.4,
        heartbeat_path=tmp_path / "heartbeat.json",
    )

    assert result["timed_out"] is True
    assert "taskkill /T /F" in result["cleanup"]["actions"] if os.name == "nt" else result["cleanup"]["actions"]
    assert child_pid.exists(), "the fixture must prove that a real child process was started"
    pid = int(child_pid.read_text(encoding="utf-8"))
    for _ in range(20):
        if not _pid_is_alive(pid):
            break
        time.sleep(0.1)
    assert not _pid_is_alive(pid), f"orphaned child process remains alive: {pid}"
