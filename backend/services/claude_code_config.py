"""Load Claude Code local settings into the app secret/settings store.

Test and operator harnesses may import credentials from the user's local Claude
Code configuration. Values never appear as UI defaults and are never written
into source trees — only into the encrypted secret store / settings metadata.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def default_claude_settings_path() -> Path:
    override = str(os.environ.get("CLAUDE_CODE_SETTINGS_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "settings.json"


def read_claude_code_settings(path: Path | None = None) -> dict[str, Any]:
    """Return the Claude Code settings object, or {} when missing/invalid."""
    target = path or default_claude_settings_path()
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def extract_anthropic_credentials(settings: dict[str, Any] | None = None) -> dict[str, str]:
    """Extract base URL / API key material from Claude Code settings or env.

    Preference order for the key:
    1. settings.env.ANTHROPIC_AUTH_TOKEN
    2. settings.env.ANTHROPIC_API_KEY
    3. process env ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY

    Base URL preference:
    1. settings.env.ANTHROPIC_BASE_URL
    2. process env ANTHROPIC_BASE_URL
    """
    raw = settings if settings is not None else read_claude_code_settings()
    env_block = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    api_key = str(
        env_block.get("ANTHROPIC_AUTH_TOKEN")
        or env_block.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    ).strip()
    base_url = str(
        env_block.get("ANTHROPIC_BASE_URL")
        or os.environ.get("ANTHROPIC_BASE_URL")
        or ""
    ).strip()
    model_id = str(
        env_block.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or env_block.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or raw.get("model")
        or "claude-sonnet-4-20250514"
    ).strip()
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model_id": model_id,
        "provider": "anthropic_messages",
    }


async def import_claude_code_into_secret_store(
    *,
    roles: tuple[str, ...] = ("executor",),
    settings_path: Path | None = None,
    require_credentials: bool = False,
) -> dict[str, Any]:
    """Persist Claude Code credentials into model-profile settings + secret store.

    Returns a redacted summary suitable for logs/tests (never includes the key).
    """
    from services import model_profiles

    creds = extract_anthropic_credentials(read_claude_code_settings(settings_path))
    if not creds["api_key"] and not creds["base_url"]:
        if require_credentials:
            raise RuntimeError("Claude Code settings did not provide ANTHROPIC credentials")
        return {
            "imported": False,
            "reason": "no_credentials",
            "roles": [],
            "api_key_configured": False,
            "base_url_configured": False,
            "model_id": "",
            "provider": creds["provider"],
        }

    saved_roles: list[str] = []
    for role in roles:
        payload: dict[str, Any] = {
            "provider": creds["provider"],
            "base_url": creds["base_url"],
            "model_id": creds["model_id"] or "claude-sonnet-4-20250514",
            "temperature": 0.3,
            "top_p": 1.0,
            "max_tokens": 8192,
            "reasoning_effort": "",
        }
        if creds["api_key"]:
            payload["api_key"] = creds["api_key"]
        await model_profiles.save(role, payload)
        saved_roles.append(role)

    return {
        "imported": True,
        "roles": saved_roles,
        "api_key_configured": bool(creds["api_key"]),
        "base_url_configured": bool(creds["base_url"]),
        "model_id": creds["model_id"],
        "provider": creds["provider"],
        # Never echo secret material.
        "base_url_host": _safe_host(creds["base_url"]),
    }


def _safe_host(base_url: str) -> str:
    if not base_url:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        return parsed.hostname or ""
    except Exception:
        return ""
