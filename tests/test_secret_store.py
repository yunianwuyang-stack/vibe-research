from __future__ import annotations

import asyncio
from pathlib import Path


def test_secret_store_round_trip_clear_and_no_plaintext(tmp_path):
    from services.secret_store import SecretStore

    path = tmp_path / "secrets.json"
    store = SecretStore(path, b"test-machine-secret")
    store.set("editor_ai_api_key", "very-secret-value")
    assert store.get("editor_ai_api_key") == "very-secret-value"
    assert "very-secret-value" not in path.read_text(encoding="utf-8")
    store.clear("editor_ai_api_key")
    assert store.get("editor_ai_api_key") == ""


def test_settings_keep_secret_out_of_sqlite_and_return_masked_metadata(tmp_path, monkeypatch):
    import services.secret_store as secret_store
    import services.state_store as state_store

    old_db = state_store.DB_PATH
    store = secret_store.SecretStore(tmp_path / "secrets.json", b"isolated-machine-secret")
    monkeypatch.setattr(secret_store, "_default_store", store)
    state_store.DB_PATH = tmp_path / "settings.db"

    async def exercise():
        await state_store.init_db()
        await state_store.save_settings({"editor_ai_api_key": "very-secret-value", "editor_ai_base_url": "https://example.test"})
        metadata = await state_store.get_settings_metadata()
        actual = await state_store.get_all_settings()
        db = await state_store.get_db()
        try:
            row = await (await db.execute("SELECT value FROM settings WHERE key='editor_ai_api_key'")).fetchone()
        finally:
            await db.close()
        return metadata, actual, row["value"]

    try:
        metadata, actual, stored = asyncio.run(exercise())
    finally:
        state_store.DB_PATH = old_db

    assert metadata["editor_ai_api_key"] == {"configured": True}
    assert actual["editor_ai_api_key"] == "very-secret-value"
    assert stored == "__secret_configured__"
    assert "very-secret-value" not in (tmp_path / "settings.db").read_bytes().decode("latin1")
