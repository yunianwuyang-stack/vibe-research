"""Persistent, evidence-gated research contract state machine."""
from __future__ import annotations
import json
import uuid
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from infrastructure.literature import (
    CitationVerifier,
    CitationVerdict,
    HttpTransport,
    LiteratureClient,
    ProductCitationLookup,
    ProviderUnavailable,
    offline_sets_from_cache,
)
from config import WORKSPACES_DIR
from typing import Any
from fastapi import HTTPException
from services.state_store import get_db
from services import hypothesis_lifecycle

NEEDS_EVIDENCE = "needs_evidence"
EVIDENCE_PENDING_REVIEW = "evidence_pending_review"
BLOCKED = "blocked"
READY_FOR_REVIEW = "ready_for_review"
APPROVED = "approved"

async def _refresh_evidence_status(db: Any, project_id: str) -> str:
    """Derive the project status from persisted evidence-card decisions.

    Saving a card is a real state transition, but it must not imply that the
    citation or its claim support has been verified.  A project becomes ready
    for review only when at least one card has passed both independent gates.
    """
    row = await (await db.execute(
        """
        SELECT
          SUM(CASE WHEN citation_status='approved' AND claim_support_status='approved' THEN 1 ELSE 0 END) AS usable,
          SUM(CASE WHEN citation_status='needs_review' OR (citation_status='approved' AND claim_support_status='needs_review') THEN 1 ELSE 0 END) AS pending
        FROM evidence_cards WHERE project_id=?
        """,
        (project_id,),
    )).fetchone()
    usable = int(row["usable"] or 0)
    pending = int(row["pending"] or 0)
    status = READY_FOR_REVIEW if usable else (EVIDENCE_PENDING_REVIEW if pending else NEEDS_EVIDENCE)
    await db.execute(
        "UPDATE research_projects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (status, project_id),
    )
    return status

def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().removeprefix("https://doi.org/").removeprefix("doi:")
    if not re.fullmatch(r"10\.\d{4,9}/\S+", normalized):
        raise HTTPException(status_code=422, detail="Selected evidence contains an invalid DOI")
    return normalized

def _identity(record: Any) -> str:
    doi = _normalize_doi(record.doi)
    if doi:
        return f"doi:{doi}"
    authors = "|".join(str(item).strip().casefold() for item in record.authors if str(item).strip())
    return f"title:{record.title.strip().casefold()}|year:{record.year}|authors:{authors}"

async def _project(project_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        row = await (await db.execute("SELECT * FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Research project not found")
        result = dict(row)
        artifacts = await (await db.execute("SELECT * FROM research_artifacts WHERE project_id=? ORDER BY created_at", (project_id,))).fetchall()
        events = await (await db.execute("SELECT * FROM research_events WHERE project_id=? ORDER BY id", (project_id,))).fetchall()
        result["artifacts"] = [dict(x) for x in artifacts]
        cards = await (await db.execute("SELECT * FROM evidence_cards WHERE project_id=? ORDER BY created_at", (project_id,))).fetchall()
        result["evidence_cards"] = []
        for card in cards:
            item = dict(card); item["authors"] = json.loads(item.pop("authors_json"))
            provenance = await (await db.execute("SELECT provider,query,source_url,raw_response_sha256,retrieved_at FROM evidence_provenance WHERE evidence_card_id=? ORDER BY id", (item["id"],))).fetchall()
            item["provenance"] = [dict(value) for value in provenance]
            result["evidence_cards"].append(item)
        result.update(await hypothesis_lifecycle.read_project(db, project_id))
        result["events"] = [{**dict(x), "payload": json.loads(x["payload"])} for x in events]
        return result
    finally:
        await db.close()

async def create_contract(title: str, research_question: str, inclusion_criteria: str) -> dict[str, Any]:
    if not all(x.strip() for x in (title, research_question, inclusion_criteria)):
        raise HTTPException(status_code=422, detail="title, research_question and inclusion_criteria are required")
    project_id = uuid.uuid4().hex
    db = await get_db()
    try:
        await db.execute("INSERT INTO research_projects (id,title,research_question,inclusion_criteria,status) VALUES (?,?,?,?,?)", (project_id,title,research_question,inclusion_criteria,NEEDS_EVIDENCE))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"contract_created","human",json.dumps({"status":NEEDS_EVIDENCE})))
        await db.commit()
    finally:
        await db.close()
    return await _project(project_id)

async def list_contracts() -> list[dict[str, Any]]:
    db = await get_db()
    try: rows = await (await db.execute("SELECT id FROM research_projects ORDER BY updated_at DESC")).fetchall()
    finally: await db.close()
    return [await _project(row["id"]) for row in rows]

