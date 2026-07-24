"""(docstring)"""
from __future__ import annotations

import importlib.util
import importlib.machinery
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CACHED_MODULE: Any = None
_INTERNAL_NAME = "_docx_export_internal"


def _resolve_source() -> Optional[Path]:
    """(docstring)"""
    from config import TOOLS_DIR
    base = TOOLS_DIR / "docx_export"
    candidates = [
        base.with_suffix(".py"),       # tools/docx_export.py
        base.with_suffix(".pyc"),      # tools/docx_export.pyc
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_docx_export():
    """(docstring)"""
    global _CACHED_MODULE
    if _CACHED_MODULE is not None:
        return _CACHED_MODULE

    source = _resolve_source()
    if source is None:
        log.warning("docx_export source not found in tools/")
        return None

    if source.suffix == ".pyc":

        loader = importlib.machinery.SourcelessFileLoader(_INTERNAL_NAME, str(source))
        spec = importlib.util.spec_from_loader(_INTERNAL_NAME, loader)
    else:

        loader = importlib.machinery.SourceFileLoader(_INTERNAL_NAME, str(source))
        spec = importlib.util.spec_from_loader(_INTERNAL_NAME, loader)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _CACHED_MODULE = module
    return module


def get_markdown_to_docx():
    """(docstring)"""
    mod = load_docx_export()
    if mod is None:
        return None
    return getattr(mod, "markdown_to_docx", None)
