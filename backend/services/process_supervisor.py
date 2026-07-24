"""Bounded subprocess execution for local research workspaces."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from pathlib import Path
from typing import IO, Mapping


class ProcessSupervisor:
    def __init__(self, workspace: Path, allowed_commands: set[str] | None = None):
        self.workspace = workspace.resolve()
        self.allowed_commands = allowed_commands or {"python", "python3", "node"}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _validate(self, command: list[str], cwd: Path) -> None:
        if not command or any(not isinstance(item, str) or "\x00" in item for item in command):
            raise ValueError("Command must be a non-empty list of safe strings")
        executable_name = Path(command[0]).name
        allowed = (
            {item.casefold() for item in self.allowed_commands}
            if os.name == "nt"
            else set(self.allowed_commands)
        )
        candidate = executable_name.casefold() if os.name == "nt" else executable_name
        if candidate not in allowed:
            raise ValueError("Command is not allowlisted")
        if "--dangerously-skip-permissions" in command:
            raise ValueError("Dangerous permission bypass is forbidden")
        try:
            resolved_cwd = cwd.resolve()
            resolved_cwd.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("Working directory escapes workspace") from exc
        if not resolved_cwd.is_dir():
            raise ValueError("Working directory does not exist")

    @staticmethod
    def _subprocess_options() -> dict:
        options: dict = {"start_new_session": os.name != "nt"}
        if os.name == "nt":
            options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        return options

    @staticmethod
    def _spawn_command(command: list[str]) -> list[str]:
        """Expand Windows batch wrappers so create_subprocess_exec can launch them.

        ``CreateProcess`` cannot execute ``.cmd``/``.bat`` directly.  Official
        Codex/Claude Windows shims are batch files, so wrap them with ``cmd.exe``
        after the original executable has already passed the allowlist.
        """
        if os.name != "nt":
            return command
        if Path(command[0]).suffix.lower() not in {".cmd", ".bat"}:
            return command
        return ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]

    async def spawn(
        self,
        task_id: str,
        command: list[str],
        cwd: Path,
        *,
        env: Mapping[str, str] | None = None,
        stdout: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
        stderr: int | IO[bytes] | None = asyncio.subprocess.DEVNULL,
    ) -> asyncio.subprocess.Process:
        """Start a persistent, owned subprocess without invoking a shell.

        Long-running services use this path so cancellation always targets the
        exact child process tree created by this supervisor.  Callers still
        choose from their own fixed command recipes; this method only enforces
        the executable/cwd boundary shared by every subprocess feature.
        """
        self._validate(command, cwd)
        launch_command = self._spawn_command(command)
        existing = self._processes.get(task_id)
        if existing is not None and existing.returncode is None:
            raise ValueError(f"Task is already running: {task_id}")
        self._processes.pop(task_id, None)
        proc = await asyncio.create_subprocess_exec(
            *launch_command,
            cwd=str(cwd.resolve()),
            env=dict(env) if env is not None else None,
            stdout=stdout,
            stderr=stderr,
            **self._subprocess_options(),
        )
        self._processes[task_id] = proc
        return proc

    def get(self, task_id: str) -> asyncio.subprocess.Process | None:
        return self._processes.get(task_id)

    def is_running(self, task_id: str) -> bool:
        proc = self._processes.get(task_id)
        return proc is not None and proc.returncode is None

    def forget(self, task_id: str, *, pid: int | None = None) -> bool:
        """Forget a completed process, optionally guarding against PID reuse."""
        proc = self._processes.get(task_id)
        if proc is None or (pid is not None and proc.pid != pid):
            return False
        if proc.returncode is None:
            return False
        self._processes.pop(task_id, None)
        return True

    async def run(
        self,
        task_id: str,
        command: list[str],
        cwd: Path,
        timeout: float = 60,
        *,
        env: Mapping[str, str] | None = None,
    ) -> dict:
        proc = await self.spawn(
            task_id,
            command,
            cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        communicate_task = asyncio.create_task(proc.communicate())
        try:
            stdout, stderr = await asyncio.wait_for(asyncio.shield(communicate_task), timeout)
            return {"returncode": proc.returncode, "stdout": stdout.decode(errors="replace"), "stderr": stderr.decode(errors="replace")}
        except asyncio.TimeoutError:
            await self.cancel(task_id)
            try:
                stdout, stderr = await asyncio.wait_for(communicate_task, 10)
            except asyncio.TimeoutError:
                communicate_task.cancel()
                await asyncio.gather(communicate_task, return_exceptions=True)
                stdout, stderr = b"", b""
            timeout_message = f"Process timed out after {timeout}s"
            decoded_stderr = stderr.decode(errors="replace")
            return {
                "returncode": -1,
                "stdout": stdout.decode(errors="replace"),
                "stderr": f"{decoded_stderr.rstrip()}\n{timeout_message}".lstrip(),
            }
        except asyncio.CancelledError:
            await self.cancel(task_id)
            await asyncio.gather(communicate_task, return_exceptions=True)
            raise
        finally:
            self._processes.pop(task_id, None)
            if not communicate_task.done():
                communicate_task.cancel()
                await asyncio.gather(communicate_task, return_exceptions=True)
            # asyncio has no public Process.close(); close its transport before
            # short-lived Windows event loops exit so pipe callbacks can settle.
            transport = getattr(proc, "_transport", None)
            if transport is not None:
                transport.close()
                await asyncio.sleep(0)

    async def cancel(self, task_id: str) -> bool:
        proc = self._processes.get(task_id)
        if proc is None:
            return False
        if proc.returncode is None:
            await self.terminate_process_tree(proc.pid, process=proc)
        self._processes.pop(task_id, None)
        return proc.returncode is not None

    async def cancel_all(self) -> list[str]:
        stopped: list[str] = []
        for task_id in list(self._processes):
            if await self.cancel(task_id):
                stopped.append(task_id)
        return stopped

    @staticmethod
    async def terminate_process_tree(
        pid: int,
        *,
        process: asyncio.subprocess.Process | None = None,
        grace_seconds: float = 5,
    ) -> bool:
        """Terminate an owned process group/tree by PID.

        ``process`` is supplied for children still attached to the active
        event loop.  Recovered preview children can omit it after their
        persisted PID/start-time identity has been verified by the caller.
        """
        if pid <= 1 or pid == os.getpid():
            raise ValueError("Refusing to terminate an unsafe process id")
        if os.name == "nt":
            try:
                result = await asyncio.to_thread(
                    subprocess.run,
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=max(5.0, grace_seconds + 2.0),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                taskkill_succeeded = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                taskkill_succeeded = False
            if process is not None:
                try:
                    await asyncio.wait_for(process.wait(), grace_seconds)
                except asyncio.TimeoutError:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
            # taskkill returns 128 when the process already exited.  Both that
            # case and a reaped asyncio child are successful cleanup outcomes.
            return taskkill_succeeded or (process is not None and process.returncode is not None)

        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        if process is not None:
            try:
                await asyncio.wait_for(process.wait(), grace_seconds)
                return True
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(min(grace_seconds, 0.2))
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                return False
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        if process is not None:
            await process.wait()
        return True
