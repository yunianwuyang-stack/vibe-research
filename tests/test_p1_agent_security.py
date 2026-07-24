from __future__ import annotations

import asyncio
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_workspace_tools_drop_unrelated_secrets_and_reject_escape(tmp_path):
    from services.openai_responses_agent import WorkspaceBoundaryError, WorkspaceTools
    tools = WorkspaceTools(tmp_path, environment={"PATH": "", "UNRELATED_API_KEY": "do-not-leak", "SKILL_MODE": "strict"})
    assert "UNRELATED_API_KEY" not in tools.environment
    assert tools.environment["SKILL_MODE"] == "strict"
    with pytest.raises(WorkspaceBoundaryError):
        tools._resolve("../outside.txt")


def test_workspace_tools_reject_non_allowlisted_command(tmp_path):
    from services.openai_responses_agent import WorkspaceTools
    tools = WorkspaceTools(tmp_path, environment={"PATH": ""})
    result = asyncio.run(tools.execute("run_command", {"command": "cmd", "args": ["/c", "echo", "bad"]}))
    assert "command not allowlisted" in result


def test_workspace_tools_reject_absolute_path_to_allowlisted_binary(tmp_path):
    from services.openai_responses_agent import WorkspaceTools
    tools = WorkspaceTools(tmp_path, environment={"PATH": ""})
    result = asyncio.run(
        tools.execute("run_command", {"command": str(tmp_path / "python.exe"), "args": []})
    )
    assert "command path must be a bare allowlisted program name" in result


def test_workspace_tools_reject_python_inline_execution(tmp_path):
    from services.openai_responses_agent import WorkspaceTools
    tools = WorkspaceTools(tmp_path, environment={"PATH": ""})
    result = asyncio.run(
        tools.execute("run_command", {"command": "python", "args": ["-c", "print('unsafe')"]})
    )
    assert "interpreter inline and module execution are not allowlisted" in result


def test_secret_redaction_covers_environment_and_key_shapes():
    from services.openai_responses_agent import redact_secrets
    secret = "sk-example-secret-value-123456789"
    text = redact_secrets(f"token={secret} raw={secret}", {"PROVIDER_API_KEY": secret})
    assert secret not in text
    assert "[REDACTED]" in text


def test_zip_compression_ratio_is_bounded(tmp_path):
    from services.safe_archive import extract_zip
    source = tmp_path / "bomb.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("huge.txt", b"A" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="compression ratio"):
        extract_zip(source, tmp_path / "out")
