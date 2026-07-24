"""Source-mode backend must honor VIBE_USER_DATA_ROOT for settings/workspaces."""
from __future__ import annotations

import importlib
import os
from pathlib import Path


def test_source_mode_user_data_root_override(tmp_path, monkeypatch):
    root = tmp_path / "custom-user-data"
    monkeypatch.setenv("VIBE_USER_DATA_ROOT", str(root))
    monkeypatch.delenv("VIBE_DESKTOP", raising=False)
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)

    import config

    importlib.reload(config)

    assert config.DB_PATH == (root / "db" / "vibe.db").resolve()
    assert config.WORKSPACES_DIR == (root / "workspaces").resolve()
    assert config.DB_PATH.parent.exists()
    assert config.WORKSPACES_DIR.exists()


def test_legacy_aris_db_promotes_to_vibe_db(tmp_path, monkeypatch):
    root = tmp_path / "legacy-user"
    db_dir = root / "db"
    db_dir.mkdir(parents=True)
    legacy = db_dir / "aris.db"
    legacy.write_bytes(b"legacy-ledger")
    monkeypatch.setenv("VIBE_USER_DATA_ROOT", str(root))
    monkeypatch.delenv("VIBE_DESKTOP", raising=False)
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)

    import config
    import importlib

    importlib.reload(config)

    assert config.DB_PATH == (db_dir / "vibe.db").resolve()
    assert config.DB_PATH.is_file()
    assert config.DB_PATH.read_bytes() == b"legacy-ledger"
    assert not legacy.exists()
