import hashlib

def test_adapter_manifest_reports_official_discovery_without_embedded_binaries(monkeypatch, tmp_path):
    from services.agent_bundle import build_adapter_manifest
    codex = tmp_path / "codex.exe"
    codex.write_bytes(b"codex")
    monkeypatch.setattr("services.agent_bundle.shutil.which", lambda command: str(codex) if command == "codex" else None)
    monkeypatch.setattr("services.agent_bundle._version", lambda executable: "1.2.3")
    # Host PATH discovery only (no packaged runtime root).
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("VIBE_PACKAGED_RUNTIME", raising=False)
    monkeypatch.setattr("services.agent_bundle._default_runtime_root", lambda: None)
    manifest = build_adapter_manifest()
    assert manifest["schema_version"] == "2.0"
    assert manifest["adapters"]["codex"]["status"] == "available"
    assert manifest["adapters"]["codex"]["sha256"] == hashlib.sha256(b"codex").hexdigest()
    assert manifest["adapters"]["claude"]["status"] == "unavailable"
    assert manifest["adapters"]["claude"]["action"]["kind"] == "official_install"
    assert manifest["embedded_binaries"] == []

def test_adapter_manifest_never_claims_authentication(monkeypatch):
    from services.agent_bundle import build_adapter_manifest
    monkeypatch.setattr("services.agent_bundle.shutil.which", lambda command: None)
    monkeypatch.setattr("services.agent_bundle._default_runtime_root", lambda: None)
    entry = build_adapter_manifest()["adapters"]["codex"]
    assert entry["auth_status"] == "unknown"
    assert entry["redistribution"] == "not_bundled"


def test_agent_manifest_endpoint_is_registered():
    from main import app
    assert any(getattr(route, 'path', None) == '/api/agents/manifest' for route in app.routes)
