from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from models.editor_contracts import CAPABILITY_UNAVAILABLE, EDITOR_ENDPOINT_CONTRACTS
from routers.editor import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _request(client: TestClient, method: str, route: str):
    path = route.replace("{wf_id}", "contract-wf")
    if method == "GET":
        params = {}
        if route.endswith("/file-preview-html") or route.endswith("/stats"):
            params["path"] = "paper/main.md"
        return client.get(path, params=params)
    if method == "DELETE":
        return client.delete(path, params={"path": "paper/main.md"})
    if route.endswith("/create-file"):
        return client.post(path, json={"path": "paper/new.md"})
    if route.endswith("/drawio-export"):
        return client.post(path, json={"source": "<mxfile/>", "format": "pdf"})
    if route.endswith("/mermaid-export"):
        return client.post(path, json={"source": "flowchart LR;A-->B;", "format": "svg"})
    if route.endswith("/generate-image"):
        return client.post(path, json={"prompt": "diagram", "model": "gpt-image-1"})
    if route.endswith("/compile"):
        return client.post(path, json={"source_md": "# paper"})
    if route.endswith("/ai-agent-apply"):
        return client.post(path, json={"files": []})
    if route.endswith("/ai-agent"):
        return client.post(path, json={"message": "test"})
    if route.endswith("/ai-agent-stage"):
        return client.post(path, json={"path": "paper/main.md", "content": "proposal"})
    if route.endswith("/describe-image"):
        return client.post(path, params={"path": "figure.png"})
    return client.post(path)


def test_editor_contract_map_covers_every_route_once():
    registered = {
        f"{method} {route.path}"
        for route in router.routes
        for method in route.methods
    }
    assert registered == set(EDITOR_ENDPOINT_CONTRACTS)
    assert len(registered) == 30


def test_unavailable_editor_endpoints_are_structured_501_not_false_success():
    client = _client()
    for key, contract in EDITOR_ENDPOINT_CONTRACTS.items():
        if contract["status"] != "unavailable":
            continue
        method, route = key.split(" ", 1)
        response = _request(client, method, route)
        assert response.status_code == 501, key
        detail = response.json()["detail"]
        assert detail == {"code": CAPABILITY_UNAVAILABLE, "reason": contract["reason"]}
        assert response.json().get("ok") is not True


def test_implemented_routes_are_explicitly_classified():
    assert all(
        contract["status"] in {"implemented", "unavailable"}
        for contract in EDITOR_ENDPOINT_CONTRACTS.values()
    )
    assert EDITOR_ENDPOINT_CONTRACTS["POST /api/editor/{wf_id}/mermaid-export"]["status"] == "implemented"


def test_editor_file_crud_preview_download_and_stats(monkeypatch, tmp_path):
    import services.editor_ai as editor_ai

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    client = _client()
    base = "/api/editor/contract-wf"

    created = client.post(f"{base}/create-file", json={"path": "paper/main.md"})
    assert created.status_code == 200 and created.json() == {"ok": True}
    saved = client.put(f"{base}/file", json={"path": "paper/main.md", "content": "# Title\nA short paper."})
    assert saved.status_code == 200
    preview = client.get(f"{base}/file-preview-html", params={"path": "paper/main.md"})
    assert preview.status_code == 200 and "&lt;" not in preview.json()["html"]
    stats = client.get(f"{base}/stats", params={"path": "paper/main.md"})
    assert stats.status_code == 200 and stats.json()["words"] == 5
    downloaded = client.get(f"{base}/download", params={"path": "paper/main.md"})
    assert downloaded.status_code == 200 and downloaded.text.replace("\r\n", "\n") == "# Title\nA short paper."
    deleted = client.delete(f"{base}/file", params={"path": "paper/main.md"})
    assert deleted.status_code == 200 and deleted.json() == {"ok": True}


@pytest.mark.parametrize("method,path", [("post", "/create-file"), ("put", "/file"), ("delete", "/file")])
def test_editor_paths_reject_workspace_traversal(monkeypatch, tmp_path, method, path):
    import services.editor_ai as editor_ai

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    client = _client()
    base = "/api/editor/contract-wf"
    if method == "post":
        response = client.post(base + path, json={"path": "../escape.txt"})
    elif method == "put":
        response = client.put(base + path, json={"path": "../escape.txt", "content": "bad"})
    else:
        response = client.delete(base + path, params={"path": "../escape.txt"})
    assert response.status_code == 400


