"""Secret storage separated from the SQLite settings metadata table."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import DB_PATH


SECRET_KEYS = frozenset({
    "executor_api_key", "reviewer_api_key", "editor_ai_api_key", "minimax_api_key",
    "gemini_api_key", "gpt_image_api_key", "aminer_api_key",
})


class SecretStore:
    """File-backed encrypted store; SQLite sees only configured metadata."""

    def __init__(self, path: Path | None = None, machine_secret: bytes | None = None):
        self.path = path or DB_PATH.with_name("secrets.v1.json")
        self.key_path = self.path.with_name("secrets.v1.key")
        # Platform key providers and test fixtures can yield arbitrary opaque
        # bytes. Derive a stable AES-256 key whenever the supplied value is
        # not already an AES-GCM key length.
        raw_key = machine_secret or self._load_or_create_key()
        self.key = raw_key if len(raw_key) in {16, 24, 32} else hashlib.sha256(raw_key).digest()

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) != 32: raise ValueError("invalid secret-store key")
            return key
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle: handle.write(key)
        try: os.chmod(self.key_path, 0o600)
        except OSError: pass
        return key

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def set(self, key: str, value: str) -> None:
        values = self._load()
        nonce = os.urandom(12)
        values[key] = base64.b64encode(nonce + AESGCM(self.key).encrypt(nonce, value.encode(), key.encode())).decode()
        self._save(values)

    def get(self, key: str) -> str:
        value = self._load().get(key)
        if not value:
            return ""
        raw = base64.b64decode(value)
        return AESGCM(self.key).decrypt(raw[:12], raw[12:], key.encode()).decode()

    def clear(self, key: str) -> None:
        values = self._load()
        values.pop(key, None)
        self._save(values)


_default_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    global _default_store
    if _default_store is None:
        _default_store = SecretStore()
    return _default_store
