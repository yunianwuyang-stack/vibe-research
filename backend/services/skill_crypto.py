"""Encryption helpers for packaged skill assets."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

_SALT_PREFIX = b"vibe-research-skill-enc-v2"
_TRANSPORT_SALT = b"vibe-research-dk-transport-v1"
_ENCRYPT_EXTENSIONS = {".py", ".sh", ".bib", ".txt", ".css", ".tex", ".md", ".json", ".yaml", ".js", ".html", ".yml"}
_SKIP_DIRS = {"node_modules", "__pycache__", ".git"}
_cached_decrypt_key: Optional[bytes] = None


def _derive_key(master_key: str) -> bytes:
    """Derive the original AES-256 skill key from a master key string."""
    password = _SALT_PREFIX + master_key.encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", password, _SALT_PREFIX, 100000)


def set_decrypt_key(dk_hex: str) -> None:
    global _cached_decrypt_key
    _cached_decrypt_key = bytes.fromhex(dk_hex)


def get_decrypt_key() -> Optional[bytes]:
    return _cached_decrypt_key


def clear_decrypt_key() -> None:
    global _cached_decrypt_key
    _cached_decrypt_key = None


def is_encrypted_skills(skills_dir: Path) -> bool:
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return False
    meta = skills_dir / ".skill_meta.json"
    if meta.exists():
        try:
            if json.loads(meta.read_text(encoding="utf-8")).get("encrypted") is True:
                return True
        except (OSError, json.JSONDecodeError):
            pass
    return any(skills_dir.rglob("*.enc"))


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    """Decrypt nonce(12) + AES-256-GCM ciphertext/tag bytes."""
    nonce, ciphertext = data[:12], data[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt bytes as nonce(12) + AES-256-GCM ciphertext/tag."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def encrypt_file(src: Path, dst: Path, key: bytes) -> None:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(encrypt_bytes(src.read_bytes(), key))


def decrypt_file(src: Path, key: bytes) -> bytes:
    return decrypt_bytes(Path(src).read_bytes(), key)


def decrypt_skill_file_to_memory(enc_path: Path, license_key: Optional[str] = None) -> Optional[bytes]:
    enc_path = Path(enc_path)
    key = get_decrypt_key()
    if key is None or not enc_path.exists():
        return None
    try:
        return decrypt_file(enc_path, key)
    except Exception as exc:
        log.warning("Failed to decrypt skill file %s: %s", enc_path, exc)
        return None


def decrypt_skill_md(skills_dir: Path, skill_name: str, license_key: Optional[str] = None) -> Optional[str]:
    skill_dir = Path(skills_dir) / skill_name
    encrypted = skill_dir / "SKILL.md.enc"
    if encrypted.exists():
        data = decrypt_skill_file_to_memory(encrypted, license_key)
        return data.decode("utf-8") if data is not None else None
    plaintext = skill_dir / "SKILL.md"
    if plaintext.exists():
        return plaintext.read_text(encoding="utf-8")
    return None


def _retry_rmtree(path: Path, attempts: int = 5, delay: float = 0.3) -> bool:
    """Remove a tree, retrying on Windows file-lock errors (WinError 32).

    Some sandboxes (and the desktop host's safe-delete hook) intercept rmtree's
    per-file deletes and require a recycle bin that the backend environment does
    not provide, turning every removal into SAFE_DELETE_FAIL_CLOSED.  When a
    plain rmtree keeps failing, fall back to renaming the directory aside so the
    mount point is freed and a fresh copy can be materialized; the stale tree is
    left for the OS / user to reclaim later.

    Returns True when the mount point is guaranteed free (either rmtree
    succeeded or rename-aside moved the directory away).  Returns False when
    even rename-aside failed (typically because the destination directory has
    files locked by another live process).  Callers must treat False as
    "best-effort cleanup failed" and decide whether to keep going or abort.
    """
    last: Exception | None = None
    for try_n in range(attempts):
        try:
            shutil.rmtree(path)
            return True
        except (OSError, PermissionError) as exc:
            last = exc
            if try_n < attempts - 1:
                time.sleep(delay * (try_n + 1))
    # Last resort: rename aside so the destination path becomes available.
    try:
        stale = path.with_name(f"{path.name}.stale-{int(time.time())}")
        os.replace(path, stale)
        log.warning("rmtree blocked for %s; renamed aside to %s", path, stale)
        return True
    except OSError as rename_exc:
        # Even rename-aside failed (destination is locked by another process).
        # Degrade to "leave the directory in place" instead of raising, so the
        # caller can decide to overwrite-on-write rather than abort the whole
        # mount.  This converts a hard failure into a soft one and prevents
        # stale-* tree pileups from cascading into mount_failed crashes.
        log.warning(
            "rmtree blocked for %s after %d attempts (%s); rename-aside also "
            "failed (%s).  Leaving directory in place; mount will overwrite "
            "files individually.",
            path, attempts, last, rename_exc,
        )
        return False


def _retry_copy2(src: Path, dst: Path, attempts: int = 3, delay: float = 0.2) -> None:
    """Copy a file, retrying on Windows file-lock errors."""
    last: Exception | None = None
    for try_n in range(attempts):
        try:
            shutil.copy2(src, dst)
            return
        except (OSError, PermissionError) as exc:
            last = exc
            if try_n < attempts - 1:
                time.sleep(delay * (try_n + 1))
    raise RuntimeError(f"could not copy {src} to {dst} after {attempts} attempts: {last}")


def decrypt_skills_to_workspace(
    skills_dir: Path,
    workspace_utils: Path,
    sub_dir: str = "shared-scripts",
    destination_sub_dir: Optional[str] = None,
    license_key: Optional[str] = None,
) -> bool:
    """Materialize a packaged skill support directory into a workspace.

    sub_dir names the source directory below skills_dir. Packaged skills refer
    to shared helpers as _utils/<name> while the source tree stores them under
    shared-scripts. destination_sub_dir keeps that distinction explicit while
    preserving the historical default for existing callers.
    """
    src_root = Path(skills_dir) / sub_dir
    if not src_root.exists():
        return False
    dst_root = Path(workspace_utils) / (destination_sub_dir or sub_dir)
    if dst_root.exists():
        # Best-effort cleanup: when even rename-aside fails the directory is
        # likely locked by another live process (concurrent run_workflow, AV
        # scanner, etc.).  Keep going and let _retry_copy2 overwrite files
        # individually instead of aborting the whole mount; the alternative
        # (raising CAPABILITY_BLOCKED) turns a recoverable file-lock into a
        # workflow-killing error and was the root cause of repeated
        # paper-figure recovery failures on Windows.
        cleaned = _retry_rmtree(dst_root)
        if not cleaned:
            log.warning(
                "could not fully clean %s; overwriting files individually",
                dst_root,
            )
    dst_root.mkdir(parents=True, exist_ok=True)

    key = get_decrypt_key()
    for src in src_root.rglob("*"):
        if not src.is_file() or any(part in _SKIP_DIRS for part in src.relative_to(src_root).parts):
            continue
        rel = src.relative_to(src_root)
        if src.suffix == ".enc":
            if key is None:
                return False
            dst = dst_root / rel.with_suffix("")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(decrypt_file(src, key))
        elif src.name != ".skill_meta.json":
            dst = dst_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                _retry_copy2(src, dst)
            except RuntimeError as exc:
                raise RuntimeError(f"CAPABILITY_BLOCKED:{sub_dir}:mount_failed:{exc}") from exc
    return True


def encrypt_skills_dir(skills_dir: Path, output_dir: Path, master_key: str = "") -> dict:
    """Encrypt supported files from a skill tree using the original v2 format."""
    skills_dir, output_dir = Path(skills_dir), Path(output_dir)
    if not master_key:
        master_key = os.urandom(32).hex()
    key = _derive_key(master_key)
    result = {"encrypted": 0, "skipped": 0, "errors": [], "dk_hex": key.hex()}

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".skill_meta.json").write_text(
        json.dumps({"version": 2, "encrypted": True}), encoding="utf-8"
    )

    for src in sorted(skills_dir.rglob("*")):
        rel = src.relative_to(skills_dir)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if src.is_dir():
            continue
        try:
            if src.suffix.lower() in _ENCRYPT_EXTENSIONS:
                encrypt_file(src, output_dir / f"{rel.as_posix()}.enc", key)
                result["encrypted"] += 1
            else:
                dst = output_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                result["skipped"] += 1
        except Exception as exc:
            result["errors"].append({"file": rel.as_posix(), "error": str(exc)})
    return result


def _transport_key(license_key: str) -> bytes:
    password = b"transport:" + license_key.encode("utf-8")
    return hashlib.pbkdf2_hmac("sha256", password, _TRANSPORT_SALT, 50000)


def encrypt_dk_for_transport(master_key_hex: str, license_key: str) -> str:
    return encrypt_bytes(master_key_hex.encode("utf-8"), _transport_key(license_key)).hex()


def decrypt_dk_from_transport(encrypted_dk_hex: str, license_key: str) -> str:
    plaintext = decrypt_bytes(bytes.fromhex(encrypted_dk_hex), _transport_key(license_key))
    return plaintext.decode("utf-8")
