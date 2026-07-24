"""Typed, secret-safe model settings for the research roles."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException


ROLES = ("executor", "reviewer", "editor_ai")
ROLE_NAMES = {
    "executor": "执行模型",
    "reviewer": "独立审稿模型",
    "editor_ai": "科研编辑模型",
}
DEFAULTS = {
    # Workflow skills need a tool-capable transport.  Responses is the
    # product default; Chat Completions remains available as an explicit
    # compatibility choice in the settings UI.
    "provider": "openai_responses",
    "base_url": "",
    "model_id": "gpt-4o",
    "temperature": 0.3,
    "top_p": 1.0,
    "max_tokens": 8192,
    "reasoning_effort": "",
}
PROVIDERS = {
    "openai_compatible": "OpenAI 聊天补全",
    "openai_responses": "OpenAI 响应协议",
    "anthropic_messages": "Anthropic 消息协议",
    "gemini_generate_content": "Gemini 内容生成",
}
REASONING_EFFORTS = {"", "minimal", "low", "medium", "high"}


def _key(role: str, name: str) -> str:
    return f"{role}_{name}"


def _role_or_404(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(404, detail="Unknown model role")
    return role


def _metadata_value(metadata: dict[str, dict[str, object]], key: str, default: Any) -> Any:
    value = metadata.get(key, {}).get("value", default)
    return default if value is None else value


def _parse_float(value: Any, *, field: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail=f"{field} must be a number") from exc
    if not low <= number <= high:
        raise HTTPException(422, detail=f"{field} must be between {low} and {high}")
    return number


def _parse_int(value: Any, *, field: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, detail=f"{field} must be an integer") from exc
    if not low <= number <= high:
        raise HTTPException(422, detail=f"{field} must be between {low} and {high}")
    return number


def validate_update(values: dict[str, Any]) -> dict[str, Any]:
    provider = str(values.get("provider", DEFAULTS["provider"])).strip()
    if provider not in PROVIDERS:
        raise HTTPException(422, detail="provider must be openai_compatible, openai_responses, anthropic_messages, or gemini_generate_content")
    base_url = str(values.get("base_url", "")).strip()
    if base_url:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HTTPException(422, detail="base_url must be an absolute http(s) URL")
    model_id = str(values.get("model_id", "")).strip()
    if not model_id or len(model_id) > 240:
        raise HTTPException(422, detail="model_id is required and must be at most 240 characters")
    reasoning_effort = str(values.get("reasoning_effort", "")).strip().lower()
    if reasoning_effort not in REASONING_EFFORTS:
        raise HTTPException(422, detail="reasoning_effort must be minimal, low, medium, high, or empty")
    return {
        "provider": provider,
        "base_url": base_url,
        "model_id": model_id,
        "temperature": _parse_float(values.get("temperature", DEFAULTS["temperature"]), field="temperature", low=0, high=2),
        "top_p": _parse_float(values.get("top_p", DEFAULTS["top_p"]), field="top_p", low=0, high=1),
        "max_tokens": _parse_int(values.get("max_tokens", DEFAULTS["max_tokens"]), field="max_tokens", low=1, high=32768),
        "reasoning_effort": reasoning_effort,
    }


async def profiles() -> dict[str, list[dict[str, Any]]]:
    from services.state_store import get_settings_metadata

    metadata = await get_settings_metadata()
    result = []
    for role in ROLES:
        value = {
            "role": role,
            "name": ROLE_NAMES[role],
            "provider": str(_metadata_value(metadata, _key(role, "provider"), DEFAULTS["provider"])),
            "base_url": str(_metadata_value(metadata, _key(role, "base_url"), DEFAULTS["base_url"])),
            "model_id": str(_metadata_value(metadata, _key(role, "model_id"), DEFAULTS["model_id"])),
            "temperature": float(_metadata_value(metadata, _key(role, "temperature"), DEFAULTS["temperature"])),
            "top_p": float(_metadata_value(metadata, _key(role, "top_p"), DEFAULTS["top_p"])),
            "max_tokens": int(_metadata_value(metadata, _key(role, "max_tokens"), DEFAULTS["max_tokens"])),
            "reasoning_effort": str(_metadata_value(metadata, _key(role, "reasoning_effort"), DEFAULTS["reasoning_effort"])),
            "api_key_configured": bool(metadata.get(_key(role, "api_key"), {}).get("configured", False)),
        }
        result.append(value)
    return {"profiles": result}


async def save(role: str, values: dict[str, Any]) -> dict[str, Any]:
    _role_or_404(role)
    normalized = validate_update(values)
    updates = {_key(role, name): str(value) for name, value in normalized.items()}
    if values.get("clear_api_key"):
        updates[_key(role, "api_key")] = ""
    elif values.get("api_key") is not None:
        api_key = str(values["api_key"]).strip()
        if api_key:
            updates[_key(role, "api_key")] = api_key
    from services.state_store import save_settings

    await save_settings(updates)
    return next(item for item in (await profiles())["profiles"] if item["role"] == role)
