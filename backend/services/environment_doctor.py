"""Read-only environment inventory for onboarding and support."""
from __future__ import annotations
import platform
import shutil
import subprocess
from pathlib import Path

LOGIN_URLS = {
    "codex": "https://platform.openai.com/",
    "claude": "https://docs.anthropic.com/en/docs/claude-code/overview",
}


def _version(executable: str | None) -> str | None:
    if not executable:
        return None
    try:
        completed = subprocess.run([executable, "--version"], text=True, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or completed.stderr).strip().splitlines()
    return output[0] if completed.returncode == 0 and output else None


class EnvironmentDoctor:
    """Inventory prerequisites without mutating host configuration or auth state."""
    TOOL_SPECS = (
        ("bundled_python", "python", "runtime/python/python.exe"),
        ("system_python", "python", None),
        ("node", "node", None),
        ("git", "git", None),
        ("pandoc", "pandoc", None),
        ("latex", "xelatex", None),
        ("drawio", "drawio", None),
        ("codex", "codex", None),
        ("claude", "claude", None),
    )

    def __init__(self, project_root: Path):
        self.project_root = project_root.resolve()

    def _tool(self, tool_id: str, command: str, bundled_path: str | None) -> dict:
        bundled = self.project_root / bundled_path if bundled_path else None
        executable = str(bundled) if bundled and bundled.is_file() else shutil.which(command)
        version = _version(executable)
        available = bool(executable and version)
        action = {"kind": "none"} if available else {"kind": "install_or_configure", "command": command}
        if tool_id in LOGIN_URLS:
            action = {"kind": "official_login", "url": LOGIN_URLS[tool_id]} if not available else {"kind": "official_login", "url": LOGIN_URLS[tool_id], "optional": True}
        return {"id": tool_id, "status": "available" if available else "unavailable", "path": executable, "version": version, "auth_status": "unknown" if tool_id in LOGIN_URLS else "not_applicable", "action": action}

    def report(self) -> dict:
        return {"schema_version": "1.0", "platform": platform.platform(), "project_root": str(self.project_root), "tools": [self._tool(*spec) for spec in self.TOOL_SPECS]}
