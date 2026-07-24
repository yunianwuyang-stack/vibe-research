"""Deterministic novelty/innovation gate with byte-addressable reports.

The gate never invents prior art.  It scores each registered contribution claim
against (1) the project's own verified evidence cards and (2) optional provider
search snapshots.  LOW novelty without a researcher override blocks submission.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from config import WORKSPACES_DIR
from services.state_store import get_db


REPORT_RELATIVE = "evidence/innovation-check-report.json"
GATE_RULE = (
    "Every current frozen hypothesis must yield a scored novelty claim; "
    "LOW novelty requires an explicit researcher override with reason; "
    "the persisted report hash must match the ledger."
)
TOKEN_RE = re.compile(r"[a-z0-9一-鿿]{3,}", re.IGNORECASE)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value) if not isinstance(value, (bytes, bytearray)) else value).hexdigest()


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


def _tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in TOKEN_RE.finditer(text or "")}


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a))


def _score_level(overlap: float) -> str:
    if overlap >= 0.72:
        return "LOW"
    if overlap >= 0.42:
        return "MEDIUM"
    return "HIGH"


def _normalize_claim(text: str) -> str:
    cleaned = " ".join((text or "").strip().split())
    if len(cleaned) < 12:
        raise HTTPException(422, detail="Each novelty claim must be at least 12 characters")
    if len(cleaned) > 2000:
        raise HTTPException(422, detail="Each novelty claim must be at most 2000 characters")
    return cleaned


def _ensure_schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS innovation_checks (
     id TEXT PRIMARY KEY,
     project_id TEXT NOT NULL REFERENCES research_projects(id),
     status TEXT NOT NULL,
     gate_passed INTEGER NOT NULL DEFAULT 0,
     claims_json TEXT NOT NULL,
     findings_json TEXT NOT NULL,
     closest_prior_art_json TEXT NOT NULL,
     report_path TEXT NOT NULL,
     report_sha256 TEXT NOT NULL,
     sources_version_sha256 TEXT NOT NULL,
     overrides_json TEXT NOT NULL DEFAULT '{}',
     created_by TEXT NOT NULL,
     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_innovation_checks_project
    ON innovation_checks(project_id, created_at DESC);
    """


async def _ensure_schema(db: Any) -> None:
    await db.executescript(_ensure_schema_sql())


async def _project_rows(db: Any, project_id: str) -> dict[str, Any]:
    project = await (await db.execute(
        "SELECT id,title,research_question,inclusion_criteria,status FROM research_projects WHERE id=?",
        (project_id,),
    )).fetchone()
    if not project:
        raise HTTPException(404, detail="Research project not found")
    cards = await (await db.execute(
        "SELECT id,title,doi,canonical_url,citation_status,claim_support_status,authors_json "
        "FROM evidence_cards WHERE project_id=? ORDER BY created_at,id",
        (project_id,),
    )).fetchall()
    hypotheses = await (await db.execute(
        "SELECT id,hypothesis_id,version,statement,mechanism,prediction,status "
        "FROM hypothesis_versions WHERE project_id=? ORDER BY hypothesis_id,version",
        (project_id,),
    )).fetchall()
    latest: dict[str, int] = {}
    for row in hypotheses:
        latest[row["hypothesis_id"]] = max(latest.get(row["hypothesis_id"], 0), int(row["version"]))
    current_frozen = [
        dict(row)
        for row in hypotheses
        if int(row["version"]) == latest.get(row["hypothesis_id"], -1) and row["status"] == "frozen"
    ]
    return {
        "project": dict(project),
        "evidence_cards": [dict(row) for row in cards],
        "frozen_hypotheses": current_frozen,
    }


def _derive_claims(frozen: list[dict[str, Any]], explicit: list[str] | None) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    if explicit:
        for index, text in enumerate(explicit, start=1):
            claims.append({
                "id": f"N{index}",
                "text": _normalize_claim(text),
                "source": "explicit",
            })
        return claims
    if not frozen:
        raise HTTPException(409, detail="At least one current frozen hypothesis is required before novelty checking")
    for index, item in enumerate(frozen, start=1):
        text = " — ".join(
            part for part in (
                str(item.get("statement") or "").strip(),
                str(item.get("mechanism") or "").strip(),
            ) if part
        )
        claims.append({
            "id": f"H{index}",
            "text": _normalize_claim(text),
            "source": f"hypothesis:{item['id']}",
            "hypothesis_version_id": item["id"],
        })
    return claims


