"""Prompt template loading and rendering."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_PROMPT_DIR = Path(__file__).resolve().parent
_PROMPT_CACHE: dict[str, str] = {}


def load_prompt(name: str, **vars: Any) -> str:
    """(docstring)"""
    if not name.endswith(".md"):
        name = name + ".md"

    if name in _PROMPT_CACHE:
        template = _PROMPT_CACHE[name]
    else:
        template_path = _PROMPT_DIR / name
        if not template_path.exists():
            log.error("Prompt template not found: %s", template_path)
            raise FileNotFoundError(f"Prompt template not found: {template_path}")
        template = template_path.read_text(encoding="utf-8")
        _PROMPT_CACHE[name] = template


    for key, value in vars.items():
        template = template.replace("{" + key + "}", str(value))

    return template


def list_prompts() -> list[str]:
    """(docstring)"""
    return [f.stem for f in _PROMPT_DIR.glob("*.md")]


def clear_cache() -> None:
    """(docstring)"""
    _PROMPT_CACHE.clear()