async def add_evidence(project_id: str, kind: str, sha256: str, provenance: str, content: str) -> dict[str, Any]:
    """Register a byte-verified artifact as *needs_review*, never as verified.

    Provider-backed verification is intentionally deferred to R02; registration
    must not turn an opaque client assertion into an approved research fact.
    """
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if not kind.strip() or not re.fullmatch(r"[a-f0-9]{64}", sha256.lower()) or digest != sha256.lower():
        raise HTTPException(status_code=422, detail="Evidence SHA-256 must match supplied content")
    if not re.fullmatch(r"(openalex|crossref|datacite|arxiv|semantic_scholar):[^\s:]+", provenance):
        raise HTTPException(status_code=422, detail="Provenance must name a supported provider and stable identifier")
    artifact_id = uuid.uuid4().hex
    db = await get_db()
    try:
        row = await (await db.execute("SELECT status FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Research project not found")
        if row["status"] == APPROVED: raise HTTPException(status_code=409, detail="Approved contract is immutable; create a revision")
        await db.execute("INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)", (artifact_id,project_id,kind,sha256.lower(),provenance,"needs_review"))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"evidence_registered","system",json.dumps({"artifact_id":artifact_id,"sha256":sha256.lower(),"verification":"needs_review"})))
        await db.commit()
    finally:
        await db.close()
    return await _project(project_id)