def test_agent_staging_apply_discard_undo_and_provider_unavailable(monkeypatch, tmp_path):
    import services.editor_ai as editor_ai
    import services.llm_client as llm_client

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)

    async def _empty_settings():
        return {}

    monkeypatch.setattr(llm_client, "get_all_settings", _empty_settings)
    workspace = tmp_path / "agent-wf" / "paper"
    workspace.mkdir(parents=True)
    (workspace / "main.md").write_text("original", encoding="utf-8")
    client = _client()
    base = "/api/editor/agent-wf"

    # Missing editor_ai credentials must surface a structured 501 — never a false success.
    provider = client.post(f"{base}/ai-agent", json={"message": "edit it"})
    assert provider.status_code == 501
    assert provider.json()["detail"]["code"] == CAPABILITY_UNAVAILABLE

    staged = client.post(f"{base}/ai-agent-stage", json={"path": "paper/main.md", "content": "proposed"})
    assert staged.status_code == 200
    proposal = staged.json()
    assert proposal["status"] == "staged" and proposal["base_hash"] and "-original" in proposal["proposed_diff"]
    checked = client.get(f"{base}/ai-agent-check")
    assert checked.status_code == 200 and checked.json()["has_diff"] is True
    applied = client.post(f"{base}/ai-agent-apply", json={"files": ["paper/main.md"]})
    assert applied.status_code == 200
    assert (workspace / "main.md").read_text(encoding="utf-8") == "proposed"
    undone = client.post(f"{base}/ai-agent-undo")
    assert undone.status_code == 200
    assert (workspace / "main.md").read_text(encoding="utf-8") == "original"
    assert client.post(f"{base}/ai-agent-discard").status_code == 200
    assert client.post(f"{base}/ai-agent-stop").json()["stopped"] is False


