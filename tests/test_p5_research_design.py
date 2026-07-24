"""P5 research-design methods and fail-closed gates."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _profile(kind: str) -> dict[str, str]:
    values = {
        "systematic_review_meta": {"search_strategy": "two databases", "screening_rule": "dual screen", "synthesis_plan": "random effects"},
        "observational_causal": {"estimand": "ATE", "dag": "X->Y", "identification_strategy": "backdoor"},
        "experimental_ml": {"baseline": "strong baseline", "ablation_plan": "remove modules", "evaluation_metric": "AUROC"},
        "theoretical_mathematical": {"claim": "theorem", "proof_obligation": "complete proof", "counterexample_plan": "finite search"},
        "qualitative_humanities": {"corpus_scope": "public corpus", "coding_scheme": "codebook", "negative_case_plan": "negative cases"},
    }
    values[kind]["falsification_criteria"] = "predefined disconfirming observation"
    return values[kind]


def _entry(source_url: str, conflict: str = "") -> dict[str, str]:
    return {"title": "Closest prior work", "source_url": source_url, "similarities": "same question", "differences": "different design", "evidence_strength": "peer reviewed", "unresolved_conflicts": conflict}


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import services.state_store as store
    import services.research_contracts as contracts
    import services.p5_research_design as p5

    old = store.DB_PATH
    store.DB_PATH = tmp_path / "p5.db"
    monkeypatch.setattr(contracts, "WORKSPACES_DIR", tmp_path / "workspaces")
    try:
        yield store, contracts, p5
    finally:
        store.DB_PATH = old


def test_all_study_profiles_require_falsifier(isolated_db):
    store, contracts, p5 = isolated_db

    async def run():
        await store.init_db()
        project = await contracts.create_contract("P5", "A research question", "real sources")
        for kind in p5.PROFILE_REQUIRED:
            with pytest.raises(Exception):
                await p5.save_design(project["id"], {"theoretical": True, "falsifier": "f"}, kind, {k: v for k, v in _profile(kind).items() if k != "falsification_criteria"}, "researcher")
            result = await p5.save_design(project["id"], {"theoretical": True, "falsifier": "f"}, kind, _profile(kind), "researcher")
            assert result["design"]["profile_type"] == kind

    asyncio.run(run())


def test_prior_art_is_multi_source_frozen_and_conflicts_blocked(isolated_db):
    store, contracts, p5 = isolated_db

    async def run():
        await store.init_db()
        project = await contracts.create_contract("P5", "A research question", "real sources")
        with pytest.raises(Exception):
            await p5.freeze_prior_art(project["id"], "2026-07-19", {}, [_entry("https://one.example/a")], "researcher")
        with pytest.raises(Exception):
            await p5.freeze_prior_art(project["id"], "2026-07-19", {}, [_entry("https://one.example/a"), _entry("https://two.example/b", "unresolved")], "researcher")
        result = await p5.freeze_prior_art(project["id"], "2026-07-19", {}, [_entry("https://one.example/a"), _entry("https://two.example/b")], "researcher")
        assert len(result["prior_art"]["entries"]) == 2

    asyncio.run(run())


def test_protocol_and_ethics_gate_are_fail_closed(isolated_db):
    store, contracts, p5 = isolated_db

    async def run():
        await store.init_db()
        project = await contracts.create_contract("P5", "A research question", "real sources")
        protocol = {"estimand": "ATE", "outcome": "Y", "exposure": "X", "baseline": "strong", "ablation_plan": "remove", "falsification_criteria": "null result"}
        exploratory = await p5.save_protocol(project["id"], protocol, "exploratory", "researcher")
        assert exploratory["protocol"]["status"] == "draft"
        confirmatory = await p5.save_protocol(project["id"], protocol, "confirmatory", "researcher")
        assert confirmatory["protocol"]["status"] == "frozen"
        assessment = {"subjects": "public documents", "jurisdiction": "none", "irb_status": "not_required", "consent_status": "unknown", "dua_status": "verified", "license_status": "verified", "pii_categories": [], "allowed_use": "research", "retention_deletion": "delete after study"}
        blocked = await p5.assess_ethics(project["id"], assessment, "researcher")
        assert blocked["ethics_data_rights"]["status"] == "blocked"
        assessment["consent_status"] = "not_required"
        verified = await p5.assess_ethics(project["id"], assessment, "researcher")
        assert verified["ethics_data_rights"]["status"] == "verified"
        assert (await p5.gate(project["id"]))["status"] == "blocked"

    asyncio.run(run())
