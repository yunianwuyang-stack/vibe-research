"""Windows-friendly restricted subprocess adapter for P6 plugins."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class IsolatedRun:
    status: str
    returncode: int
    stdout_path: str
    stderr_path: str
    duration_ms: int
    output_complete: bool


class IsolatedRunner:
    def __init__(self, root: str | Path, *, allowed_executables: set[str] | None = None,
                 max_output_bytes: int = 10_000_000) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allowed_executables = allowed_executables or {"python", "python.exe"}
        self.max_output_bytes = max_output_bytes

    def run(self, command: Sequence[str], *, timeout_seconds: float = 30,
            output_name: str = "plugin-output.json") -> IsolatedRun:
        if not command or Path(command[0]).name.casefold() not in {x.casefold() for x in self.allowed_executables}:
            raise PermissionError("plugin executable is not allowlisted")
        started = time.monotonic()
        stdout_path = self.root / "plugin.stdout"
        stderr_path = self.root / "plugin.stderr"
        output_path = self.root / output_name
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8",
               "VIBE_RESEARCH_SANDBOX": "1"}
        try:
            proc = subprocess.Popen(list(command), cwd=self.root, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    start_new_session=True)
            try:
                stdout, stderr = proc.communicate(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                self._terminate(proc)
                stdout, stderr = proc.communicate()
                status = "timeout"
                code = 124
            else:
                code = int(proc.returncode or 0)
                status = "completed" if code == 0 else "crashed"
        except OSError as exc:
            stdout, stderr, code, status = b"", str(exc).encode(), 127, "crashed"
        stdout = stdout[:self.max_output_bytes]
        stderr = stderr[:self.max_output_bytes]
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        complete = status == "completed" and output_path.is_file() and output_path.stat().st_size > 0
        if status == "completed" and not complete:
            status = "partial_output"
        return IsolatedRun(status, code, str(stdout_path), str(stderr_path),
                           round((time.monotonic() - started) * 1000), complete)

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
