"""Multi-provider model profile configuration is typed, secret-safe, and durable."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_model_profile_validation_covers_supported_providers():
    from services import model_profiles

    for provider in (
        "openai_compatible",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    ):
        value = model_profiles.validate_update(
            {
                "provider": provider,
                "base_url": "https://api.example.com/v1",
                "model_id": "demo-model",
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 2048,
                "reasoning_effort": "medium",
            }
        )
        assert value["provider"] == provider
        assert value["base_url"].startswith("https://")
        assert value["model_id"] == "demo-model"
        assert value["reasoning_effort"] == "medium"

    with pytest.raises(HTTPException) as error:
        model_profiles.validate_update(
            {
                "provider": "invented",
                "base_url": "https://api.example.com",
                "model_id": "x",
            }
        )
    assert error.value.status_code == 422

    with pytest.raises(HTTPException) as error:
        model_profiles.validate_update(
            {
                "provider": "openai_compatible",
                "base_url": "ftp://bad.example",
                "model_id": "x",
            }
        )
    assert error.value.status_code == 422


def test_model_profiles_persist_without_leaking_api_keys(tmp_path, monkeypatch):
    import services.state_store as store
    import services.model_profiles as profiles
    import services.secret_store as secrets

    store.DB_PATH = tmp_path / "profiles.db"
    secret_store = secrets.SecretStore(path=tmp_path / "secrets.v1.json")
    monkeypatch.setattr(secrets, "get_secret_store", lambda: secret_store)
    secrets._default_store = secret_store

    async def go():
        await store.init_db()
        empty = await profiles.profiles()
        assert {item["role"] for item in empty["profiles"]} == {"executor", "reviewer", "editor_ai"}
        assert all(item["api_key_configured"] is False for item in empty["profiles"])

        saved = await profiles.save(
            "executor",
            {
                "provider": "anthropic_messages",
                "base_url": "https://api.anthropic.com",
                "model_id": "claude-opus-4-8",
                "temperature": 0.1,
                "top_p": 1.0,
                "max_tokens": 4096,
                "reasoning_effort": "high",
                "api_key": "sk-test-secret-value",
            },
        )
        assert saved["provider"] == "anthropic_messages"
        assert saved["model_id"] == "claude-opus-4-8"
        assert saved["api_key_configured"] is True
        assert "api_key" not in saved
        assert "sk-test" not in str(saved)

        reviewer = await profiles.save(
            "reviewer",
            {
                "provider": "openai_compatible",
                "base_url": "https://relay.example.com/v1",
                "model_id": "gpt-5.5",
                "temperature": 0.0,
                "top_p": 1.0,
                "max_tokens": 2048,
                "reasoning_effort": "",
            },
        )
        assert reviewer["provider"] == "openai_compatible"
        assert reviewer["api_key_configured"] is False

        all_profiles = await profiles.profiles()
        by_role = {item["role"]: item for item in all_profiles["profiles"]}
        assert by_role["executor"]["provider"] == "anthropic_messages"
        assert by_role["executor"]["api_key_configured"] is True
        assert by_role["reviewer"]["base_url"] == "https://relay.example.com/v1"
        # Secrets remain out of the public profile payload.
        payload = str(all_profiles)
        assert "sk-test-secret-value" not in payload

        # Runtime settings must resolve the real secret, not the SQLite marker.
        runtime = await store.get_all_settings()
        assert runtime["executor_api_key"] == "sk-test-secret-value"
        assert runtime["executor_provider"] == "anthropic_messages"
        assert runtime["executor_base_url"] == "https://api.anthropic.com"

        cleared = await profiles.save(
            "executor",
            {
                "provider": "anthropic_messages",
                "base_url": "https://api.anthropic.com",
                "model_id": "claude-opus-4-8",
                "temperature": 0.1,
                "top_p": 1.0,
                "max_tokens": 4096,
                "reasoning_effort": "high",
                "clear_api_key": True,
            },
        )
        assert cleared["api_key_configured"] is False
        assert (await store.get_all_settings()).get("executor_api_key", "") == ""

    asyncio.run(go())


def test_stale_secret_markers_are_healed_and_reported_unconfigured(tmp_path, monkeypatch):
    """SQLite configured markers must not outlive the encrypted secret store."""
    import services.state_store as store
    import services.model_profiles as profiles
    import services.secret_store as secrets

    store.DB_PATH = tmp_path / "profiles.db"
    secret_store = secrets.SecretStore(path=tmp_path / "secrets.v1.json")
    monkeypatch.setattr(secrets, "get_secret_store", lambda: secret_store)
    secrets._default_store = secret_store

    async def go():
        await store.init_db()
        await profiles.save(
            "executor",
            {
                "provider": "openai_compatible",
                "base_url": "https://api.ai-pixel.online/v1",
                "model_id": "gpt-5.6-sol",
                "temperature": 0.3,
                "top_p": 1.0,
                "max_tokens": 8192,
                "reasoning_effort": "medium",
                "api_key": "sk-live-shareapi-key",
            },
        )
        # Simulate a partial secret loss: marker remains, ciphertext is gone.
        secret_store.clear("executor_api_key")
        db = await store.get_db()
        try:
            await db.execute(
                "UPDATE settings SET value='__secret_configured__' WHERE key='executor_api_key'"
            )
            await db.commit()
        finally:
            await db.close()

        metadata = await store.get_settings_metadata()
        assert metadata["executor_api_key"]["configured"] is False
        runtime = await store.get_all_settings()
        assert runtime.get("executor_api_key", "") == ""
        listed = await profiles.profiles()
        executor = next(item for item in listed["profiles"] if item["role"] == "executor")
        assert executor["api_key_configured"] is False
        assert executor["base_url"] == "https://api.ai-pixel.online/v1"
        assert executor["model_id"] == "gpt-5.6-sol"

        # Re-saving a ShareAPI/OpenAI-compatible profile must restore both sides.
        restored = await profiles.save(
            "executor",
            {
                "provider": "openai_compatible",
                "base_url": "https://api.ai-pixel.online/v1",
                "model_id": "gpt-5.6-sol",
                "temperature": 0.3,
                "top_p": 1.0,
                "max_tokens": 8192,
                "reasoning_effort": "medium",
                "api_key": "sk-restored-shareapi",
            },
        )
        assert restored["api_key_configured"] is True
        assert (await store.get_all_settings())["executor_api_key"] == "sk-restored-shareapi"
        assert (await store.get_settings_metadata())["executor_api_key"]["configured"] is True

    asyncio.run(go())
