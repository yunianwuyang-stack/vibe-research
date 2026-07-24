"""Real UI→API→executor→persistence→artifact evidence for research quality gates."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _snapshot_client(title: str, authors: list[str], year: int, doi: str, url: str):
    import hashlib as _hashlib
    import json as _json
    from domain.evidence import SourceRecord

    class Client:
        def __init__(self, *a, **k):
            self.cache = Path(a[1])

        def _write(self, provider, query):
            records = [{"title": title, "authors": list(authors), "year": year, "doi": doi, "url": url}]
            self.cache.mkdir(parents=True, exist_ok=True)
            raw = _json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            path = self.cache / f"{provider}-{_hashlib.sha256(query.encode()).hexdigest()}.json"
            path.write_text(
                _json.dumps(
                    {
                        "provider": provider,
                        "query": query,
                        "retrieved_at": "now",
                        "records": records,
                        "content_sha256": _hashlib.sha256(raw).hexdigest(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return path, SourceRecord(provider, title, tuple(authors), year, doi, url, "now", query)

        def search(self, provider, query):
            _, record = self._write(provider, query)
            return [record]

        def replay_snapshot(self, provider, query):
            path, record = self._write(provider, query)
            return [record], hashlib.sha256(path.read_bytes()).hexdigest()

    return Client


def _patch_workspaces(modules, workspace: Path):
    old = {}
    for module in modules:
        old[module] = module.WORKSPACES_DIR
        module.WORKSPACES_DIR = workspace
    return old


def test_research_quality_loop_persists_gate_artifacts(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.hypothesis_lifecycle as hypothesis
    import services.evidence_screening as screening
    import services.claim_evidence as claim_evidence
    import services.scientific_narrative as narrative
    import services.approved_drafts as drafts
    import services.adversarial_review as adversarial
    import services.assurance as assurance
    import services.innovation_check as innovation

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    modules = (contracts, hypothesis, screening, claim_evidence, drafts, adversarial, innovation)
    old_db = store.DB_PATH
    old_ws = _patch_workspaces(modules, workspace)
    store.DB_PATH = tmp_path / "quality.db"
    monkeypatch.setattr(
        contracts,
        "LiteratureClient",
        _snapshot_client("Gate Paper", ["Researcher"], 2024, "10.1234/gate", "https://doi.org/10.1234/gate"),
    )

    async def go():
        await store.init_db()
        project = await contracts.create_contract("Gate Study", "Does the gate hold?", "peer-reviewed evidence")
        project_id = project["id"]

        blocked = await assurance.read(project_id)
        assert blocked["status"] == "BLOCKED"
        assert blocked["submission_ready"] is False
        assert any(item["code"] == "missing_independent_review" for item in blocked["findings"])

        project = await contracts.save_provider_evidence(
            project_id, "openalex", "gate query", "https://doi.org/10.1234/gate"
        )
        card = project["evidence_cards"][0]
        project = await contracts.review_evidence_card(project_id, card["id"], "researcher", "approved", "metadata verified")
        project = await contracts.review_claim_support(project_id, card["id"], "researcher", "approved", "full text supports claim")
        assert project["status"] == "ready_for_review"

        state = await screening.save_protocol(
            project_id,
            title="Peer-reviewed screening",
            inclusion_criteria="peer-reviewed experimental report",
            exclusion_criteria="preprint without peer review",
            source_strategy="provider snapshot + human decision",
            actor="researcher",
        )
        assert state["protocol"]["status"] == "draft"
        state = await screening.activate(project_id, "researcher")
        assert state["protocol"]["status"] == "active"
        state = await screening.decide(project_id, card["id"], "included", "matches inclusion criteria", "researcher")
        prisma = await screening.export_prisma(project_id)
        prisma_path = workspace / project_id / prisma["artifact"]["path"]
        assert prisma_path.is_file()
        assert hashlib.sha256(prisma_path.read_bytes()).hexdigest() == prisma["artifact"]["sha256"]
        assert prisma["prisma"]["flow"]["studies_included"] == 1
        assert prisma["prisma"]["flow"]["records_screened"] == 1

        version = await hypothesis.create(
            project_id,
            {
                "statement": "The intervention improves the measured outcome",
                "mechanism": "A measurable pathway under controlled conditions",
                "prediction": "Treatment mean exceeds control mean across seeds",
                "falsification_criteria": "No positive difference after three replications",
                "boundary_conditions": "numeric laboratory observations only",
            },
            "researcher",
            "register primary hypothesis",
        )
        frozen = await hypothesis.transition(project_id, version["id"], "freeze", "researcher", "lock before claim support")
        assert frozen["status"] == "frozen"
        manifest_path = workspace / project_id / frozen["manifest"]["path"]
        assert manifest_path.is_file()
        assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == frozen["manifest"]["sha256"]

        await narrative.save_map(
            project_id,
            {
                "question": "Does the gate hold?",
                "tension": "Existing reports disagree on effect direction",
                "mechanism": "A measurable pathway under controlled conditions",
                "hypotheses": [frozen["statement"]],
                "claims": ["C1"],
                "competing_explanations": ["selection bias"],
                "boundaries": ["numeric laboratory observations"],
                "limitations": ["single provider snapshot"],
            },
        )
        await narrative.approve_map(project_id, "researcher")
        graph = await claim_evidence.create_link(
            project_id,
            {
                "claim_id": "C1",
                "evidence_card_id": card["id"],
                "relation": "supports",
                "passage": "The report records a positive treatment effect under controlled conditions.",
                "locator": "p.3",
            },
        )
        assert graph["gate"]["passed"] is False
        link_id = graph["links"][0]["id"]
        graph = await claim_evidence.review_link(project_id, link_id, "researcher", "approved", "passage supports C1")
        assert graph["gate"]["passed"] is True
        graph_path = workspace / project_id / graph["artifact"]["path"]
        assert graph_path.is_file()
        assert hashlib.sha256(graph_path.read_bytes()).hexdigest() == graph["artifact"]["sha256"]

        novelty = await innovation.run(
            project_id,
            actor="researcher",
            claims=["A gate-backed novelty ledger that binds frozen hypotheses to immutable report hashes"],
            overrides={},
            provider=None,
        )
        assert novelty["gate"]["passed"] is True
        novelty_path = workspace / project_id / novelty["artifact"]["path"]
        assert novelty_path.is_file()
        assert hashlib.sha256(novelty_path.read_bytes()).hexdigest() == novelty["artifact"]["sha256"]

        draft = await drafts.generate(project_id)
        draft_path = workspace / project_id / draft["path"]
        assert draft_path.is_file()
        assert "approved-citations-only" in draft["content"]

        review = await adversarial.run(project_id, "deterministic")
        assert review["status"] == "completed"
        assert review["verdict"] == "pass"
        report_path = workspace / project_id / review["report_path"]
        assert report_path.is_file()
        assert hashlib.sha256(report_path.read_bytes()).hexdigest() == review["report_sha256"]
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["inputs_sha256"] == review["inputs_sha256"]

        envelope = await assurance.read(project_id)
        assert envelope["status"] == "PASS"
        assert envelope["submission_ready"] is True
        assert envelope["independent_from_generator"] is True
        assert all(gate["status"] == "PASS" for gate in envelope["gates"])
        assert envelope["current_review"]["id"] == review["id"]

        approved = await contracts.approve(project_id, "researcher", True, "all deterministic gates passed")
        assert approved["status"] == "approved"

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        for module, value in old_ws.items():
            module.WORKSPACES_DIR = value


def test_assurance_blocks_when_claim_graph_or_review_is_missing(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.scientific_narrative as narrative
    import services.claim_evidence as claim_evidence
    import services.adversarial_review as adversarial
    import services.assurance as assurance
    import services.hypothesis_lifecycle as hypothesis
    import services.approved_drafts as drafts

    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    modules = (contracts, claim_evidence, adversarial, hypothesis, drafts)
    old_db = store.DB_PATH
    old_ws = _patch_workspaces(modules, workspace)
    store.DB_PATH = tmp_path / "block.db"
    monkeypatch.setattr(
        contracts,
        "LiteratureClient",
        _snapshot_client("Blocked Paper", ["Author"], 2024, "10.1234/block", "https://doi.org/10.1234/block"),
    )

    async def go():
        await store.init_db()
        project = await contracts.create_contract("Blocked", "Why blocked?", "criteria")
        project_id = project["id"]
        project = await contracts.save_provider_evidence(
            project_id, "openalex", "blocked", "https://doi.org/10.1234/block"
        )
        card = project["evidence_cards"][0]
        await contracts.review_evidence_card(project_id, card["id"], "researcher", "approved", "ok")
        await contracts.review_claim_support(project_id, card["id"], "researcher", "approved", "ok")
        await narrative.save_map(
            project_id,
            {
                "question": "Why blocked?",
                "tension": "Conflicting reports",
                "mechanism": "Unclear pathway",
                "hypotheses": ["H1"],
                "claims": ["C1"],
                "competing_explanations": ["noise"],
                "boundaries": ["lab"],
                "limitations": ["n=1"],
            },
        )
        await narrative.approve_map(project_id, "researcher")
        envelope = await assurance.read(project_id)
        codes = {item["code"] for item in envelope["findings"]}
        assert "unsupported_claims" in codes or "no_approved_support_links" in codes
        assert "missing_independent_review" in codes
        assert envelope["submission_ready"] is False
        review = await adversarial.run(project_id, "deterministic")
        assert review["verdict"] == "block"
        report_path = workspace / project_id / review["report_path"]
        assert report_path.is_file()

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old_db
        for module, value in old_ws.items():
            module.WORKSPACES_DIR = value