def test_agent_provider_stages_reviewable_proposals(monkeypatch, tmp_path):
    """Configured editor_ai provider must stage real proposals through UI→API→service."""
    import services.editor_ai as editor_ai
    import services.llm_client as llm_client

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "agent-ok" / "paper"
    workspace.mkdir(parents=True)
    (workspace / "main.md").write_text("original draft", encoding="utf-8")

    async def _configured_settings():
        return {
            "editor_ai_api_key": "test-key",
            "editor_ai_base_url": "https://example.test/v1",
            "editor_ai_model_id": "gpt-test",
            "editor_ai_provider": "openai_compatible",
        }

    async def _fake_call_llm(agent: str, prompt: str, timeout: int = 300) -> str:
        assert agent == "editor_ai"
        assert "original draft" in prompt
        return (
            'Here is the edit:\n'
            '{"summary":"Tighten the abstract.","files":['
            '{"path":"paper/main.md","content":"revised abstract"}'
            "]}"
        )

    monkeypatch.setattr(llm_client, "get_all_settings", _configured_settings)
    monkeypatch.setattr(llm_client, "call_llm", _fake_call_llm)

    client = _client()
    base = "/api/editor/agent-ok"
    response = client.post(f"{base}/ai-agent", json={"message": "tighten abstract"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "staged"
    assert body["summary"] == "Tighten the abstract."
    assert body["changed_files"] == ["paper/main.md"]
    assert body["proposals"] and body["proposals"][0]["path"] == "paper/main.md"
    assert "-original draft" in body["proposals"][0]["proposed_diff"]
    assert "+revised abstract" in body["proposals"][0]["proposed_diff"]
    # Source file stays untouched until the researcher applies the proposal.
    assert (workspace / "main.md").read_text(encoding="utf-8") == "original draft"

    applied = client.post(f"{base}/ai-agent-apply", json={"files": ["paper/main.md"]})
    assert applied.status_code == 200
    assert (workspace / "main.md").read_text(encoding="utf-8") == "revised abstract"


def test_agent_apply_rejects_stale_base_hash(monkeypatch, tmp_path):
    import services.editor_ai as editor_ai

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "agent-stale" / "paper"
    workspace.mkdir(parents=True)
    target = workspace / "main.md"
    target.write_text("original", encoding="utf-8")
    client = _client()
    base = "/api/editor/agent-stale"
    assert client.post(f"{base}/ai-agent-stage", json={"path": "paper/main.md", "content": "proposed"}).status_code == 200
    target.write_text("external edit", encoding="utf-8")
    response = client.post(f"{base}/ai-agent-apply", json={"files": ["paper/main.md"]})
    assert response.status_code == 409
    assert target.read_text(encoding="utf-8") == "external edit"


def test_ai_edit_persists_chat_history_and_run_script_writes_audit(monkeypatch, tmp_path):
    """AI edit + chat history + allowlisted script must leave durable artifacts."""
    import services.editor_ai as editor_ai
    import services.llm_client as llm_client

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "edit-wf" / "paper"
    workspace.mkdir(parents=True)
    (workspace / "main.md").write_text("# Draft\noriginal body\n", encoding="utf-8")

    async def _configured_settings():
        return {
            "editor_ai_api_key": "test-key",
            "editor_ai_base_url": "https://example.test/v1",
            "editor_ai_model_id": "gpt-test",
            "editor_ai_provider": "openai_compatible",
        }

    async def _fake_call_llm(agent: str, prompt: str, timeout: int = 300) -> str:
        assert agent == "editor_ai"
        assert "original body" in prompt
        return "# Draft\nrevised body with tighter abstract\n"

    monkeypatch.setattr(llm_client, "get_all_settings", _configured_settings)
    monkeypatch.setattr(llm_client, "call_llm", _fake_call_llm)

    client = _client()
    base = "/api/editor/edit-wf"

    missing = client.post(
        f"{base}/ai-edit",
        json={
            "message": "tighten abstract",
            "current_file": "paper/main.md",
            "current_content": "# Draft\noriginal body\n",
            "workspace_files": ["paper/main.md"],
            "role": "markdown",
        },
    )
    # Without credentials the route must not fake success. Re-run after credentials
    # are present; the monkeypatched settings already provide them.
    assert missing.status_code == 200, missing.text
    body = missing.json()
    assert "revised body" in body["content"]
    assert body["history_path"] == "_chat_history.json"
    history_path = tmp_path / "edit-wf" / "_chat_history.json"
    assert history_path.is_file()
    history = history_path.read_text(encoding="utf-8")
    assert "tighten abstract" in history
    assert "revised body" in history

    listed = client.get(f"{base}/chat-history")
    assert listed.status_code == 200
    assert listed.json()["history"]
    assert listed.json()["history"][0]["request"] == "tighten abstract"

    cleared = client.delete(f"{base}/chat-history")
    assert cleared.status_code == 200 and cleared.json()["ok"] is True
    assert client.get(f"{base}/chat-history").json()["history"] == []

    scripted = client.post(
        f"{base}/run-script",
        json={"script": "print('VIBE_SCRIPT_OK')\n", "language": "python"},
    )
    assert scripted.status_code == 200, scripted.text
    payload = scripted.json()
    assert payload["success"] is True
    assert "VIBE_SCRIPT_OK" in payload["stdout"]
    audit_path = tmp_path / "edit-wf" / payload["audit"]["path"]
    assert audit_path.is_file()
    audit = audit_path.read_text(encoding="utf-8")
    assert "run_script" in audit
    assert "python" in audit


def test_ai_edit_without_credentials_returns_structured_501(monkeypatch, tmp_path):
    import services.editor_ai as editor_ai
    import services.llm_client as llm_client

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "edit-missing" / "paper"
    workspace.mkdir(parents=True)
    (workspace / "main.md").write_text("body", encoding="utf-8")

    async def _empty_settings():
        return {}

    monkeypatch.setattr(llm_client, "get_all_settings", _empty_settings)
    client = _client()
    response = client.post(
        "/api/editor/edit-missing/ai-edit",
        json={
            "message": "edit",
            "current_file": "paper/main.md",
            "current_content": "body",
            "workspace_files": ["paper/main.md"],
        },
    )
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == CAPABILITY_UNAVAILABLE


def test_mermaid_export_produces_offline_svg_artifact(monkeypatch, tmp_path):
    """Mermaid export must use the offline library + local browser and leave hashed artifacts."""
    import services.editor_ai as editor_ai

    monkeypatch.setattr(editor_ai, "WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "mermaid-wf"
    workspace.mkdir(parents=True)
    client = _client()
    response = client.post(
        "/api/editor/mermaid-wf/mermaid-export",
        json={
            "source": "flowchart LR\n  A[Research] --> B[Evidence]\n  B --> C[Claim]\n",
            "format": "svg",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["outputs"] and body["outputs"][0]["path"].endswith(".svg")
    svg_path = workspace / body["outputs"][0]["path"]
    assert svg_path.is_file()
    svg = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg and "viewBox" in svg
    manifest_path = workspace / body["manifest"]["path"]
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["operation"] == "mermaid_export"
    assert manifest["runtime"]["offline"] is True
    assert manifest["runtime"]["mermaid_library_sha256"]
    assert body["source"]["sha256"]
    # Reject external references instead of fetching the network.
    blocked = client.post(
        "/api/editor/mermaid-wf/mermaid-export",
        json={"source": "flowchart LR\n  A-->B\n  click A \"https://example.com\"\n", "format": "svg"},
    )
    assert blocked.status_code == 422
