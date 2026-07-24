"""Safe local preview servers for generated ``code/`` projects.

The preview API intentionally does not accept a command line.  It detects a
small set of supported project shapes and maps each shape to a fixed command
recipe.  Every child is launched by :class:`ProcessSupervisor` inside the
workflow workspace with a scrubbed environment and loopback-only binding.
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import shutil
import socket
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import RUNTIME_NODE, RUNTIME_PYTHON, WORKSPACES_DIR
from services.process_supervisor import ProcessSupervisor

log = logging.getLogger(__name__)

PORT_RANGE_START = 19000
PORT_RANGE_END = 19100
_STATE_FILE = ".preview-servers.json"
_READ_LIMIT = 256 * 1024
_SENSITIVE_ENV_MARKERS = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "ANTHROPIC", "OPENAI",
    "LICENSE", "CLAUDE", "MINIMAX", "GEMINI", "API_",
)


@dataclass
class _ProjectShape:
    has_backend: bool = False
    has_frontend: bool = False
    backend_dir: Path | None = None
    frontend_dir: Path | None = None
    backend_framework: str | None = None
    frontend_kind: str | None = None
    backend_serves_frontend: bool = False


@dataclass(frozen=True)
class _ProcessIdentity:
    executable: str
    start_token: str


@dataclass
class _Proc:
    kind: str
    port: int
    url: str
    pid: int
    cwd: Path
    executable: str
    start_token: str
    task_id: str | None = None
    recovered: bool = False
    monitor: asyncio.Task | None = field(default=None, repr=False, compare=False)


@dataclass
class _ServerEntry:
    frontend: _Proc | None = None
    backend: _Proc | None = None


def _read_head(path: Path, limit: int = _READ_LIMIT) -> str:
    """Read only ordinary project files; never follow a project symlink."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * limit:
            return ""
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except (OSError, UnicodeError):
        return ""


def _package(path: Path) -> dict[str, Any]:
    raw = _read_head(path)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _contains_html(root: Path) -> bool:
    try:
        for index, candidate in enumerate(root.rglob("*.html")):
            if index >= 100:
                return False
            if candidate.is_symlink() or "node_modules" in candidate.parts:
                continue
            return True
    except OSError:
        return False
    return False


def _detect_backend(directory: Path) -> tuple[str | None, str]:
    """Return ``(framework, source_head)`` without importing project code."""
    main_py = directory / "main.py"
    app_py = directory / "app.py"
    combined = "\n".join((_read_head(main_py), _read_head(app_py)))
    lower = combined.casefold()
    if "fastapi" in lower and ("fastapi(" in lower or "from fastapi" in lower):
        return "fastapi", combined
    if "flask" in lower and ("flask(" in lower or "from flask" in lower):
        return "flask", combined

    package = _package(directory / "package.json")
    dependencies: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            dependencies.update(value)
    js_source = "\n".join(
        _read_head(directory / name) for name in ("index.js", "server.js", "app.js")
    )
    if "express" in dependencies or "express" in js_source.casefold():
        return "express", combined + js_source
    return None, combined + js_source