async def approve(project_id: str, actor: str, approved: bool, reason: str) -> dict[str, Any]:
    if not actor.strip() or not reason.strip(): raise HTTPException(status_code=422, detail="human actor and reason are required")
    review_inputs_sha256 = ""
    if approved:
        from services.adversarial_review import current_inputs_sha256
        review_inputs_sha256 = await current_inputs_sha256(project_id)
    db = await get_db()
    try:
        row = await (await db.execute("SELECT status FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not row: raise HTTPException(status_code=404, detail="Research project not found")
        verified = await (await db.execute("SELECT count(*) FROM research_artifacts WHERE project_id=? AND status='verified'", (project_id,))).fetchone()
        if approved and (row["status"] != READY_FOR_REVIEW or verified[0] == 0): raise HTTPException(status_code=409, detail="Provider-verified evidence is required before approval")
        if approved:
            review = await (await db.execute("SELECT id FROM adversarial_reviews WHERE project_id=? AND mode='deterministic' AND status='completed' AND verdict='pass' AND inputs_sha256=? ORDER BY rowid DESC LIMIT 1", (project_id, review_inputs_sha256))).fetchone()
            if not review: raise HTTPException(status_code=409, detail="A current passing deterministic adversarial review is required before approval")
        status = APPROVED if approved else BLOCKED
        await db.execute("UPDATE research_projects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status,project_id))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"approval_recorded",actor,json.dumps({"approved":approved,"reason":reason})))
        await db.commit()
    finally:
        await db.close()
    return await _project(project_id)

async def get_contract(project_id: str) -> dict[str, Any]: return await _project(project_id)

async def save_provider_evidence(project_id: str, provider: str, query: str, source_url: str, snapshot_sha256: str | None = None) -> dict[str, Any]:
    """Persist one card from the exact integrity-checked search snapshot."""
    client = LiteratureClient(HttpTransport(), WORKSPACES_DIR / "literature-cache", timeout_seconds=15)
    try: records, digest = client.replay_snapshot(provider, query)
    except ProviderUnavailable as exc: raise HTTPException(status_code=409, detail="The literature search snapshot is no longer available; run the search again") from exc
    if snapshot_sha256 is not None and digest != snapshot_sha256.lower():
        raise HTTPException(status_code=409, detail="The literature search snapshot changed; run the search again before saving")
    record = next((item for item in records if item.url == source_url), None)
    if record is None: raise HTTPException(status_code=422, detail="Selected source was not returned by provider")
    identity = _identity(record); doi = _normalize_doi(record.doi)
    cache_path = WORKSPACES_DIR / "literature-cache" / f"{provider}-{hashlib.sha256(query.encode()).hexdigest()}.json"
    if not cache_path.is_file(): raise HTTPException(status_code=503, detail="Provider response recording is unavailable")
    raw_bytes = cache_path.read_bytes(); envelope = json.loads(raw_bytes.decode("utf-8"))
    from infrastructure.literature.providers import verified_records
    try: verified_records(envelope,provider,query)
    except ProviderUnavailable as exc: raise HTTPException(status_code=503, detail="Provider response recording failed integrity validation") from exc
    if hashlib.sha256(raw_bytes).hexdigest() != digest:
        raise HTTPException(status_code=409, detail="The literature search snapshot changed during save; run the search again")
    db = await get_db()
    try:
        project = await (await db.execute("SELECT status FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project: raise HTTPException(status_code=404, detail="Research project not found")
        card = await (await db.execute("SELECT id FROM evidence_cards WHERE project_id=? AND identity=?", (project_id, identity))).fetchone()
        card_id = card["id"] if card else uuid.uuid4().hex
        if not card:
            await db.execute("INSERT INTO evidence_cards (id,project_id,identity,title,authors_json,publication_year,doi,canonical_url) VALUES (?,?,?,?,?,?,?,?)", (card_id,project_id,identity,record.title,json.dumps(record.authors,ensure_ascii=False),record.year,doi,record.url))
        await db.execute("INSERT OR IGNORE INTO evidence_provenance (evidence_card_id,provider,query,source_url,raw_response_sha256,retrieved_at) VALUES (?,?,?,?,?,?)", (card_id,provider,query,record.url,digest,record.retrieved_at))
        status = await _refresh_evidence_status(db, project_id)
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"evidence_card_saved","human",json.dumps({"evidence_card_id":card_id,"identity":identity,"provider":provider,"raw_response_sha256":digest})))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"evidence_status_changed","system",json.dumps({"status":status,"reason":"evidence_card_saved"})))
        await db.commit()
    finally: await db.close()
    return await _project(project_id)

def _arxiv_from_url(url: str | None) -> str | None:
    if not url:
        return None
    text = str(url)
    if "arxiv.org" not in text.casefold():
        return None
    return ProductCitationLookup._norm_arxiv(text)


def _run_machine_citation_check(card: dict[str, Any], *, enable_network: bool = True) -> dict[str, Any]:
    """Deterministic citation existence check with offline snapshot priority.

    Offline PASS requires the DOI/title/arXiv id to appear in an integrity-checked
    literature-cache envelope. Card rows alone never mint a silent PASS.
    """
    cache_dir = Path(WORKSPACES_DIR) / "literature-cache"
    cache_dois, cache_arxiv, cache_titles = offline_sets_from_cache(cache_dir)
    lookup = ProductCitationLookup(
        offline_dois=cache_dois,
        offline_arxiv=cache_arxiv,
        offline_titles=cache_titles,
        enable_network=enable_network,
    )
    doi = card.get("doi")
    title = str(card.get("title") or "")
    arxiv = _arxiv_from_url(card.get("canonical_url"))
    authors_raw = card.get("authors_json") or card.get("authors") or []
    if isinstance(authors_raw, str):
        try:
            authors = tuple(json.loads(authors_raw))
        except json.JSONDecodeError:
            authors = ()
    else:
        authors = tuple(authors_raw)
    year = card.get("publication_year")
    year_int = int(year) if isinstance(year, int) or (isinstance(year, str) and str(year).isdigit()) else None
    check = CitationVerifier(lookup).verify(
        doi=str(doi).strip() if isinstance(doi, str) and doi.strip() else None,
        arxiv=arxiv,
        title=title or None,
        authors=authors,
        year=year_int,
    )
    checked_at = datetime.now(timezone.utc).isoformat()
    return {
        "verdict": check.verdict.value,
        "layer": check.layer if check.layer != "doi" else (lookup.last_layer or check.layer),
        "detail": check.detail,
        "lookup_layer": lookup.last_layer,
        "checked_at": checked_at,
        "enable_network": enable_network,
    }


def _write_citation_check_artifact(project_id: str, card_id: str, payload: dict[str, Any]) -> str:
    root = Path(WORKSPACES_DIR) / project_id / "citation_checks"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{card_id}.json"
    body = {
        "format_version": "citation-check/v1",
        "project_id": project_id,
        "evidence_card_id": card_id,
        **payload,
    }
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(raw)
    body["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return f"citation_checks/{card_id}.json"


async def review_evidence_card(project_id: str, card_id: str, actor: str, decision: str, reason: str) -> dict[str, Any]:
    if decision not in {"approved", "rejected"} or not actor.strip() or not reason.strip():
        raise HTTPException(status_code=422, detail="actor, reason and approved/rejected decision are required")
    db = await get_db()
    try:
        card = await (await db.execute("SELECT * FROM evidence_cards WHERE id=? AND project_id=?", (card_id,project_id))).fetchone()
        if not card: raise HTTPException(status_code=404, detail="Evidence card not found")
        card_data = dict(card)
        machine = _run_machine_citation_check(card_data, enable_network=True)
        if decision == "approved" and machine["verdict"] == CitationVerdict.FAIL.value:
            artifact_rel = _write_citation_check_artifact(
                project_id,
                card_id,
                {**machine, "human_decision": decision, "blocked": True},
            )
            await db.execute(
                "UPDATE evidence_cards SET citation_machine_verdict=?,citation_machine_layer=?,citation_machine_detail=?,"
                "citation_machine_checked_at=?,citation_machine_artifact_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    machine["verdict"],
                    machine["lookup_layer"] or machine["layer"],
                    machine["detail"][:2000],
                    machine["checked_at"],
                    artifact_rel,
                    card_id,
                ),
            )
            await db.execute(
                "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
                (
                    project_id,
                    "citation_machine_check_blocked",
                    "system",
                    json.dumps(
                        {
                            "evidence_card_id": card_id,
                            "machine": machine,
                            "artifact_path": artifact_rel,
                            "reason": reason,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            await db.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "citation_machine_failed",
                    "message": "Machine citation existence check failed; human approval is blocked",
                    "machine": machine,
                    "artifact_path": artifact_rel,
                },
            )
        citation_status = "approved" if decision == "approved" else "rejected"
        artifact_rel = _write_citation_check_artifact(
            project_id,
            card_id,
            {**machine, "human_decision": decision, "blocked": False},
        )
        await db.execute(
            "UPDATE evidence_cards SET citation_status=?,decision_reason=?,"
            "citation_machine_verdict=?,citation_machine_layer=?,citation_machine_detail=?,"
            "citation_machine_checked_at=?,citation_machine_artifact_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                citation_status,
                reason,
                machine["verdict"],
                machine["lookup_layer"] or machine["layer"],
                machine["detail"][:2000],
                machine["checked_at"],
                artifact_rel,
                card_id,
            ),
        )
        status = await _refresh_evidence_status(db, project_id)
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "evidence_card_reviewed",
                actor,
                json.dumps(
                    {
                        "evidence_card_id": card_id,
                        "citation_status": citation_status,
                        "claim_support_status": "needs_review",
                        "reason": reason,
                        "machine": machine,
                        "artifact_path": artifact_rel,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (project_id, "evidence_status_changed", "system", json.dumps({"status": status, "reason": "citation_reviewed"})),
        )
        await db.commit()
    finally: await db.close()
    return await _project(project_id)

async def review_claim_support(project_id: str, card_id: str, actor: str, decision: str, reason: str) -> dict[str, Any]:
    if decision not in {"approved", "rejected"} or not actor.strip() or not reason.strip(): raise HTTPException(status_code=422, detail="actor, reason and approved/rejected decision are required")
    db = await get_db()
    try:
        card = await (await db.execute("SELECT citation_status FROM evidence_cards WHERE id=? AND project_id=?", (card_id,project_id))).fetchone()
        if not card: raise HTTPException(status_code=404, detail="Evidence card not found")
        if decision == "approved" and card["citation_status"] != "approved": raise HTTPException(status_code=409, detail="Citation existence must be approved before claim support")
        await db.execute("UPDATE evidence_cards SET claim_support_status=?,decision_reason=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (decision,reason,card_id))
        status = await _refresh_evidence_status(db, project_id)
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"claim_support_reviewed",actor,json.dumps({"evidence_card_id":card_id,"claim_support_status":decision,"reason":reason})))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"evidence_status_changed","system",json.dumps({"status":status,"reason":"claim_support_reviewed"})))
        await db.commit()
    finally: await db.close()
    return await _project(project_id)


