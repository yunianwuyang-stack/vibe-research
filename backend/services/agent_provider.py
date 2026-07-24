"""Provider adapters whose availability is determined from real executables/configuration."""
from __future__ import annotations

from dataclasses import dataclass
import shutil
from typing import Protocol


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str | None
    executable: str | None


class AgentProvider(Protocol):
    def doctor(self) -> ProviderStatus: ...


class CliProvider:
    def __init__(self, name: str, command: str):
        self.name, self.command = name, command

    def doctor(self) -> ProviderStatus:
        executable = shutil.which(self.command)
        return ProviderStatus(self.name, bool(executable), None if executable else "executable_not_found", executable)


class OpenAICompatibleProvider:
    def __init__(self, configured: bool):
        self.configured = configured

    def doctor(self) -> ProviderStatus:
        return ProviderStatus("openai-compatible", self.configured, None if self.configured else "credentials_not_configured", None)


def provider_registry(openai_configured: bool = False) -> dict[str, AgentProvider]:
    return {"codex": CliProvider("codex", "codex"), "claude": CliProvider("claude", "claude"),
            "openai-compatible": OpenAICompatibleProvider(openai_configured)}
