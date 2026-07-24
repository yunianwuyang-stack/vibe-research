"""Unit tests for machine citation existence gate on evidence-card review."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _snapshot_client(title, authors, year, doi, url):
    import hashlib

    from domain.evidence import SourceRecord

    class Client:
        def __init__(self, *a, **k):
            self.cache = Path(a[1])

        def _write(self, provider, query):
            records = [
                {
                    "title": title,
                    "authors": list(authors),
                    "year": year,
                    "doi": doi,
                    "url": url,
                }
            ]
            self.cache.mkdir(parents=True, exist_ok=True)
            raw = json.dumps(
                records, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
            path = self.cache / f"{provider}-{hashlib.sha256(query.encode()).hexdigest()}.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": provider,
                        "query": query,
                        "retrieved_at": "now",
                        "records": records,
                        "content_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            record = SourceRecord(
                provider, title, tuple(authors), year, doi, url, "2026-01-01T00:00:00Z", query
            )
            return path, record, hashlib.sha256(path.read_bytes()).hexdigest()

        def search(self, provider, query):
            _, record, _ = self._write(provider, query)
            return [record]

        def replay_snapshot(self, provider, query):
            path, record, digest = self._write(provider, query)
            return [record], digest

    return Client


def test_offline_snapshot_pass_and_unknown_doi_blocked(tmp_path, monkeypatch):
    import services.research_contracts as contracts
    import services.state_store as store
    from fastapi import HTTPException

    old = store.DB_PATH
    store.DB_PATH = tmp_path / "machine-citation.db"
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    monkeypatch.setattr(contracts, "WORKSPACES_DIR", workspace)
    monkeypatch.setattr(
        contracts,
        "LiteratureClient",
        _snapshot_client("Known Paper", ["A Author"], 2024, "10.1234/known", "https://doi.org/10.1234/known"),
    )

    async def go():
        await store.init_db()
        project = await contracts.create_contract("P", "Question?", "peer reviewed")
        project = await contracts.save_provider_evidence(
            project["id"], "openalex", "question", "https://doi.org/10.1234/known"
        )
        card = project["evidence_cards"][0]
        project = await contracts.review_evidence_card(
            project["id"], card["id"], "researcher", "approved", "offline metadata checked"
        )
        approved = project["evidence_cards"][0]
        assert approved["citation_status"] == "approved"
        assert approved["citation_machine_verdict"] == "PASS"
        assert approved["citation_machine_layer"] == "offline_snapshot"
        artifact = workspace / project["id"] / approved["citation_machine_artifact_path"]
        assert artifact.is_file()
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["verdict"] == "PASS"
        assert payload["human_decision"] == "approved"

        # Inject a card whose DOI is absent from the offline literature cache.
        db = await store.get_db()
        try:
            fake_id = "deadbeefcitationfail01"
            await db.execute(
                "INSERT INTO evidence_cards (id,project_id,identity,title,authors_json,publication_year,doi,canonical_url) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    fake_id,
                    project["id"],
                    "doi:10.9999/does-not-exist-vibe",
                    "Fabricated Paper",
                    "[]",
                    2024,
                    "10.9999/does-not-exist-vibe",
                    "https://doi.org/10.9999/does-not-exist-vibe",
                ),
            )
            await db.commit()
        finally:
            await db.close()

        # Force offline-only so FAIL is deterministic without depending on live DOI API.
        monkeypatch.setattr(
            contracts,
            "_run_machine_citation_check",
            lambda card, enable_network=True: {
                "verdict": "FAIL",
                "layer": "live_doi",
                "detail": card.get("doi") or "",
                "lookup_layer": "live_doi",
                "checked_at": "2026-07-16T00:00:00+00:00",
                "enable_network": enable_network,
            },
        )
        with pytest.raises(HTTPException) as excinfo:
            await contracts.review_evidence_card(
                project["id"], fake_id, "researcher", "approved", "should be blocked"
            )
        assert excinfo.value.status_code == 409
        detail = excinfo.value.detail
        assert isinstance(detail, dict)
        assert detail.get("code") == "citation_machine_failed"

    try:
        asyncio.run(go())
    finally:
        store.DB_PATH = old


def test_product_lookup_offline_sets_and_format():
    from infrastructure.literature.product_lookup import ProductCitationLookup, offline_sets_from_cache

    cache = Path(__file__).resolve().parents[1]  # unused placeholder
    del cache
    lookup = ProductCitationLookup(offline_dois={"10.1234/abc"}, enable_network=False)
    assert lookup.doi_exists("10.1234/abc") is True
    assert lookup.last_layer == "offline_snapshot"
    assert lookup.doi_exists("10.1/bad") is False