async def verify_provider_evidence(project_id: str, provider: str, query: str, source_url: str) -> dict[str, Any]:
    """Fetch provider data server-side and persist an immutable verified record."""
    client = LiteratureClient(HttpTransport(), WORKSPACES_DIR / "literature-cache", timeout_seconds=15)
    try: records = client.search(provider, query)
    except ProviderUnavailable as exc: raise HTTPException(status_code=503, detail="Provider unavailable") from exc
    record = next((x for x in records if x.url == source_url), None)
    if record is None: raise HTTPException(status_code=422, detail="Selected source was not returned by provider")
    payload = json.dumps(record.__dict__, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest(); artifact_id = uuid.uuid4().hex
    db = await get_db()
    try:
        exists = await (await db.execute("SELECT id FROM research_projects WHERE id=?",(project_id,))).fetchone()
        if not exists: raise HTTPException(status_code=404, detail="Research project not found")
        provenance=f"{record.provider}:{record.doi or record.url}"
        await db.execute("INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",(artifact_id,project_id,"provider_record",digest,provenance,"verified"))
        await db.execute("UPDATE research_projects SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(READY_FOR_REVIEW,project_id))
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",(project_id,"provider_evidence_verified","provider",json.dumps({"artifact_id":artifact_id,"provider":provider,"query":query,"source_url":source_url,"sha256":digest})))
        await db.commit()
    finally: await db.close()
    return await _project(project_id)