def _card_corpus(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corpus = []
    for card in cards:
        authors = card.get("authors_json")
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except json.JSONDecodeError:
                authors = []
        corpus.append({
            "kind": "evidence_card",
            "id": card["id"],
            "title": card.get("title") or "",
            "doi": card.get("doi") or "",
            "url": card.get("canonical_url") or "",
            "authors": authors or [],
            "citation_status": card.get("citation_status"),
            "claim_support_status": card.get("claim_support_status"),
            "text": " ".join(filter(None, [card.get("title") or "", " ".join(authors or [])])),
        })
    return corpus


def _search_corpus(records: list[Any]) -> list[dict[str, Any]]:
    corpus = []
    for index, record in enumerate(records):
        title = getattr(record, "title", None) or (record.get("title") if isinstance(record, dict) else "") or ""
        authors = list(getattr(record, "authors", None) or (record.get("authors") if isinstance(record, dict) else []) or [])
        doi = getattr(record, "doi", None) or (record.get("doi") if isinstance(record, dict) else "") or ""
        url = getattr(record, "url", None) or (record.get("url") if isinstance(record, dict) else "") or ""
        corpus.append({
            "kind": "provider_search",
            "id": f"search-{index + 1}",
            "title": title,
            "doi": doi,
            "url": url,
            "authors": authors,
            "text": " ".join(filter(None, [title, " ".join(str(a) for a in authors)])),
        })
    return corpus


def _evaluate_claims(
    claims: list[dict[str, str]],
    corpus: list[dict[str, Any]],
    overrides: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    closest: list[dict[str, Any]] = []
    unsupported_low: list[str] = []
    if not corpus:
        return ([{
            "severity": "critical",
            "code": "empty_novelty_corpus",
            "message": "Novelty cannot be assessed without verified evidence or provider search records.",
            "locator": "corpus",
        }], [], {
            "passed": False,
            "status": "blocked",
            "reason": "empty_novelty_corpus",
            "total_claims": len(claims),
            "low_novelty_claim_ids": [],
            "rule": GATE_RULE,
        })
    for claim in claims:
        best = None
        best_score = -1.0
        for item in corpus:
            score = _overlap(claim["text"], item.get("text") or item.get("title") or "")
            if score > best_score:
                best_score = score
                best = item
        level = _score_level(best_score if best_score >= 0 else 0.0)
        override_reason = (overrides.get(claim["id"]) or "").strip()
        entry = {
            "claim_id": claim["id"],
            "claim": claim["text"],
            "source": claim.get("source"),
            "novelty": level,
            "overlap": round(max(best_score, 0.0), 4),
            "closest_prior_art": None,
            "override_reason": override_reason or None,
        }
        if best and best_score > 0:
            entry["closest_prior_art"] = {
                "kind": best.get("kind"),
                "id": best.get("id"),
                "title": best.get("title"),
                "doi": best.get("doi") or None,
                "url": best.get("url") or None,
                "overlap": round(best_score, 4),
            }
            closest.append(entry["closest_prior_art"] | {"claim_id": claim["id"]})
        if level == "LOW" and not override_reason:
            unsupported_low.append(claim["id"])
            findings.append({
                "severity": "critical",
                "code": "low_novelty_without_override",
                "message": f"Claim {claim['id']} closely matches existing work and has no researcher override.",
                "locator": claim["id"],
            })
        elif level == "LOW":
            findings.append({
                "severity": "major",
                "code": "low_novelty_overridden",
                "message": f"Claim {claim['id']} is LOW novelty but overridden: {override_reason}",
                "locator": claim["id"],
            })
        elif level == "MEDIUM":
            findings.append({
                "severity": "minor",
                "code": "medium_novelty",
                "message": f"Claim {claim['id']} has partial overlap with prior work and needs careful framing.",
                "locator": claim["id"],
            })
        findings_row = entry
        findings.append({
            "severity": "info",
            "code": "claim_scored",
            "message": f"Claim {claim['id']} novelty={level} overlap={entry['overlap']}",
            "locator": claim["id"],
            "detail": findings_row,
        })
    gate = {
        "passed": not unsupported_low and bool(claims),
        "total_claims": len(claims),
        "low_novelty_claim_ids": unsupported_low,
        "rule": GATE_RULE,
    }
    if not claims:
        findings.insert(0, {
            "severity": "critical",
            "code": "missing_novelty_claims",
            "message": "No novelty claims were derived or supplied.",
            "locator": "",
        })
        gate["passed"] = False
    return findings, closest, gate


async def _provider_records(query: str, provider: str | None) -> tuple[list[Any], dict[str, Any] | None]:
    """Return (records, failure). Failure never invents PASS novelty."""
    if not provider:
        return [], None
    try:
        from infrastructure.literature import HttpTransport, LiteratureClient, ProviderUnavailable
        from config import WORKSPACES_DIR as ROOT_WS
        cache = ROOT_WS / "_literature_cache"
        client = LiteratureClient(HttpTransport(), cache, min_interval_seconds=0.0, timeout_seconds=8.0)
        return list(client.search(provider, query)), None
    except Exception as exc:
        # Provider outages must never invent PASS novelty; surface root_cause instead.
        return [], {
            "root_cause": "PROVIDER_FAILURE",
            "provider": provider,
            "error_type": type(exc).__name__,
            "message": str(exc)[:500],
        }


def _serialize_row(row: Any, *, report: dict[str, Any] | None = None) -> dict[str, Any]:
    value = dict(row)
    value["gate_passed"] = bool(value.get("gate_passed"))
    value["claims"] = json.loads(value.pop("claims_json"))
    value["findings"] = json.loads(value.pop("findings_json"))
    value["closest_prior_art"] = json.loads(value.pop("closest_prior_art_json"))
    value["overrides"] = json.loads(value.pop("overrides_json") or "{}")
    if report is not None:
        value["report"] = report
        value["gate"] = report.get("gate", {"passed": value["gate_passed"]})
        # Surface provider outage root cause on the API payload (P1-PS-008).
        if "provider_failure" in report:
            value["provider_failure"] = report.get("provider_failure")
        if report.get("gate", {}).get("root_cause"):
            value.setdefault("root_cause", report["gate"].get("root_cause"))
    else:
        value["gate"] = {"passed": value["gate_passed"], "rule": GATE_RULE}
        value["report"] = {
            "path": value["report_path"],
            "sha256": value["report_sha256"],
        }
        value.setdefault("provider_failure", None)
    value["artifact"] = {"path": value["report_path"], "sha256": value["report_sha256"]}
    return value


async def read(project_id: str) -> dict[str, Any]:
    db = await get_db()
    try:
        await _ensure_schema(db)
        row = await (await db.execute(
            "SELECT * FROM innovation_checks WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
            (project_id,),
        )).fetchone()
        if not row:
            return {
                "project_id": project_id,
                "status": "missing",
                "gate": {"passed": False, "rule": GATE_RULE, "total_claims": 0, "low_novelty_claim_ids": []},
                "claims": [],
                "findings": [{
                    "severity": "critical",
                    "code": "missing_innovation_check",
                    "message": "No persisted novelty/innovation check exists for this project.",
                    "locator": "",
                }],
                "closest_prior_art": [],
                "artifact": None,
                "report": None,
            }
        path = _workspace(project_id) / row["report_path"]
        report = None
        if path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == row["report_sha256"]:
                report = json.loads(raw.decode("utf-8"))
        result = _serialize_row(row, report=report)
        if report is None:
            result["gate"] = {"passed": False, "rule": GATE_RULE, "total_claims": 0, "low_novelty_claim_ids": []}
            result["findings"] = [{
                "severity": "critical",
                "code": "innovation_report_missing",
                "message": "The novelty report artifact is missing or its hash no longer matches the ledger.",
                "locator": row["report_path"],
            }] + result.get("findings", [])
            result["gate_passed"] = False
        return result
    finally:
        await db.close()


async def run(
    project_id: str,
    *,
    actor: str = "researcher",
    claims: list[str] | None = None,
    overrides: dict[str, str] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    actor = (actor or "researcher").strip() or "researcher"
    overrides = {str(k): str(v).strip() for k, v in (overrides or {}).items() if str(v).strip()}
    provider = (provider or "").strip() or None

    db = await get_db()
    try:
        await _ensure_schema(db)
        rows = await _project_rows(db, project_id)
    finally:
        await db.close()

    claim_rows = _derive_claims(rows["frozen_hypotheses"], claims)
    corpus = _card_corpus(rows["evidence_cards"])
    search_query = rows["project"]["research_question"] or " ".join(item["text"] for item in claim_rows[:2])
    provider_hits, provider_failure = await _provider_records(search_query, provider)
    corpus.extend(_search_corpus(provider_hits))

    findings, closest, gate = _evaluate_claims(claim_rows, corpus, overrides)
    if provider_failure is not None:
        findings = list(findings)
        findings.insert(0, {
            "severity": "critical",
            "code": "provider_failure",
            "message": (
                f"Provider '{provider_failure.get('provider')}' failed "
                f"({provider_failure.get('error_type')}); novelty cannot PASS on empty/outage results."
            ),
            "locator": "provider",
            "root_cause": provider_failure.get("root_cause") or "PROVIDER_FAILURE",
        })
        # Provider outage must not leave a green gate even if local cards exist;
        # empty corpus already blocks; non-empty still records the root cause.
        if not corpus:
            gate = {
                **gate,
                "passed": False,
                "status": "blocked",
                "reason": "provider_failure",
                "root_cause": "PROVIDER_FAILURE",
            }
        else:
            gate = {
                **gate,
                "provider_root_cause": "PROVIDER_FAILURE",
            }
    sources_version = _sha({
        "project": rows["project"],
        "claims": claim_rows,
        "evidence_card_ids": [card["id"] for card in rows["evidence_cards"]],
        "frozen_hypothesis_ids": [item["id"] for item in rows["frozen_hypotheses"]],
        "overrides": overrides,
        "provider": provider,
        "provider_hit_count": len(provider_hits),
        "provider_failure": provider_failure,
    })
    generated_at = datetime.now(timezone.utc).isoformat()
    document = {
        "format_version": "innovation-check/v1",
        "project": {
            "id": rows["project"]["id"],
            "title": rows["project"]["title"],
            "research_question": rows["project"]["research_question"],
        },
        "claims": claim_rows,
        "findings": findings,
        "closest_prior_art": closest,
        "gate": gate,
        "overrides": overrides,
        "provider": provider,
        "provider_failure": provider_failure,
        "corpus_size": len(corpus),
        "sources_version_sha256": sources_version,
        "generated_at": generated_at,
        "generator": "vibe.innovation-check/1.0",
    }
    relative_path = REPORT_RELATIVE
    path = _workspace(project_id) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(document)
    digest = hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw)

    check_id = uuid.uuid4().hex
    db = await get_db()
    try:
        await _ensure_schema(db)
        await db.execute(
            "INSERT INTO innovation_checks "
            "(id,project_id,status,gate_passed,claims_json,findings_json,closest_prior_art_json,"
            "report_path,report_sha256,sources_version_sha256,overrides_json,created_by,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (
                check_id,
                project_id,
                "blocked" if gate.get("status") == "blocked" else "completed",
                1 if gate["passed"] else 0,
                json.dumps(claim_rows, ensure_ascii=False),
                json.dumps(findings, ensure_ascii=False),
                json.dumps(closest, ensure_ascii=False),
                relative_path,
                digest,
                sources_version,
                json.dumps(overrides, ensure_ascii=False),
                actor,
            ),
        )
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                project_id,
                "innovation_check",
                digest,
                f"innovation-check:{sources_version}",
                "verified" if gate["passed"] else "needs_review",
            ),
        )
        await db.execute(
            "INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)",
            (
                project_id,
                "innovation_check_completed",
                actor,
                json.dumps(
                    {
                        "id": check_id,
                        "gate": gate,
                        "report_path": relative_path,
                        "report_sha256": digest,
                        "sources_version_sha256": sources_version,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        await db.commit()
        row = await (await db.execute("SELECT * FROM innovation_checks WHERE id=?", (check_id,))).fetchone()
    finally:
        await db.close()
    return _serialize_row(row, report=document)


async def snapshot_for_assurance(project_id: str) -> dict[str, Any]:
    """Compact snapshot consumed by the independent verification plane."""
    state = await read(project_id)
    artifact = state.get("artifact")
    file_hash = None
    if artifact and artifact.get("path"):
        path = _workspace(project_id) / artifact["path"]
        if path.is_file():
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "status": state.get("status"),
        "gate_passed": bool((state.get("gate") or {}).get("passed")),
        "artifact_path": (artifact or {}).get("path"),
        "sha256": (artifact or {}).get("sha256"),
        "file_sha256": file_hash,
        "low_novelty_claim_ids": list((state.get("gate") or {}).get("low_novelty_claim_ids") or []),
        "total_claims": int((state.get("gate") or {}).get("total_claims") or len(state.get("claims") or [])),
        "sources_version_sha256": state.get("sources_version_sha256"),
    }
