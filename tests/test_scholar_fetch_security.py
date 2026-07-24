from __future__ import annotations

import importlib.util
import ssl
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "scholar_fetch.py"
ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def load_module():
    spec = importlib.util.spec_from_file_location("scholar_fetch_security", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_tls_verification_is_never_bypassed(monkeypatch):
    module = load_module()
    calls = []

    def rejected(*args, **kwargs):
        calls.append((args, kwargs))
        raise ssl.SSLError("certificate verification failed")

    monkeypatch.setattr(module.urllib.request, "urlopen", rejected)
    assert module._http_get("https://example.invalid") is None
    assert len(calls) == 1
    assert "context" not in calls[0][1]


def test_aminer_without_key_makes_no_network_request(monkeypatch):
    monkeypatch.delenv("AMINER_API_KEY", raising=False)
    module = load_module()
    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")),
    )
    assert module.aminer_search("test query") == []


def test_source_has_no_tls_bypass_or_embedded_token():
    source = SOURCE.read_text(encoding="utf-8")
    forbidden = (
        "CERT_NONE",
        "_SSL_CTX_NOVERIFY",
        "check_hostname = False",
        "ssl._create_unverified_context",
        "create_unverified_context",
    )
    for marker in forbidden:
        assert marker not in source
    assert 'os.environ.get("AMINER_API_KEY", "")' in source


def test_env_example_keeps_aminer_credential_empty_and_documents_unavailability():
    env = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "AMINER_API_KEY=" in env
    assert "AMINER_API_KEY=<" not in env
    assert "capability unavailable" in env
    assert "never commit real credentials" in env