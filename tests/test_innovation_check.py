"""Innovation/novelty gate: UI→API→persistence→artifact evidence."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def test_innovation_gate_blocks_low_novelty_and_accepts_override(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.hypothesis_lifecycle as hypothesis
    import services.innovation_check as innovation

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    old_db = store.DB_PATH
    old_ws = {
        contracts: contracts.WORKSPACES_DIR,
        hypothesis: hypothesis.WORKSPACES_DIR,
        innovation: innovation.WORKSPACES_DIR,
    }
    store.DB_PATH = tmp_path / "innovation.db"
    contracts.WORKSPACES_DIR = workspace
    hypothesis.WORKSPACES_DIR = workspace
    innovation.WORKSPACES_DIR = workspace

    async def go():
        await store.init_db()
        project = await contracts.create_contract(
            "Novelty Study",
            "Does structured novelty scoring improve evidence-native research?",
            "peer-reviewed experimental reports only",
        )
        project_id = project["id"]

        missing = await innovation.read(project_id)
        assert missing["status"] == "missing"
        assert missing["gate"]["passed"] is False
        assert any(item["code"] == "missing_innovation_check" for item in missing["findings"])

        version = await hypothesis.create(
            project_id,
            {
                "statement": "Structured novelty scoring improves evidence-native research workflows",
                "mechanism": "Claim-level prior-art overlap and researcher override gates",
                "prediction": "Projects with scored novelty reports pass assurance more reliably",
                "falsification_criteria": "No improvement in gate pass rate after three replications",
                "boundary_conditions": "desktop research workbench only",
            },
            "researcher",
            "register primary hypothesis",
        )
        frozen = await hypothesis.transition(
            project_id, version["id"], "freeze", "researcher", "lock for novelty check"
        )
        assert frozen["status"] == "frozen"

        # Closest prior art reuses the claim wording so the deterministic scorer
        # must produce LOW novelty without inventing sources.
        blocked = await innovation.run(
            project_id,
            actor="researcher",
            claims=[
                "Structured novelty scoring improves evidence-native research workflows with claim-level prior-art overlap"
            ],
            overrides={},
            provider=None,
        )
        assert blocked["gate"]["passed"] is False
        assert blocked["gate"]["status"] == "blocked"
        assert blocked["gate"]["reason"] == "empty_novelty_corpus"
        assert any(item["code"] == "empty_novelty_corpus" for item in blocked["findings"])

        # Seed a near-duplicate card only for the independent LOW-novelty branch.
        db = await store.get_db()
        try:
            card_id = "card-near-dup"
            await db.execute(
                "INSERT INTO evidence_cards "
                "(id,project_id,identity,title,authors_json,doi,canonical_url,citation_status,claim_support_status) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    card_id,
                    project_id,
                    "title:structured novelty scoring improves evidence-native research workflows",
                    "Structured novelty scoring improves evidence-native research workflows with claim-level prior-art overlap",
                    json.dumps(["Prior Author"], ensure_ascii=False),
                    None,
                    "https://example.test/prior-art",
                    "approved",
                    "approved",
                ),
            )
            await db.commit()
        finally:
            await db.close()

        blocked = await innovation.run(
            project_id,
            actor="researcher",
            claims=[
                "Structured novelty scoring improves evidence-native research workflows with claim-level prior-art overlap"
            ],
            overrides={},
            provider=None,
        )
        assert blocked["gate"]["passed"] is False
        assert "N1" in blocked["gate"]["low_novelty_claim_ids"]
        report_path = workspace / project_id / blocked["artifact"]["path"]
        assert report_path.is_file()
        assert hashlib.sha256(report_path.read_bytes()).hexdigest() == blocked["artifact"]["sha256"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["gate"]["passed"] is False
        assert report["claims"][0]["text"].startswith("Structured novelty scoring")

        passed = await innovation.run(
            project_id,
            actor="researcher",
            claims=[
                "Structured novelty scoring improves evidence-native research workflows with claim-level prior-art overlap"
            ],
            overrides={"N1": "Differs by requiring immutable report hash and human override ledger."},
            provider=None,
        )
        assert passed["gate"]["passed"] is True
        assert passed["overrides"]["N1"]
        assert any(item["code"] == "low_novelty_overridden" for item in passed["findings"])
        current = await innovation.read(project_id)
        assert current["gate"]["passed"] is True
        assert current["artifact"]["sha256"] == passed["artifact"]["sha256"]

        snap = await innovation.snapshot_for_assurance(project_id)
        assert snap["gate_passed"] is True
        assert snap["file_sha256"] == snap["sha256"]

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        for module, value in old_ws.items():
            module.WORKSPACES_DIR = value


def test_innovation_check_http_routes(tmp_path, monkeypatch):
    import services.state_store as store
    import services.secret_store as secrets
    import services.research_contracts as contracts
    import services.hypothesis_lifecycle as hypothesis
    import services.innovation_check as innovation
    from fastapi.testclient import TestClient
    from services.local_session import TOKEN_ENV, TOKEN_HEADER

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    store.DB_PATH = tmp_path / "innovation-http.db"
    secrets._STORE = None  # type: ignore[attr-defined]
    contracts.WORKSPACES_DIR = workspace
    hypothesis.WORKSPACES_DIR = workspace
    innovation.WORKSPACES_DIR = workspace
    monkeypatch.setenv("VIBE_USER_DATA_ROOT", str(tmp_path / "user-data"))
    monkeypatch.setenv(TOKEN_ENV, "innovation-http-token")

    import asyncio
    from main import app

    asyncio.run(store.init_db())
    client = TestClient(app)
    headers = {TOKEN_HEADER: "innovation-http-token"}

    project = client.post(
        "/api/research-projects",
        headers=headers,
        json={
            "title": "HTTP Novelty",
            "research_question": "Can novelty checks be persisted through the research API?",
            "inclusion_criteria": "desktop projects only",
        },
    ).json()
    project_id = project["id"]
    missing = client.get(f"/api/research-projects/{project_id}/innovation-check", headers=headers)
    assert missing.status_code == 200
    assert missing.json()["status"] == "missing"

    created = client.post(
        f"/api/research-projects/{project_id}/hypotheses",
        headers=headers,
        json={
            "statement": "Persisted novelty checks block unsupported LOW claims",
            "mechanism": "Deterministic overlap scoring against verified evidence",
            "prediction": "Assurance remains blocked until override or rewrite",
            "falsification_criteria": "LOW claim passes without override",
            "boundary_conditions": "HTTP contract tests only",
            "actor": "researcher",
            "change_reason": "register",
        },
    )
    assert created.status_code == 200
    version_id = created.json()["hypotheses"][0]["id"]
    frozen = client.post(
        f"/api/research-projects/{project_id}/hypotheses/{version_id}/freeze",
        headers=headers,
        json={"actor": "researcher", "reason": "lock"},
    )
    assert frozen.status_code == 200

    run = client.post(
        f"/api/research-projects/{project_id}/innovation-check",
        headers=headers,
        json={
            "actor": "researcher",
            "claims": ["A distinctly framed contribution about immutable novelty ledgers for desktop research"],
            "overrides": {},
        },
    )
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "blocked"
    assert body["gate"]["passed"] is False
    assert any(item["code"] == "empty_novelty_corpus" for item in body["findings"])
    assert body["artifact"]["path"].endswith("innovation-check-report.json")
    assert Path(workspace / project_id / body["artifact"]["path"]).is_file()
    assert body["gate"]["total_claims"] == 1


def test_innovation_gate_blocks_empty_corpus(tmp_path):
    import asyncio
    import services.state_store as store
    import services.research_contracts as contracts
    import services.hypothesis_lifecycle as hypothesis
    import services.innovation_check as innovation

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    old_db = store.DB_PATH
    old_ws = {contracts: contracts.WORKSPACES_DIR, hypothesis: hypothesis.WORKSPACES_DIR, innovation: innovation.WORKSPACES_DIR}
    store.DB_PATH = tmp_path / "empty.db"
    contracts.WORKSPACES_DIR = hypothesis.WORKSPACES_DIR = innovation.WORKSPACES_DIR = workspace
    async def go():
        await store.init_db()
        project = await contracts.create_contract("Empty", "Does empty corpus pass?", "real sources")
        version = await hypothesis.create(project["id"], {"statement": "A sufficiently long hypothesis statement", "mechanism": "A mechanism", "prediction": "A prediction", "falsification_criteria": "A falsifier", "boundary_conditions": "A boundary"}, "researcher", "register")
        await hypothesis.transition(project["id"], version["id"], "freeze", "researcher", "freeze")
        result = await innovation.run(project["id"], claims=["A sufficiently long novelty claim"], provider=None)
        assert result["status"] == "blocked"
        assert result["gate"]["passed"] is False
        assert any(item["code"] == "empty_novelty_corpus" for item in result["findings"])
    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        for module, value in old_ws.items(): module.WORKSPACES_DIR = value


def test_innovation_provider_failure_has_root_cause(tmp_path, monkeypatch):
    """Provider outages must surface PROVIDER_FAILURE and never invent PASS."""
    import asyncio
    import services.state_store as store
    import services.research_contracts as contracts
    import services.hypothesis_lifecycle as hypothesis
    import services.innovation_check as innovation

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    old_db = store.DB_PATH
    old_ws = {
        contracts: contracts.WORKSPACES_DIR,
        hypothesis: hypothesis.WORKSPACES_DIR,
        innovation: innovation.WORKSPACES_DIR,
    }
    store.DB_PATH = tmp_path / "provider-fail.db"
    contracts.WORKSPACES_DIR = hypothesis.WORKSPACES_DIR = innovation.WORKSPACES_DIR = workspace

    async def _boom(query: str, provider: str | None):
        return [], {
            "root_cause": "PROVIDER_FAILURE",
            "provider": provider or "semantic_scholar",
            "error_type": "TimeoutError",
            "message": "forced provider outage",
        }

    monkeypatch.setattr(innovation, "_provider_records", _boom)

    async def go():
        await store.init_db()
        project = await contracts.create_contract(
            "Provider Outage",
            "Does provider failure invent novelty PASS?",
            "real sources",
        )
        version = await hypothesis.create(
            project["id"],
            {
                "statement": "A sufficiently long hypothesis statement about novelty ledgers",
                "mechanism": "A mechanism",
                "prediction": "A prediction",
                "falsification_criteria": "A falsifier",
                "boundary_conditions": "A boundary",
            },
            "researcher",
            "register",
        )
        await hypothesis.transition(project["id"], version["id"], "freeze", "researcher", "freeze")
        result = await innovation.run(
            project["id"],
            claims=["A sufficiently long novelty claim about immutable novelty ledgers"],
            provider="semantic_scholar",
        )
        assert result["status"] == "blocked"
        assert result["gate"]["passed"] is False
        assert result.get("provider_failure", {}).get("root_cause") == "PROVIDER_FAILURE"
        assert any(item.get("code") == "provider_failure" for item in result["findings"])
        assert any(item.get("root_cause") == "PROVIDER_FAILURE" for item in result["findings"])

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        for module, value in old_ws.items():
            module.WORKSPACES_DIR = value
