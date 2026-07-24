from __future__ import annotations


def test_cli_provider_does_not_report_mock_as_available(monkeypatch):
    import services.agent_provider as providers

    monkeypatch.setattr(providers.shutil, "which", lambda command: None)
    status = providers.CliProvider("codex", "codex").doctor()
    assert status.available is False
    assert status.reason == "executable_not_found"


def test_openai_provider_requires_configuration_and_registry_is_real(monkeypatch):
    import services.agent_provider as providers

    monkeypatch.setattr(providers.shutil, "which", lambda command: "/real/bin/" + command)
    registry = providers.provider_registry(openai_configured=False)
    assert registry["codex"].doctor().available is True
    assert registry["claude"].doctor().available is True
    assert registry["openai-compatible"].doctor().reason == "credentials_not_configured"