def _detect_project(code_dir: Path) -> _ProjectShape:
    """Detect frontend/backend shape strictly from bounded text inspection."""
    code_dir = code_dir.resolve()
    shape = _ProjectShape()

    backend_candidate = code_dir / "backend"
    if not backend_candidate.is_dir() or backend_candidate.is_symlink():
        backend_candidate = code_dir
    framework, backend_source = _detect_backend(backend_candidate)
    if framework is not None:
        shape.has_backend = True
        shape.backend_dir = backend_candidate
        shape.backend_framework = framework

    frontend_candidate = code_dir / "frontend"
    if not frontend_candidate.is_dir() or frontend_candidate.is_symlink():
        frontend_candidate = code_dir
    package = _package(frontend_candidate / "package.json")
    dependencies: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key)
        if isinstance(value, dict):
            dependencies.update(value)
    scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
    spa_markers = {"react", "react-dom", "vue", "vite", "@vitejs/plugin-react", "next"}
    is_spa = bool(package) and (
        bool(spa_markers.intersection(dependencies))
        or "dev" in scripts
        or "build" in scripts
    )
    has_html = _contains_html(frontend_candidate)
    if is_spa:
        shape.has_frontend = True
        shape.frontend_dir = frontend_candidate
        dev_script = str(scripts.get("dev", "")).casefold()
        if "vite" in dependencies or "vite" in dev_script:
            shape.frontend_kind = "vite"
        elif "next" in dependencies or "next" in dev_script:
            shape.frontend_kind = "next"
        else:
            shape.frontend_kind = "spa"
    elif has_html:
        shape.has_frontend = True
        shape.frontend_dir = frontend_candidate
        shape.frontend_kind = "html"

    source_lower = backend_source.casefold()
    shape.backend_serves_frontend = shape.has_backend and any(
        marker in source_lower
        for marker in (
            "staticfiles", "static_folder", "send_from_directory", "send_file",
            "render_template", "express.static", "sendfile",
        )
    )
    return shape


def _find_free_port(start: int, end: int, exclude: set[int] | None = None) -> int | None:
    excluded = exclude or set()
    for port in range(start, end):
        if port in excluded:
            continue
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return None


def _windows_process_identity(pid: int) -> _ProcessIdentity | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        created = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return _ProcessIdentity(str(Path(buffer.value).resolve()), str(created))
    finally:
        kernel32.CloseHandle(handle)


def _posix_process_identity(pid: int) -> _ProcessIdentity | None:
    proc_root = Path("/proc") / str(pid)
    try:
        stat = (proc_root / "stat").read_text(encoding="utf-8")
        close_paren = stat.rfind(")")
        fields = stat[close_paren + 2 :].split()
        # fields starts at stat field 3 (state); field 22 is index 19 here.
        start_token = fields[19]
        executable = str((proc_root / "exe").resolve())
        return _ProcessIdentity(executable, start_token)
    except (OSError, IndexError, ValueError):
        return None


def _process_identity(pid: int) -> _ProcessIdentity | None:
    if pid <= 1:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    identity = _posix_process_identity(pid)
    if identity is not None:
        return identity
    try:
        os.kill(pid, 0)
    except (OSError, PermissionError):
        return None
    return None  # Recovery is disabled when a strong start-time identity is unavailable.


def _same_executable(left: str, right: str) -> bool:
    if os.name == "nt":
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    return os.path.abspath(left) == os.path.abspath(right)


def _build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Construct a child environment without API/license credentials."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }
    path_parts: list[str] = []
    for runtime in (RUNTIME_NODE, RUNTIME_PYTHON):
        if runtime:
            candidate = Path(runtime)
            path_parts.append(str(candidate if candidate.is_dir() else candidate.parent))
    path_parts.append(env.get("PATH", ""))
    env["PATH"] = os.pathsep.join(part for part in path_parts if part)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update({str(key): str(value) for key, value in extra.items()})
    return env


