"""(docstring)"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)


_dk_hex: Optional[str] = None


def check_license_local(is_desktop: bool) -> bool:
    """(docstring)"""
    return True


def verify_license_online(license_key: str, machine_id: str, is_desktop: bool) -> Tuple[bool, str, Optional[str]]:
    """(docstring)"""
    return True, "Unlocked without activation", None


def apply_dk_from_verify(dk_encrypted: Optional[str], license_key: str) -> None:
    """(docstring)"""
    pass


def save_license_local(license_key: str, machine_id: str, is_desktop: bool) -> None:
    """(docstring)"""
    pass


def renew_license_online(license_key: str, machine_id: str, is_desktop: bool) -> Tuple[bool, Optional[str]]:
    """(docstring)"""
    return True, None
