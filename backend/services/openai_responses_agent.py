"""Local-workspace agent loop for OpenAI Responses function tools.

The executor exposes a small, auditable tool surface instead of pretending a
Responses endpoint is Anthropic Messages or launching an incompatible CLI.
"""
from __future__ import annotations

import asyncio
import fnmatch
import inspect
import json
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

log = logging.getLogger(__name__)

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024
MAX_TOOL_OUTPUT_CHARS = 60_000
MAX_COMMAND_OUTPUT_CHARS = 100_000
MAX_RUN_STDOUT_CHARS = 250_000

_ALLOWED_COMMANDS = {"python", "python3", "node", "npm", "npx", "pdflatex", "xelatex", "bibtex", "biber", "pandoc", "git", "pytest", "ruff", "mypy"}
_SECRET_NAME = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|credential|private[_-]?key)")
_SECRET_VALUE = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|(?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s,;]+")
_SAFE_ENV_NAMES = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PYTHONPATH", "NODE_PATH"}

def redact_secrets(value: str, environment: dict[str, str] | None = None) -> str:
    result = str(value or "")
    for name, secret in (environment or {}).items():
        if _SECRET_NAME.search(name) or len(str(secret)) >= 16:
            if secret:
                result = result.replace(str(secret), "[REDACTED]")
    return _SECRET_VALUE.sub("[REDACTED]", result)


class WorkspaceBoundaryError(ValueError):
    """A tool path attempted to leave the workflow workspace."""


class AgentCancelled(RuntimeError):
    """The owner cancelled the tool loop."""


class AgentTimeout(RuntimeError):
    """The tool loop exceeded an activity or wall-clock deadline."""


def _truncate(value: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    marker = f"\n... [truncated {len(value) - limit} characters] ...\n"
    remaining = max(0, limit - len(marker))
    head = remaining * 2 // 3
    return value[:head] + marker + value[-(remaining - head) :]


class _TextCollector:
    def __init__(self, limit: int):
        self.limit = limit
        self.parts: list[str] = []
        self.length = 0
        self.dropped = 0

    def add(self, value: str) -> None:
        if not value:
            return
        remaining = self.limit - self.length
        if remaining <= 0:
            self.dropped += len(value)
            return
        kept = value[:remaining]
        self.parts.append(kept)
        self.length += len(kept)
        self.dropped += len(value) - len(kept)

    def value(self) -> str:
        result = "".join(self.parts)
        if self.dropped:
            result += f"\n... [runner log truncated {self.dropped} characters]"
        return result


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function", "name": "read",
        "description": "Read a UTF-8 text file inside the workflow workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path"},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
            },
            "required": ["path"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "write",
        "description": "Atomically create or overwrite a UTF-8 file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "replace",
        "description": "Replace exact text in one workspace file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}, "old_text": {"type": "string"},
                "new_text": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_text", "new_text"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "list",
        "description": "List files/directories in the workspace, optionally recursively.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": False},
                "pattern": {"type": "string", "default": "*"},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "search",
        "description": "Search text files and return matching path/line snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}, "path": {"type": "string", "default": "."},
                "pattern": {"type": "string", "default": "*"},
                "regex": {"type": "boolean", "default": False},
                "case_sensitive": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["query"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "mkdir",
        "description": "Create a directory and missing parents inside the workspace.",
        "parameters": {
            "type": "object", "properties": {"path": {"type": "string"}},
            "required": ["path"], "additionalProperties": False,
        },
    },
    {
        "type": "function", "name": "run_command",
        "description": (
            "Run a bounded command in the workspace. Prefer command+args without a shell; "
            "set shell=true only for pipelines or shell conditionals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}, "maxItems": 256},
                "cwd": {"type": "string", "default": "."}, "stdin": {"type": "string"},
                "shell": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 900},
            },
            "required": ["command"], "additionalProperties": False,
        },
    },
]


def chat_tool_definitions() -> list[dict[str, Any]]:
    """Translate Responses-style tools into Chat Completions tool schema."""
    tools: list[dict[str, Any]] = []
    for item in TOOL_DEFINITIONS:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "parameters": item.get("parameters") or {"type": "object", "properties": {}},
                },
            }
        )
    return tools