class ProjectServerManager:
    def __init__(
        self,
        workspace_root: Path = WORKSPACES_DIR,
        *,
        port_start: int = PORT_RANGE_START,
        port_end: int = PORT_RANGE_END,
        python_executable: str | None = None,
        npm_executable: str | None = None,
        node_executable: str | None = None,
    ):
        self.workspace_root = workspace_root.resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.port_start = int(port_start)
        self.port_end = int(port_end)
        if self.port_start <= 0 or self.port_end <= self.port_start or self.port_end > 65536:
            raise ValueError("Invalid preview port range")
        self._python_override = python_executable
        self._npm_override = npm_executable
        self._node_override = node_executable
        allowed = {Path(self._python()).name}
        npm = self._npm()
        if npm:
            allowed.add(Path(npm).name)
        node = self._node()
        if node:
            allowed.add(Path(node).name)
        self._supervisor = ProcessSupervisor(self.workspace_root, allowed)
        self._servers: dict[str, _ServerEntry] = {}
        self._lock = asyncio.Lock()

    def _python(self) -> str:
        if self._python_override:
            return self._python_override
        if RUNTIME_PYTHON and Path(RUNTIME_PYTHON).is_file():
            return str(Path(RUNTIME_PYTHON).resolve())
        return sys.executable

    def _npm(self) -> str | None:
        if self._npm_override:
            return self._npm_override
        candidates: list[Path] = []
        if RUNTIME_NODE:
            runtime = Path(RUNTIME_NODE)
            if runtime.is_dir():
                candidates.extend((runtime / "npm.cmd", runtime / "npm"))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve())
        return shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")

    def _node(self) -> str | None:
        if self._node_override:
            return self._node_override
        candidates: list[Path] = []
        if RUNTIME_NODE:
            runtime = Path(RUNTIME_NODE)
            if runtime.is_dir():
                candidates.extend((runtime / "node.exe", runtime / "node"))
            elif runtime.is_file():
                candidates.append(runtime)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve())
        return shutil.which("node.exe" if os.name == "nt" else "node") or shutil.which("node")

    def _code_dir(self, code_dir: Path) -> tuple[Path, Path, str]:
        unresolved = Path(code_dir)
        if unresolved.is_symlink():
            raise ValueError("Project code directory cannot be a symlink")
        resolved = unresolved.resolve()
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("Project directory escapes workspace root") from exc
        if len(relative.parts) != 2 or relative.parts[1] != "code":
            raise ValueError("Project directory must be a workflow code/ directory")
        if not resolved.is_dir():
            raise ValueError("Project code directory does not exist")
        workspace = resolved.parent
        return resolved, workspace, relative.parts[0]

    def _task_id(self, wf_id: str, kind: str) -> str:
        digest = hashlib.sha256(wf_id.encode("utf-8")).hexdigest()[:20]
        return f"preview-{digest}-{kind}"

    def _state_path(self, wf_id: str) -> Path:
        unresolved = self.workspace_root / wf_id
        if unresolved.is_symlink():
            raise ValueError("Workflow directory cannot be a symlink")
        workspace = unresolved.resolve()
        relative = workspace.relative_to(self.workspace_root)
        if len(relative.parts) != 1 or not relative.parts[0]:
            raise ValueError("Invalid workflow id")
        return workspace / _STATE_FILE

    def _persist(self, wf_id: str) -> None:
        path = self._state_path(wf_id)
        entry = self._servers.get(wf_id)
        rows: dict[str, dict[str, Any]] = {}
        if entry:
            for kind in ("frontend", "backend"):
                proc = getattr(entry, kind)
                if proc is None:
                    continue
                rows[kind] = {
                    "pid": proc.pid,
                    "port": proc.port,
                    "url": proc.url,
                    "cwd": str(proc.cwd),
                    "executable": proc.executable,
                    "start_token": proc.start_token,
                }
        if not rows:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        # The workflow already exists whenever a preview is launched.  Never
        # recreate it from a late process-monitor callback after the workflow
        # has been deleted.
        if not path.parent.is_dir():
            return
        payload = {"version": 1, "wf_id": wf_id, "servers": rows}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f"{_STATE_FILE}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _safe_persist(self, wf_id: str) -> None:
        try:
            self._persist(wf_id)
        except (OSError, ValueError):
            log.warning("Unable to persist preview state for %s", wf_id, exc_info=True)

    def _entry_running(self, proc: _Proc) -> bool:
        if proc.task_id and self._supervisor.is_running(proc.task_id):
            return True
        identity = _process_identity(proc.pid)
        return bool(
            identity
            and identity.start_token == proc.start_token
            and _same_executable(identity.executable, proc.executable)
        )

    def _drop_if_empty(self, wf_id: str) -> None:
        entry = self._servers.get(wf_id)
        if entry is not None and entry.frontend is None and entry.backend is None:
            self._servers.pop(wf_id, None)

    def _prune(self, wf_id: str) -> None:
        entry = self._servers.get(wf_id)
        if entry is None:
            return
        changed = False
        for kind in ("frontend", "backend"):
            proc = getattr(entry, kind)
            if proc is not None and not self._entry_running(proc):
                if proc.task_id:
                    self._supervisor.forget(proc.task_id, pid=proc.pid)
                setattr(entry, kind, None)
                changed = True
        self._drop_if_empty(wf_id)
        if changed:
            self._safe_persist(wf_id)

    def _used_ports(self) -> set[int]:
        ports: set[int] = set()
        for wf_id in list(self._servers):
            self._prune(wf_id)
        for entry in self._servers.values():
            for proc in (entry.frontend, entry.backend):
                if proc is not None:
                    ports.add(proc.port)
        return ports

    def _command(self, kind: str, code_dir: Path, port: int, shape: _ProjectShape):
        if kind == "frontend":
            directory = shape.frontend_dir
            if not shape.has_frontend or directory is None:
                return None
            if shape.frontend_kind in {"spa", "vite", "next"}:
                npm = self._npm()
                scripts = _package(directory / "package.json").get("scripts", {})
                if not npm or not isinstance(scripts, dict) or "dev" not in scripts:
                    return None
                args = [npm, "run", "dev"]
                if shape.frontend_kind == "vite":
                    # Vite otherwise silently increments a raced port, while
                    # the API keeps reporting the originally allocated URL.
                    args.extend(("--", "--port", str(port), "--host", "127.0.0.1", "--strictPort"))
                elif shape.frontend_kind == "next":
                    args.extend(("--", "--port", str(port), "--hostname", "127.0.0.1"))
                return (
                    args,
                    directory,
                    {"PORT": str(port), "HOST": "127.0.0.1", "BROWSER": "none"},
                )
            proxy = Path(__file__).resolve().with_name("_preview_proxy.py")
            return (
                [
                    self._python(), str(proxy), "--dir", str(directory.resolve()),
                    "--port", str(port), "--bind", "127.0.0.1",
                ],
                directory,
                {},
            )

        directory = shape.backend_dir
        framework = shape.backend_framework
        if not shape.has_backend or directory is None or framework is None:
            return None
        if framework == "fastapi":
            # No --reload: reloader forks break PID identity used by recover_all
            # after API process restart, and preview is a short-lived local serve.
            module = "main" if (directory / "main.py").is_file() else "app"
            return (
                [
                    self._python(), "-m", "uvicorn", f"{module}:app", "--host", "127.0.0.1",
                    "--port", str(port),
                ],
                directory,
                {"PORT": str(port), "HOST": "127.0.0.1"},
            )
        if framework == "flask":
            entry = "app.py" if (directory / "app.py").is_file() else "main.py"
            return (
                [self._python(), entry],
                directory,
                {"PORT": str(port), "HOST": "127.0.0.1", "FLASK_RUN_HOST": "127.0.0.1"},
            )
        if framework == "express":
            # Launch the allowlisted entry directly rather than an arbitrary
            # package script, and preload a tiny net.Server guard that rewrites
            # every TCP listen overload to IPv4 loopback.  Plain Express
            # ``app.listen(PORT)`` otherwise binds all interfaces and ignores
            # the HOST environment variable.
            entry = next(
                (
                    directory / name
                    for name in ("index.js", "server.js", "app.js")
                    if (directory / name).is_file() and not (directory / name).is_symlink()
                ),
                None,
            )
            node = self._node()
            if entry is None or node is None:
                return None
            guard = Path(__file__).resolve().with_name("_preview_node_guard.cjs")
            if not guard.is_file() or guard.is_symlink():
                return None
            return (
                [node, "--require", str(guard), entry.name],
                directory,
                {"PORT": str(port), "HOST": "127.0.0.1"},
            )
        return None

    @staticmethod
    def _static_dir(shape: _ProjectShape) -> Path | None:
        directory = shape.frontend_dir
        if directory is None:
            return None
        if shape.frontend_kind == "html":
            return directory
        for name in ("dist", "build"):
            candidate = directory / name
            if candidate.is_dir() and not candidate.is_symlink():
                return candidate
        return None

    @staticmethod
    def _start_error(kind: str, shape: _ProjectShape) -> str:
        if kind == "frontend":
            if shape.frontend_kind in {"spa", "vite", "next"}:
                return "前端起不来: package.json 缺少可用的 dev 脚本或 npm 运行时"
            return "前端起不来: code/frontend/(或 code/)下既没有 package.json, 也没有任何 .html 文件"
        return "后端起不来: code/backend/(或 code/)下没有受支持的 FastAPI/Flask/Express 入口"

    async def _capture_identity(self, pid: int) -> _ProcessIdentity | None:
        for _ in range(20):
            identity = _process_identity(pid)
            if identity is not None:
                return identity
            await asyncio.sleep(0.01)
        return None

    async def _monitor(self, wf_id: str, kind: str, proc: _Proc) -> None:
        owned = self._supervisor.get(proc.task_id or "")
        if owned is None:
            return
        try:
            await owned.wait()
        except asyncio.CancelledError:
            return
        async with self._lock:
            entry = self._servers.get(wf_id)
            if entry:
                # A backend that serves the built frontend is represented by
                # two API handles pointing at one child.  Clear every alias
                # when that child exits so status and persisted recovery state
                # cannot retain a dead frontend handle.
                for target in ("frontend", "backend"):
                    current = getattr(entry, target, None)
                    if current is not None and current.pid == proc.pid:
                        setattr(entry, target, None)
                self._drop_if_empty(wf_id)
                self._safe_persist(wf_id)
            if proc.task_id:
                self._supervisor.forget(proc.task_id, pid=proc.pid)

    def _alias_frontend_to_backend(self, wf_id: str) -> _Proc | None:
        entry = self._servers.get(wf_id)
        if entry is None or entry.backend is None:
            return None
        if entry.frontend is not None:
            return entry.frontend
        backend = entry.backend
        alias = _Proc(
            kind="frontend",
            port=backend.port,
            url=backend.url,
            pid=backend.pid,
            cwd=backend.cwd,
            executable=backend.executable,
            start_token=backend.start_token,
            task_id=backend.task_id,
            recovered=backend.recovered,
        )
        entry.frontend = alias
        self._safe_persist(wf_id)
        return alias

    async def _spawn_recipe(
        self,
        wf_id: str,
        kind: str,
        port: int,
        command: list[str],
        cwd: Path,
        extra_env: dict[str, str],
    ) -> dict[str, Any]:
        task_id = self._task_id(wf_id, kind)
        try:
            workspace = self._state_path(wf_id).parent
            unresolved_log_dir = workspace / ".preview-logs"
            if unresolved_log_dir.is_symlink():
                raise ValueError("Preview log directory cannot be a symlink")
            unresolved_log_dir.mkdir(exist_ok=True)
            log_dir = unresolved_log_dir.resolve()
            log_dir.relative_to(workspace)
            log_path = log_dir / f"{kind}.log"
            if log_path.is_symlink():
                raise ValueError("Preview log file cannot be a symlink")
            if log_path.exists():
                stat = log_path.stat()
                if not log_path.is_file() or stat.st_nlink != 1:
                    raise ValueError("Preview log file must be a regular unlinked file")
            with log_path.open("ab") as log_handle:
                process = await self._supervisor.spawn(
                    task_id,
                    command,
                    cwd,
                    env=_build_env(extra_env),
                    stdout=log_handle,
                    stderr=log_handle,
                )
        except (OSError, ValueError) as exc:
            return {"kind": kind, "status": "error", "error": f"启动失败: {exc}"}

        identity = await self._capture_identity(process.pid)
        if identity is None:
            await self._supervisor.cancel(task_id)
            return {"kind": kind, "status": "error", "error": "无法验证预览子进程身份，已安全停止"}

        # Detect immediate failures such as a port race or missing dependency.
        await asyncio.sleep(0.08)
        if process.returncode is not None:
            self._supervisor.forget(task_id, pid=process.pid)
            detail = "预览进程启动后立即退出"
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-1000:].strip()
                if tail:
                    detail = f"{detail}: {tail}"
            except OSError:
                pass
            return {"kind": kind, "status": "error", "error": detail}

        url = f"http://127.0.0.1:{port}"
        proc = _Proc(
            kind=kind,
            port=port,
            url=url,
            pid=process.pid,
            cwd=cwd.resolve(),
            executable=identity.executable,
            start_token=identity.start_token,
            task_id=task_id,
        )
        entry = self._servers.setdefault(wf_id, _ServerEntry())
        setattr(entry, kind, proc)
        self._safe_persist(wf_id)
        proc.monitor = asyncio.create_task(self._monitor(wf_id, kind, proc))
        return {"kind": kind, "status": "starting", "port": port, "url": url}

    async def _start_one(self, wf_id: str, kind: str, code_dir: Path, shape: _ProjectShape) -> dict[str, Any]:
        self._prune(wf_id)
        entry = self._servers.setdefault(wf_id, _ServerEntry())
        existing = getattr(entry, kind)
        if existing is not None:
            return {
                "kind": kind,
                "status": "already_running",
                "port": existing.port,
                "url": existing.url,
            }
        port = _find_free_port(self.port_start, self.port_end, self._used_ports())
        if port is None:
            return {
                "kind": kind,
                "status": "error",
                "error": f"预览端口 {self.port_start}-{self.port_end - 1} 全部被占用",
            }
        recipe = self._command(kind, code_dir, port, shape)
        if recipe is None:
            self._drop_if_empty(wf_id)
            return {"kind": kind, "status": "error", "error": self._start_error(kind, shape)}
        command, cwd, extra_env = recipe
        return await self._spawn_recipe(wf_id, kind, port, command, cwd, extra_env)

    async def _start_proxy_frontend(
        self,
        wf_id: str,
        shape: _ProjectShape,
        backend_port: int,
    ) -> dict[str, Any]:
        static_dir = self._static_dir(shape)
        if static_dir is None:
            return {
                "kind": "frontend",
                "status": "error",
                "error": "前端是 React/Vue 但没有 build 产物(dist/build)，无法预览；请先 npm run build",
            }
        port = _find_free_port(self.port_start, self.port_end, self._used_ports())
        if port is None:
            return {
                "kind": "frontend",
                "status": "error",
                "error": f"预览端口 {self.port_start}-{self.port_end - 1} 全部被占用",
            }
        proxy = Path(__file__).resolve().with_name("_preview_proxy.py")
        command = [
            self._python(), str(proxy), "--dir", str(static_dir.resolve()), "--port", str(port),
            "--backend-port", str(backend_port), "--bind", "127.0.0.1",
        ]
        result = await self._spawn_recipe(wf_id, "frontend", port, command, static_dir, {})
        if result.get("status") == "starting":
            result["note"] = "前端已通过反向代理与后端同源，/api 自动转发到后端"
        return result

    async def start(self, wf_id: str, code_dir: Path, mode: str) -> dict[str, Any]:
        if mode not in {"frontend", "backend", "both"}:
            raise ValueError("mode 必须是 frontend / backend / both")
        code_dir, _workspace, actual_wf_id = self._code_dir(code_dir)
        if actual_wf_id != wf_id:
            raise ValueError("Workflow id does not match project directory")
        async with self._lock:
            shape = _detect_project(code_dir)
            results: list[dict[str, Any]] = []

            if mode == "both" and shape.has_backend and shape.has_frontend:
                backend = await self._start_one(wf_id, "backend", code_dir, shape)
                results.append(backend)
                if backend.get("status") in {"starting", "already_running"}:
                    if shape.backend_serves_frontend:
                        alias = self._alias_frontend_to_backend(wf_id)
                        if alias is not None:
                            current = self._servers.get(wf_id)
                            shared = bool(current and current.backend and current.backend.pid == alias.pid)
                            if shared:
                                note = "后端已同源托管前端，前后端同一端口，/api 直接可用"
                                if shape.frontend_kind != "html" and self._static_dir(shape) is None:
                                    note += "（注意：前端需先 npm run build 生成 dist/build，后端才能托管页面）"
                            else:
                                note = "已有独立前端预览正在运行"
                            results.append({
                                "kind": "frontend",
                                "status": backend["status"] if shared else "already_running",
                                "port": alias.port,
                                "url": alias.url,
                                "note": note,
                            })
                    else:
                        results.append(await self._start_proxy_frontend(wf_id, shape, int(backend["port"])))
                return {"wf_id": wf_id, "servers": results}

            kinds: list[str] = []
            if mode in {"frontend", "both"} and (shape.has_frontend or mode == "frontend"):
                kinds.append("frontend")
            if mode in {"backend", "both"} and (shape.has_backend or mode == "backend"):
                kinds.append("backend")
            if not kinds:
                kinds = [mode] if mode != "both" else ["frontend", "backend"]
            for kind in kinds:
                result = await self._start_one(wf_id, kind, code_dir, shape)
                if (
                    kind == "frontend"
                    and result.get("status") == "starting"
                    and shape.has_backend
                    and not shape.backend_serves_frontend
                    and mode == "frontend"
                ):
                    result["note"] = "该前端需调后端 /api，单起前端时接口会失败，建议用「前后端一起」启动"
                results.append(result)
            return {"wf_id": wf_id, "servers": results}

    async def stop(self, wf_id: str, kind: str | None = None) -> dict[str, Any]:
        if kind is not None and kind not in {"frontend", "backend"}:
            raise ValueError("kind 必须是 frontend / backend")
        stopped: list[str] = []
        monitors: set[asyncio.Task] = set()
        async with self._lock:
            self._prune(wf_id)
            entry = self._servers.get(wf_id)
            if entry is None:
                return {"wf_id": wf_id, "stopped": stopped}
            targets = (kind,) if kind else ("frontend", "backend")
            handled_pids: dict[int, bool] = {}
            for target in targets:
                proc = getattr(entry, target)
                if proc is None:
                    continue
                if proc.pid in handled_pids:
                    success = handled_pids[proc.pid]
                else:
                    success = False
                    if proc.task_id and self._supervisor.get(proc.task_id) is not None:
                        success = await self._supervisor.cancel(proc.task_id)
                    elif self._entry_running(proc):
                        # Recovery is only accepted after exact executable and
                        # creation-time verification, preventing PID-reuse kills.
                        success = await ProcessSupervisor.terminate_process_tree(proc.pid)
                    handled_pids[proc.pid] = success
                if success:
                    # A same-origin frontend alias shares the backend PID.  A
                    # successful tree kill invalidates both handles at once.
                    for sibling in ("frontend", "backend"):
                        current = getattr(entry, sibling)
                        if current is not None and current.pid == proc.pid:
                            if sibling in targets and sibling not in stopped:
                                stopped.append(sibling)
                            setattr(entry, sibling, None)
                            if current.monitor and not current.monitor.done():
                                current.monitor.cancel()
                                monitors.add(current.monitor)
            self._drop_if_empty(wf_id)
            self._safe_persist(wf_id)
        if monitors:
            await asyncio.gather(*monitors, return_exceptions=True)
        return {"wf_id": wf_id, "stopped": stopped}

    async def status(self, wf_id: str) -> dict[str, Any]:
        async with self._lock:
            self._prune(wf_id)
            entry = self._servers.get(wf_id)
            result: dict[str, Any] = {"wf_id": wf_id, "frontend": None, "backend": None}
            if entry:
                for kind in ("frontend", "backend"):
                    proc = getattr(entry, kind)
                    if proc is not None:
                        result[kind] = {"port": proc.port, "url": proc.url, "running": True}
            return result

    async def recover_all(self) -> dict[str, int]:
        """Adopt only preview children proven by persisted PID identity."""
        recovered = 0
        discarded = 0
        async with self._lock:
            for state_path in self.workspace_root.glob(f"*/{_STATE_FILE}"):
                # Never traverse a workflow-directory symlink while reading or
                # deleting recovery metadata.
                try:
                    redirected_parent = state_path.parent.resolve() != state_path.parent.absolute()
                except OSError:
                    redirected_parent = True
                if state_path.parent.is_symlink() or redirected_parent:
                    discarded += 1
                    continue
                try:
                    if state_path.is_symlink():
                        state_path.unlink()
                        discarded += 1
                        continue
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    if (
                        not isinstance(payload, dict)
                        or payload.get("version") != 1
                        or not isinstance(payload.get("servers"), dict)
                    ):
                        raise ValueError("unsupported preview state")
                    wf_id = str(payload["wf_id"])
                    unresolved_workspace = self.workspace_root / wf_id
                    if unresolved_workspace.is_symlink():
                        raise ValueError("workflow symlink")
                    workspace = unresolved_workspace.resolve()
                    relative = workspace.relative_to(self.workspace_root)
                    code_path = workspace / "code"
                    if (
                        len(relative.parts) != 1
                        or workspace != state_path.parent.resolve()
                        or code_path.is_symlink()
                        or not code_path.is_dir()
                    ):
                        raise ValueError("state/workspace mismatch")
                    entry = _ServerEntry()
                    for kind in ("frontend", "backend"):
                        row = payload.get("servers", {}).get(kind)
                        if not isinstance(row, dict):
                            continue
                        try:
                            port = int(row["port"])
                            pid = int(row["pid"])
                            if not self.port_start <= port < self.port_end:
                                raise ValueError("invalid port")
                            cwd = Path(str(row["cwd"])).resolve()
                            cwd.relative_to(code_path.resolve())
                            identity = _process_identity(pid)
                            if not identity or identity.start_token != str(row["start_token"]):
                                continue
                            if not _same_executable(identity.executable, str(row["executable"])):
                                continue
                        except (OSError, TypeError, ValueError, KeyError):
                            continue
                        proc = _Proc(
                            kind=kind,
                            port=port,
                            url=f"http://127.0.0.1:{port}",
                            pid=pid,
                            cwd=cwd,
                            executable=identity.executable,
                            start_token=identity.start_token,
                            recovered=True,
                        )
                        setattr(entry, kind, proc)
                        recovered += 1
                    if entry.frontend or entry.backend:
                        self._servers[wf_id] = entry
                        self._safe_persist(wf_id)
                    else:
                        state_path.unlink(missing_ok=True)
                        discarded += 1
                except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                    state_path.unlink(missing_ok=True)
                    discarded += 1
        return {"recovered": recovered, "discarded": discarded}

    async def stop_all(self) -> dict[str, list[str]]:
        results: dict[str, list[str]] = {}
        for wf_id in list(self._servers):
            try:
                stopped = await self.stop(wf_id)
                results[wf_id] = stopped["stopped"]
            except Exception:
                log.exception("Failed to stop preview processes for workflow %s", wf_id)
                results[wf_id] = []
        return results


project_server_manager = ProjectServerManager()