class WorkspaceTools:
    """Constrained file and subprocess capabilities for one workflow workspace."""

    def __init__(
        self, root: str | Path, *,
        on_output: Callable[[str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
        environment: dict[str, str] | None = None,
        max_command_timeout: int = 900,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.on_output = on_output
        self.cancel_event = cancel_event or asyncio.Event()
        source_environment = dict(environment or os.environ)
        self.environment = {key: str(value) for key, value in source_environment.items() if key in _SAFE_ENV_NAMES or key.startswith("SKILL_") or key.startswith("VIBE_")}
        self.max_command_timeout = max(1, min(int(max_command_timeout), 900))
        self._processes: set[asyncio.subprocess.Process] = set()

    def _resolve(self, value: Any, *, must_exist: bool = False) -> Path:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise WorkspaceBoundaryError("path must be a non-empty string")
        requested = Path(value).expanduser()
        candidate = requested if requested.is_absolute() else self.root / requested
        try:
            resolved = candidate.resolve(strict=must_exist)
            resolved.relative_to(self.root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorkspaceBoundaryError(f"path escapes workspace: {value}") from exc
        return resolved

    def _relative(self, path: Path) -> str:
        value = path.relative_to(self.root).as_posix()
        return value or "."

    async def _emit(self, value: str) -> None:
        if not value or self.on_output is None:
            return
        try:
            await self.on_output(_truncate(value, 4000))
        except Exception:
            log.exception("Workspace tool output callback failed")

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if self.cancel_event.is_set():
            raise AgentCancelled("agent cancelled")
        if not isinstance(arguments, dict):
            return json.dumps({"ok": False, "error": "tool arguments must be an object"})
        handlers = {
            "read": self._read, "write": self._write, "replace": self._replace,
            "list": self._list, "search": self._search, "mkdir": self._mkdir,
            "run_command": self._run_command,
        }
        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})
        try:
            result = await handler(arguments)
            result.setdefault("ok", True)
        except AgentCancelled:
            raise
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return _truncate(json.dumps(result, ensure_ascii=False))

    async def _read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("path"), must_exist=True)
        if not path.is_file():
            raise ValueError("read path is not a file")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(f"file exceeds {MAX_FILE_BYTES} byte read limit")
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        start = max(1, int(arguments.get("start_line", 1)))
        end_value = arguments.get("end_line")
        end = len(lines) if end_value is None else max(start, int(end_value))
        selected = "".join(lines[start - 1 : end])
        return {
            "path": self._relative(path), "start_line": start,
            "end_line": min(end, len(lines)), "total_lines": len(lines),
            "content": _truncate(selected),
        }

    async def _write(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"content exceeds {MAX_FILE_BYTES} byte write limit")
        path.parent.mkdir(parents=True, exist_ok=True)
        path = self._resolve(str(path))
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": self._relative(path), "bytes_written": len(data)}

    async def _replace(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("path"), must_exist=True)
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("replace target is not a supported text file")
        old = arguments.get("old_text")
        new = arguments.get("new_text")
        if not isinstance(old, str) or not old:
            raise ValueError("old_text must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError("new_text must be a string")
        text = path.read_text(encoding="utf-8", errors="strict")
        occurrences = text.count(old)
        if occurrences == 0:
            raise ValueError("old_text was not found")
        replace_all = bool(arguments.get("replace_all", False))
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        data = updated.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("replacement result exceeds file size limit")
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "path": self._relative(path),
            "replacements": occurrences if replace_all else 1,
            "remaining_matches": 0 if replace_all else occurrences - 1,
        }

    async def _list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = self._resolve(arguments.get("path", "."), must_exist=True)
        recursive = bool(arguments.get("recursive", False))
        pattern = str(arguments.get("pattern", "*") or "*")
        maximum = max(1, min(int(arguments.get("max_entries", 200)), 1000))
        candidates: Iterable[Path]
        if base.is_file():
            candidates = [base]
        else:
            candidates = base.rglob("*") if recursive else base.iterdir()
        entries: list[dict[str, Any]] = []
        truncated = False
        for candidate in candidates:
            try:
                safe = self._resolve(str(candidate), must_exist=True)
            except WorkspaceBoundaryError:
                continue
            relative_to_base = safe.relative_to(base).as_posix() if safe != base else safe.name
            if not fnmatch.fnmatch(relative_to_base, pattern) and not fnmatch.fnmatch(safe.name, pattern):
                continue
            entries.append({
                "path": self._relative(safe),
                "type": "directory" if safe.is_dir() else "file",
                "size": safe.stat().st_size if safe.is_file() else None,
            })
            if len(entries) >= maximum:
                truncated = True
                break
        entries.sort(key=lambda item: str(item["path"]).lower())
        return {"path": self._relative(base), "entries": entries, "truncated": truncated}

    async def _search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query or len(query) > 1000:
            raise ValueError("query must be 1..1000 characters")
        base = self._resolve(arguments.get("path", "."), must_exist=True)
        pattern = str(arguments.get("pattern", "*") or "*")
        is_regex = bool(arguments.get("regex", False))
        case_sensitive = bool(arguments.get("case_sensitive", False))
        maximum = max(1, min(int(arguments.get("max_results", 100)), 500))
        flags = 0 if case_sensitive else re.IGNORECASE
        matcher = re.compile(query if is_regex else re.escape(query), flags)
        files: Iterable[Path] = [base] if base.is_file() else base.rglob(pattern)
        matches: list[dict[str, Any]] = []
        files_scanned = 0
        for candidate in files:
            if not candidate.is_file():
                continue
            try:
                path = self._resolve(str(candidate), must_exist=True)
                if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                raw = path.read_bytes()
            except (OSError, WorkspaceBoundaryError):
                continue
            if b"\x00" in raw[:4096]:
                continue
            files_scanned += 1
            for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if matcher.search(line):
                    matches.append({
                        "path": self._relative(path), "line": line_number,
                        "text": _truncate(line, 500),
                    })
                    if len(matches) >= maximum:
                        return {"query": query, "matches": matches,
                                "files_scanned": files_scanned, "truncated": True}
        return {"query": query, "matches": matches,
                "files_scanned": files_scanned, "truncated": False}

    async def _mkdir(self, arguments: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve(arguments.get("path"))
        path.mkdir(parents=True, exist_ok=True)
        path = self._resolve(str(path), must_exist=True)
        return {"path": self._relative(path), "created": True}

    def _expand_environment(self, value: str) -> str:
        pattern = re.compile(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|"
            r"\$([A-Za-z_][A-Za-z0-9_]*)|%([A-Za-z_][A-Za-z0-9_]*)%"
        )

        def substitute(match: re.Match[str]) -> str:
            name = match.group(1) or match.group(3) or match.group(4) or ""
            return self.environment.get(name, match.group(2) or "")

        return pattern.sub(substitute, value)

    async def _run_command(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip() or len(command) > 16_384:
            raise ValueError("command must be a non-empty string")
        command = self._expand_environment(command.strip())
        raw_args = arguments.get("args")
        if raw_args is not None and (
            not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args)
        ):
            raise ValueError("args must be an array of strings")
        argv_args = [self._expand_environment(item) for item in (raw_args or [])]
        cwd = self._resolve(arguments.get("cwd", "."), must_exist=True)
        if not cwd.is_dir():
            raise ValueError("command cwd must be a directory")
        timeout = max(1, min(int(arguments.get("timeout_seconds", 120)), self.max_command_timeout))
        use_shell = bool(arguments.get("shell", False))
        stdin_text = arguments.get("stdin", "")
        if not isinstance(stdin_text, str) or len(stdin_text.encode("utf-8")) > 1024 * 1024:
            raise ValueError("stdin must be a string no larger than 1 MiB")

        env = dict(self.environment)
        env["VIBE_WORKSPACE"] = str(self.root)
        env["PWD"] = str(cwd)
        creationflags = 0
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True

        if use_shell:
            shell_text = command
            if argv_args:
                shell_text += " " + " ".join(shlex.quote(item) for item in argv_args)
            if os.name == "nt":
                bash = shutil.which("bash", path=env.get("PATH"))
                powershell = shutil.which("pwsh", path=env.get("PATH")) or shutil.which(
                    "powershell", path=env.get("PATH")
                )
                if bash:
                    argv = [bash, "--noprofile", "--norc", "-lc", shell_text]
                elif powershell:
                    argv = [powershell, "-NoProfile", "-NonInteractive", "-Command", shell_text]
                else:
                    argv = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", shell_text]
            else:
                argv = ["/bin/sh", "-lc", shell_text]
        elif raw_args is not None:
            argv = [command, *argv_args]
        elif Path(command).is_file():
            argv = [command]
        else:
            argv = shlex.split(command, posix=os.name != "nt")
        if not argv:
            raise ValueError("command resolved to an empty argv")
        raw_executable = argv[0]
        if Path(raw_executable).is_absolute() or "/" in raw_executable or "\\" in raw_executable:
            raise ValueError("command path must be a bare allowlisted program name")
        executable_name = Path(argv[0]).name.lower()
        if executable_name.endswith((".cmd", ".bat", ".exe")):
            executable_name = Path(executable_name).stem
        if executable_name not in _ALLOWED_COMMANDS:
            raise ValueError(f"command not allowlisted: {executable_name}")
        if executable_name in {"python", "python3"} and any(
            item in {"-c", "-m", "-"} for item in argv[1:]
        ):
            raise ValueError("interpreter inline and module execution are not allowlisted")
        if use_shell and executable_name not in {"python", "python3", "node", "npm", "npx"}:
            raise ValueError("shell execution is restricted to script runners")
        if os.name == "nt" and Path(argv[0]).suffix.lower() in {".cmd", ".bat"}:
            creationflags &= ~getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, creationflags=creationflags, **kwargs,
        )
        self._processes.add(proc)
        stdout = _TextCollector(MAX_COMMAND_OUTPUT_CHARS)
        stderr = _TextCollector(MAX_COMMAND_OUTPUT_CHARS)

        async def pump(
            stream: asyncio.StreamReader | None, collector: _TextCollector, label: str
        ) -> None:
            if stream is None:
                return
            truncation_reported = False
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    return
                decoded = chunk.decode("utf-8", errors="replace")
                before = collector.length
                collector.add(decoded)
                kept = collector.length - before
                if kept:
                    await self._emit(f"[command {label}] {redact_secrets(decoded[:kept], self.environment)}")
                if collector.dropped and not truncation_reported:
                    truncation_reported = True
                    await self._emit(
                        f"[command {label}] output limit reached; further output suppressed"
                    )

        pumps: list[asyncio.Task[Any]] = []
        wait_task: asyncio.Task[Any] | None = None
        cancel_task: asyncio.Task[Any] | None = None
        timed_out = False
        cancelled = False
        try:
            if proc.stdin is not None:
                if stdin_text:
                    proc.stdin.write(stdin_text.encode("utf-8"))
                    await proc.stdin.drain()
                proc.stdin.close()

            pumps = [
                asyncio.create_task(pump(proc.stdout, stdout, "stdout")),
                asyncio.create_task(pump(proc.stderr, stderr, "stderr")),
            ]
            wait_task = asyncio.create_task(proc.wait())
            cancel_task = asyncio.create_task(self.cancel_event.wait())
            done, _ = await asyncio.wait(
                {wait_task, cancel_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if wait_task not in done:
                cancelled = cancel_task in done and self.cancel_event.is_set()
                timed_out = not cancelled
                await self._terminate(proc)
                if not wait_task.done():
                    wait_task.cancel()
                for task in pumps:
                    if not task.done():
                        task.cancel()
            await asyncio.gather(wait_task, *pumps, return_exceptions=True)
        except asyncio.CancelledError:
            await self._terminate(proc)
            pending = [task for task in ([wait_task] + pumps) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        except BaseException:
            await self._terminate(proc)
            pending = [task for task in ([wait_task] + pumps) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
        finally:
            if cancel_task is not None:
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)
            self._processes.discard(proc)
        if cancelled:
            raise AgentCancelled("command cancelled")
        return {
            "command": argv, "cwd": self._relative(cwd),
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "timed_out": timed_out, "stdout": redact_secrets(stdout.value(), self.environment), "stderr": redact_secrets(stderr.value(), self.environment),
        }

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        if os.name == "nt" and proc.pid:
            try:
                result = await asyncio.to_thread(
                    subprocess.run, ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                tree_kill_failed = result.returncode != 0
            except OSError as exc:
                log.warning("taskkill failed for workspace process %s: %s", proc.pid, exc)
                tree_kill_failed = True
            if tree_kill_failed and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        elif proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except asyncio.TimeoutError:
                log.error("Workspace subprocess %s survived forced termination", proc.pid)

    async def cancel(self) -> None:
        self.cancel_event.set()
        await asyncio.gather(
            *(self._terminate(proc) for proc in list(self._processes)),
            return_exceptions=True,
        )


class OpenAIResponsesAgent:
    """Iterative Responses function-call agent scoped to one local workspace."""

    def __init__(
        self, *, base_url: str, api_key: str, model_id: str,
        parameters: dict[str, Any] | None = None,
        environment: dict[str, str] | None = None,
        request_func: Callable[[dict[str, Any]], Any] | None = None,
        max_turns: int = 80,
    ) -> None:
        self.base_url = base_url
        self._api_key = api_key
        self.model_id = model_id
        self.parameters = dict(parameters or {})
        self.environment = dict(environment or os.environ)
        self.request_func = request_func
        self.max_turns = max(1, min(int(max_turns), 200))
        self._cancel_event = asyncio.Event()
        self._thread_cancel_event = threading.Event()
        self._tools: WorkspaceTools | None = None
        self._last_activity = time.monotonic()
        self._running = False

    def _payload_parameters(self) -> dict[str, Any]:
        from services.llm_client import _responses_parameters

        defaults = {"temperature": 0.3, "top_p": 1.0, "max_tokens": 8192}
        defaults.update(self.parameters)
        return _responses_parameters(defaults)

    async def _call_transport(
        self, payload: dict[str, Any], *, timeout: int,
        on_sse_event: Callable[[dict[str, Any]], None],
    ) -> dict:
        if self.request_func is not None:
            if inspect.iscoroutinefunction(self.request_func):
                result = await self.request_func(payload)
            else:
                result = await asyncio.to_thread(self.request_func, payload)
            if not isinstance(result, dict):
                raise RuntimeError("Responses transport returned a non-object")
            return result

        from services.llm_client import request_openai_response

        return await asyncio.to_thread(
            request_openai_response, self.base_url, self._api_key, payload, timeout,
            on_sse_event=on_sse_event, cancel_event=self._thread_cancel_event,
        )

    async def _request_with_deadlines(
        self, payload: dict[str, Any], *, deadline: float, inactivity_timeout: int,
        emit: Callable[[str], Awaitable[None]],
    ) -> tuple[dict, bool]:
        loop = asyncio.get_running_loop()
        event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def on_sse_event(event: dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(event_queue.put_nowait, event)
            except RuntimeError:
                pass

        remaining = max(1, int(deadline - time.monotonic()))
        request_task = asyncio.create_task(
            self._call_transport(payload, timeout=remaining, on_sse_event=on_sse_event)
        )
        streamed_text = False
        try:
            while not request_task.done():
                while not event_queue.empty():
                    event = event_queue.get_nowait()
                    self._last_activity = time.monotonic()
                    if event.get("type") == "response.output_text.delta" and isinstance(
                        event.get("delta"), str
                    ):
                        streamed_text = True
                        await emit(event["delta"])
                now = time.monotonic()
                if self._cancel_event.is_set():
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentCancelled("agent cancelled")
                if now >= deadline:
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentTimeout("Responses agent exceeded overall timeout")
                if now - self._last_activity >= inactivity_timeout:
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentTimeout(
                        f"Responses agent produced no activity for {inactivity_timeout}s"
                    )
                await asyncio.wait({request_task}, timeout=0.1)
            result = await request_task
            while not event_queue.empty():
                event = event_queue.get_nowait()
                self._last_activity = time.monotonic()
                if event.get("type") == "response.output_text.delta" and isinstance(
                    event.get("delta"), str
                ):
                    streamed_text = True
                    await emit(event["delta"])
            return result, streamed_text
        finally:
            if not request_task.done():
                request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)

    @staticmethod
    def _output_text(response: dict[str, Any]) -> str:
        direct = response.get("output_text")
        if isinstance(direct, str):
            return direct
        pieces: list[str] = []
        output = response.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                    continue
                for part in item["content"]:
                    if (isinstance(part, dict) and part.get("type") == "output_text"
                            and isinstance(part.get("text"), str)):
                        pieces.append(part["text"])
        return "".join(pieces)

    @staticmethod
    def _function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
        output = response.get("output")
        if not isinstance(output, list):
            return []
        return [item for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"]

    @staticmethod
    def _continuation_items(response: dict[str, Any]) -> list[dict[str, Any]]:
        output = response.get("output")
        if not isinstance(output, list):
            return []
        # Reasoning items must be preserved for reasoning models. Messages and
        # function calls are valid input items when copied verbatim.
        return [dict(item) for item in output if isinstance(item, dict)]

    async def run(
        self, *, prompt: str, cwd: str | Path, workflow_id: str,
        on_output: Callable[[str], Awaitable[None]] | None = None,
        inactivity_timeout: int = 2400, overall_timeout: int = 7200,
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        collector = _TextCollector(MAX_RUN_STDOUT_CHARS)
        self._running = True
        deadline = time.monotonic() + max(1, int(overall_timeout))
        self._last_activity = time.monotonic()

        async def emit(value: str) -> None:
            if not value:
                return
            self._last_activity = time.monotonic()
            entry = value + ("" if value.endswith("\n") else "\n")
            before = collector.length
            collector.add(entry)
            kept = collector.length - before
            if on_output and kept:
                try:
                    await on_output(_truncate(entry[:kept].rstrip("\n"), 4000))
                except Exception:
                    log.exception("Responses agent output callback failed")

        conversation: list[dict[str, Any]] = [{
            "role": "user", "content": [{"type": "input_text", "text": prompt}],
        }]
        last_response_id = resume_session_id
        final_text = ""
        try:
            self._tools = WorkspaceTools(
                cwd, on_output=emit, cancel_event=self._cancel_event,
                environment=self.environment,
                max_command_timeout=min(
                    max(1, int(overall_timeout)), max(1, int(inactivity_timeout)), 900
                ),
            )
            await emit(f"[Responses agent] starting workflow {workflow_id}")
            for _turn in range(1, self.max_turns + 1):
                if self._cancel_event.is_set():
                    raise AgentCancelled("agent cancelled")
                payload = {
                    "model": self.model_id, "input": conversation,
                    "tools": TOOL_DEFINITIONS, "tool_choice": "auto",
                    **self._payload_parameters(),
                }
                response, streamed_text = await self._request_with_deadlines(
                    payload, deadline=deadline,
                    inactivity_timeout=max(1, int(inactivity_timeout)), emit=emit,
                )
                if isinstance(response.get("id"), str):
                    last_response_id = response["id"]
                calls = self._function_calls(response)
                text = self._output_text(response)
                if text:
                    final_text = _truncate(text, MAX_RUN_STDOUT_CHARS)
                    if not streamed_text:
                        await emit(final_text)
                if not calls:
                    if not text:
                        raise RuntimeError("Responses model ended without text or a function call")
                    return {
                        "success": True, "stdout": collector.value(), "stderr": "",
                        "returncode": 0, "result": final_text,
                        "session_id": last_response_id,
                    }

                conversation.extend(self._continuation_items(response))
                for call in calls:
                    name = str(call.get("name") or "")
                    call_id = str(call.get("call_id") or call.get("id") or "")
                    raw_arguments = call.get("arguments", "{}")
                    if isinstance(raw_arguments, dict):
                        tool_arguments = raw_arguments
                    elif isinstance(raw_arguments, str):
                        try:
                            value = json.loads(raw_arguments or "{}")
                            tool_arguments = value if isinstance(value, dict) else {}
                        except json.JSONDecodeError as exc:
                            tool_result = json.dumps(
                                {"ok": False, "error": f"invalid tool JSON: {exc}"},
                                ensure_ascii=False,
                            )
                            conversation.append({
                                "type": "function_call_output", "call_id": call_id,
                                "output": tool_result,
                            })
                            continue
                    else:
                        tool_arguments = {}
                    await emit(
                        f"[tool] {name} {json.dumps(tool_arguments, ensure_ascii=False)[:1000]}"
                    )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AgentTimeout("Responses agent exceeded overall timeout")
                    try:
                        tool_result = await asyncio.wait_for(
                            self._tools.execute(name, tool_arguments), timeout=remaining
                        )
                    except asyncio.TimeoutError as exc:
                        raise AgentTimeout(
                            "Responses agent exceeded overall timeout during a tool call"
                        ) from exc
                    await emit(f"[tool result] {name}: {_truncate(tool_result, 2000)}")
                    conversation.append({
                        "type": "function_call_output", "call_id": call_id,
                        "output": tool_result,
                    })
            raise RuntimeError(f"Responses agent exceeded {self.max_turns} tool turns")
        except AgentCancelled as exc:
            if self._tools is not None:
                await self._tools.cancel()
            return {
                "success": False, "stdout": collector.value(), "stderr": str(exc),
                "returncode": 130, "result": final_text,
                "session_id": last_response_id,
            }
        except AgentTimeout as exc:
            if self._tools is not None:
                await self._tools.cancel()
            return {
                "success": False, "stdout": collector.value(), "stderr": str(exc),
                "returncode": 124, "result": final_text,
                "session_id": last_response_id,
            }
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            if self._tools is not None:
                await self._tools.cancel()
            message = str(exc)
            if self._api_key:
                message = message.replace(self._api_key, "[redacted]")
            log.error("Responses agent failed: %s", message)
            return {
                "success": False, "stdout": collector.value(), "stderr": message,
                "returncode": 1, "result": final_text,
                "session_id": last_response_id,
            }
        finally:
            # The persisted secret store remains authoritative.  Keep the
            # plaintext credential only for the lifetime of this run.
            self._api_key = ""
            self._running = False

    async def cancel(self) -> None:
        self._cancel_event.set()
        self._thread_cancel_event.set()
        if self._tools is not None:
            await self._tools.cancel()

    @property
    def is_running(self) -> bool:
        return self._running and not self._cancel_event.is_set()


class OpenAICompatibleAgent:
    """Chat Completions tool loop using the same workspace tools as Responses.

    ShareAPI / OpenAI-compatible relays often only expose
    ``/v1/chat/completions``. Workflow skills still need read/write/run tools,
    so this agent mirrors the Responses loop over the Chat Completions wire
    format instead of falling back to an external Claude CLI.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        parameters: dict[str, Any] | None = None,
        environment: dict[str, str] | None = None,
        request_func: Callable[[dict[str, Any]], Any] | None = None,
        max_turns: int = 80,
    ) -> None:
        self.base_url = base_url
        self._api_key = api_key
        self.model_id = model_id
        self.parameters = dict(parameters or {})
        self.environment = dict(environment or os.environ)
        self.request_func = request_func
        self.max_turns = max(1, min(int(max_turns), 200))
        self._cancel_event = asyncio.Event()
        self._thread_cancel_event = threading.Event()
        self._tools: WorkspaceTools | None = None
        self._last_activity = time.monotonic()
        self._running = False

    def _payload_parameters(self) -> dict[str, Any]:
        defaults = {"temperature": 0.3, "top_p": 1.0, "max_tokens": 8192}
        defaults.update(self.parameters)
        payload = {
            "temperature": defaults.get("temperature", 0.3),
            "top_p": defaults.get("top_p", 1.0),
            "max_tokens": defaults.get("max_tokens", 8192),
        }
        # Some OpenAI-compatible gateways accept reasoning_effort on chat models.
        if defaults.get("reasoning_effort"):
            payload["reasoning_effort"] = defaults["reasoning_effort"]
        return payload

    async def _call_transport(self, payload: dict[str, Any], *, timeout: int) -> dict:
        if self.request_func is not None:
            if inspect.iscoroutinefunction(self.request_func):
                result = await self.request_func(payload)
            else:
                result = await asyncio.to_thread(self.request_func, payload)
            if not isinstance(result, dict):
                raise RuntimeError("Chat Completions transport returned a non-object")
            return result

        from services.llm_client import _request_json

        return await asyncio.to_thread(
            _request_json,
            self.base_url,
            self._api_key,
            payload,
            timeout,
            cancel_event=self._thread_cancel_event,
        )

    async def _request_with_deadlines(
        self,
        payload: dict[str, Any],
        *,
        deadline: float,
        inactivity_timeout: int,
    ) -> dict:
        remaining = max(1, int(deadline - time.monotonic()))
        request_task = asyncio.create_task(self._call_transport(payload, timeout=remaining))
        try:
            while not request_task.done():
                now = time.monotonic()
                if self._cancel_event.is_set():
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentCancelled("agent cancelled")
                if now >= deadline:
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentTimeout("Chat Completions agent exceeded overall timeout")
                if now - self._last_activity >= inactivity_timeout:
                    self._thread_cancel_event.set()
                    request_task.cancel()
                    raise AgentTimeout(
                        f"Chat Completions agent produced no activity for {inactivity_timeout}s"
                    )
                await asyncio.wait({request_task}, timeout=0.1)
            return await request_task
        finally:
            if not request_task.done():
                request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)

    @staticmethod
    def _message(response: dict[str, Any]) -> dict[str, Any]:
        try:
            message = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Chat Completions response missing message: {json.dumps(response, ensure_ascii=False)[:500]}"
            ) from exc
        if not isinstance(message, dict):
            raise RuntimeError("Chat Completions message must be an object")
        return message

    @staticmethod
    def _content_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    if isinstance(part.get("text"), str):
                        parts.append(part["text"])
                    elif part.get("type") == "text" and isinstance(part.get("text"), str):
                        parts.append(part["text"])
            return "".join(parts)
        return ""

    @staticmethod
    def _tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            return []
        return [item for item in calls if isinstance(item, dict)]

    async def run(
        self,
        *,
        prompt: str,
        cwd: str | Path,
        workflow_id: str,
        on_output: Callable[[str], Awaitable[None]] | None = None,
        inactivity_timeout: int = 2400,
        overall_timeout: int = 7200,
        resume_session_id: str | None = None,
    ) -> dict[str, Any]:
        collector = _TextCollector(MAX_RUN_STDOUT_CHARS)
        self._running = True
        deadline = time.monotonic() + max(1, int(overall_timeout))
        self._last_activity = time.monotonic()

        async def emit(value: str) -> None:
            if not value:
                return
            self._last_activity = time.monotonic()
            entry = value + ("" if value.endswith("\n") else "\n")
            before = collector.length
            collector.add(entry)
            kept = collector.length - before
            if on_output and kept:
                try:
                    await on_output(_truncate(entry[:kept].rstrip("\n"), 4000))
                except Exception:
                    log.exception("Chat Completions agent output callback failed")

        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        final_text = ""
        try:
            self._tools = WorkspaceTools(
                cwd,
                on_output=emit,
                cancel_event=self._cancel_event,
                environment=self.environment,
                max_command_timeout=min(
                    max(1, int(overall_timeout)), max(1, int(inactivity_timeout)), 900
                ),
            )
            await emit(f"[Chat Completions agent] starting workflow {workflow_id}")
            for _turn in range(1, self.max_turns + 1):
                if self._cancel_event.is_set():
                    raise AgentCancelled("agent cancelled")
                payload = {
                    "model": self.model_id,
                    "messages": messages,
                    "tools": chat_tool_definitions(),
                    "tool_choice": "auto",
                    **self._payload_parameters(),
                }
                response = await self._request_with_deadlines(
                    payload,
                    deadline=deadline,
                    inactivity_timeout=max(1, int(inactivity_timeout)),
                )
                message = self._message(response)
                text = self._content_text(message)
                if text:
                    final_text = _truncate(text, MAX_RUN_STDOUT_CHARS)
                    await emit(final_text)
                calls = self._tool_calls(message)
                if not calls:
                    if not text:
                        raise RuntimeError(
                            "Chat Completions model ended without text or a tool call"
                        )
                    return {
                        "success": True,
                        "stdout": collector.value(),
                        "stderr": "",
                        "returncode": 0,
                        "result": final_text,
                        "session_id": resume_session_id,
                    }

                # Preserve the assistant tool-call turn exactly as returned so
                # providers that require matching tool_call ids continue the loop.
                assistant_message = {
                    "role": "assistant",
                    "content": message.get("content") if message.get("content") is not None else "",
                    "tool_calls": calls,
                }
                if isinstance(message.get("function_call"), dict):
                    assistant_message["function_call"] = message["function_call"]
                messages.append(assistant_message)

                for call in calls:
                    function = call.get("function") if isinstance(call.get("function"), dict) else {}
                    name = str(function.get("name") or call.get("name") or "")
                    call_id = str(call.get("id") or call.get("tool_call_id") or "")
                    raw_arguments = function.get("arguments", "{}")
                    if isinstance(raw_arguments, dict):
                        tool_arguments = raw_arguments
                    elif isinstance(raw_arguments, str):
                        try:
                            value = json.loads(raw_arguments or "{}")
                            tool_arguments = value if isinstance(value, dict) else {}
                        except json.JSONDecodeError as exc:
                            tool_result = json.dumps(
                                {"ok": False, "error": f"invalid tool JSON: {exc}"},
                                ensure_ascii=False,
                            )
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call_id,
                                    "content": tool_result,
                                }
                            )
                            continue
                    else:
                        tool_arguments = {}
                    await emit(
                        f"[tool] {name} {json.dumps(tool_arguments, ensure_ascii=False)[:1000]}"
                    )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise AgentTimeout("Chat Completions agent exceeded overall timeout")
                    try:
                        tool_result = await asyncio.wait_for(
                            self._tools.execute(name, tool_arguments), timeout=remaining
                        )
                    except asyncio.TimeoutError as exc:
                        raise AgentTimeout(
                            "Chat Completions agent exceeded overall timeout during a tool call"
                        ) from exc
                    await emit(f"[tool result] {name}: {_truncate(tool_result, 2000)}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": tool_result,
                        }
                    )
            raise RuntimeError(f"Chat Completions agent exceeded {self.max_turns} tool turns")
        except AgentCancelled as exc:
            if self._tools is not None:
                await self._tools.cancel()
            return {
                "success": False,
                "stdout": collector.value(),
                "stderr": str(exc),
                "returncode": 130,
                "result": final_text,
                "session_id": resume_session_id,
            }
        except AgentTimeout as exc:
            if self._tools is not None:
                await self._tools.cancel()
            return {
                "success": False,
                "stdout": collector.value(),
                "stderr": str(exc),
                "returncode": 124,
                "result": final_text,
                "session_id": resume_session_id,
            }
        except asyncio.CancelledError:
            await self.cancel()
            raise
        except Exception as exc:
            if self._tools is not None:
                await self._tools.cancel()
            message = str(exc)
            if self._api_key:
                message = message.replace(self._api_key, "[redacted]")
            log.error("Chat Completions agent failed: %s", message)
            return {
                "success": False,
                "stdout": collector.value(),
                "stderr": message,
                "returncode": 1,
                "result": final_text,
                "session_id": resume_session_id,
            }
        finally:
            self._api_key = ""
            self._running = False

    async def cancel(self) -> None:
        self._cancel_event.set()
        self._thread_cancel_event.set()
        if self._tools is not None:
            await self._tools.cancel()

    @property
    def is_running(self) -> bool:
        return self._running and not self._cancel_event.is_set()
