"""Generate editable drafts strictly from human-approved citation cards."""
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


def _workspace(project_id: str) -> Path:
    workspace = (WORKSPACES_DIR / project_id).resolve()
    workspace.relative_to(WORKSPACES_DIR.resolve())
    return workspace


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise HTTPException(409, detail="Draft provenance frontmatter is missing")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as error:
        raise HTTPException(409, detail="Draft provenance frontmatter is not closed") from error
    values: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        if ":" not in line:
            raise HTTPException(409, detail="Draft provenance frontmatter contains an invalid line")
        key, value = line.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in values:
            raise HTTPException(409, detail="Draft provenance frontmatter contains an invalid or duplicate key")
        values[key] = value.strip()
    return values


def body_for_scientific_audit(content: str) -> str:
    """Exclude separately verified machine provenance from prose linting."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration:
        return content
    return "\n" * (end + 1) + "\n".join(lines[end + 1 :])


def _validate_hypothesis_frontmatter(
    content: str,
    project_id: str,
    hypothesis_set: dict[str, Any],
) -> dict[str, str]:
    values = _frontmatter(content)
    schema = {
        "project_id",
        "evidence_version_sha256",
        "claim_evidence_graph_sha256",
        "hypothesis_manifest_sha256",
        "hypothesis_manifest_set_sha256",
        "hypothesis_bindings_json",
        "generated_at_utc",
        "generator_policy",
        "citation_policy",
    }
    if set(values) != schema:
        raise HTTPException(
            409,
            detail={
                "message": "Draft provenance frontmatter schema was modified",
                "missing": sorted(schema - set(values)),
                "unexpected": sorted(set(values) - schema),
            },
        )
    expected_bindings = _canonical(hypothesis_set["bindings"])
    expected_hash = hypothesis_set["manifest_set_sha256"]
    required = {
        "project_id": project_id,
        "hypothesis_manifest_sha256": expected_hash,
        "hypothesis_manifest_set_sha256": expected_hash,
        "hypothesis_bindings_json": expected_bindings,
        "generator_policy": "approved-citations-and-frozen-hypotheses-only",
        "citation_policy": "approved-citations-only",
    }
    mismatches = [key for key, expected in required.items() if values.get(key) != expected]
    if mismatches:
        raise HTTPException(
            409,
            detail={
                "message": "Draft hypothesis provenance is missing, stale, or modified",
                "fields": mismatches,
            },
        )
    for key in ("evidence_version_sha256", "claim_evidence_graph_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", values[key]):
            raise HTTPException(409, detail=f"Draft frontmatter {key} is not a SHA-256 digest")
    try:
        generated_at = datetime.fromisoformat(values["generated_at_utc"].replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(409, detail="Draft generated_at_utc is invalid") from error
    if generated_at.tzinfo is None:
        raise HTTPException(409, detail="Draft generated_at_utc must include a timezone")
    return values


async def _eligible_numeric_registry(db: Any, project_id: str) -> list[Any]:
    """Numbers may only come from current, intact confirmatory experiments."""
    from domain.assurance.numeric_registry import NumericValue
    from services import experiment_execution

    await experiment_execution._ensure_schema(db)
    rows = await (await db.execute(
        "SELECT * FROM experiment_runs WHERE project_id=? AND status='completed' AND exit_code=0 "
        "AND analysis_mode='confirmatory' AND dependency_status='current' ORDER BY created_at",
        (project_id,),
    )).fetchall()
    values: list[Any] = []
    for row in rows:
        integrity = await experiment_execution.inspect_run_integrity(db, row)
        if not integrity["passed"]:
            continue
        statistics = json.loads(row["statistics_json"])
        if not statistics.get("passed"):
            continue
        result = json.loads(row["result_json"])
        metric = str(result.get("metric", "outcome"))
        digest = row["result_sha256"]
        for key in ("control_mean", "treatment_mean", "difference", "standard_error"):
            if key in result:
                values.append(NumericValue(f"experiment.{key}", float(result[key]), key, digest, row["id"], metric))
        for index, value in enumerate(result.get("ci95", [])):
            values.append(NumericValue("experiment.ci95", float(value), f"ci95[{index}]", digest, row["id"], metric))
    return values


async def generate(project_id: str) -> dict[str, Any]:
    from services.scientific_narrative import read_map
    from services.claim_evidence import read_graph
    from services import hypothesis_lifecycle
    try:
        narrative = await read_map(project_id)
    except HTTPException as error:
        if error.status_code == 404: raise HTTPException(status_code=409, detail="Researcher-owned argument map is required before draft generation") from error
        raise
    if not narrative["approved"]: raise HTTPException(status_code=409, detail="Human approval of the argument map is required before draft generation")
    graph = await read_graph(project_id)
    if not graph["gate"]["passed"]:
        missing = ", ".join(graph["gate"]["unsupported_claim_ids"])
        raise HTTPException(status_code=409, detail=f"Every narrative claim requires approved supporting evidence. Missing: {missing}")
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await hypothesis_lifecycle._ensure_schema(db)
        hypothesis_set = await hypothesis_lifecycle.current_frozen_manifest_set(db, project_id)
        registry = await _eligible_numeric_registry(db, project_id)
        project = await (await db.execute("SELECT * FROM research_projects WHERE id=?", (project_id,))).fetchone()
        if not project: raise HTTPException(status_code=404, detail="Research project not found")
        direct_card_rows = await (await db.execute(
            "SELECT DISTINCT card.id FROM evidence_cards card JOIN claim_evidence_links link ON link.evidence_card_id=card.id "
            "WHERE card.project_id=? AND card.citation_status='approved' AND card.claim_support_status='approved' "
            "AND link.status='approved' AND link.relation='supports'",
            (project_id,),
        )).fetchall()
        experiment_basis_rows = await (await db.execute(
            "SELECT evidence_card_ids_json FROM claim_experiment_links WHERE project_id=? AND status='approved' AND relation='supports'",
            (project_id,),
        )).fetchall()
        card_ids = {row["id"] for row in direct_card_rows}
        for row in experiment_basis_rows:
            card_ids.update(str(value) for value in json.loads(row["evidence_card_ids_json"]) if str(value))
        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            cards = await (await db.execute(
                f"SELECT * FROM evidence_cards WHERE project_id=? AND citation_status='approved' AND claim_support_status='approved' "
                f"AND id IN ({placeholders}) ORDER BY created_at,id",
                (project_id, *sorted(card_ids)),
            )).fetchall()
        else:
            cards = []
        if not cards: raise HTTPException(status_code=409, detail="At least one approved Claim-Evidence support link is required before draft generation")
        evidence = [dict(card) for card in cards]
        evidence_version = hashlib.sha256(json.dumps({"evidence": evidence, "graph_sha256": graph["artifact"]["sha256"], "hypothesis_manifest_set_sha256": hypothesis_set["manifest_set_sha256"]}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        generated_at = datetime.now(timezone.utc).isoformat()
        references = "\n".join(f"{index}. {card['title']} ({card['publication_year'] or 'n.d.'}). {card['doi'] or card['canonical_url']}" for index,card in enumerate(evidence,1))
        claim_id = narrative["claims"][0]
        hypotheses = "\n".join(
            f"- {item['statement']} Prediction: {item['prediction']} Falsifier: {item['falsification_criteria']} "
            f"[hypothesis:{item['hypothesis_id']}:v{item['version']}:{item['manifest_sha256']}]"
            for item in hypothesis_set["hypotheses"]
        )
        claims = "\n".join(f"- {item}" for item in narrative["claims"])
        numeric_lines = "\n".join(f"- {value.metric} / {value.condition}: {value.value:.6g} [claim:{claim_id}] (run {value.run_id}, artifact {value.artifact_hash})" for value in registry) or f"尚无通过统计门禁的实验数字。[claim:{claim_id}]"
        markdown = f"""---
project_id: {project_id}
evidence_version_sha256: {evidence_version}
claim_evidence_graph_sha256: {graph["artifact"]["sha256"]}
hypothesis_manifest_sha256: {hypothesis_set["manifest_set_sha256"]}
hypothesis_manifest_set_sha256: {hypothesis_set["manifest_set_sha256"]}
hypothesis_bindings_json: {_canonical(hypothesis_set["bindings"])}
generated_at_utc: {generated_at}
generator_policy: approved-citations-and-frozen-hypotheses-only
citation_policy: approved-citations-only
---

# {project['title']}

## 研究问题

{project['research_question']}

## 纳入与排除标准

{project['inclusion_criteria']}

## 引言

本节等待研究者基于下列已核验引用撰写研究张力、机制与贡献。系统不会把“引用存在”自动解释为“支持某项主张”。

## 证据综合

当前已纳入 {len(evidence)} 条经人工核对的引用。每项 claim support 仍须在证据卡中单独判断；未知状态不得改写为支持。

## 方法

请在此记录检索策略、筛选流程、分析方法与可复现条件。

## 结果

尚无经验证的数字或实验结果；在数字注册表或实验产物获批前，本节不得生成结论性数字。

## 讨论

请补充竞争解释、边界条件、局限与可证伪预测。

## 参考文献

{references}
"""
        markdown = markdown.replace("## 引言", f"## 引言\n\n文献张力：{narrative['tension']} [claim:{claim_id}]\n\n候选机制：{narrative['mechanism']} [claim:{claim_id}]\n\n### 假设\n{hypotheses}\n\n### 经研究者批准的主张\n{claims}", 1)
        # Registered hypothesis lines already carry their immutable manifest locator.
        for claim in narrative["claims"]: markdown = markdown.replace(f"- {claim}", f"- {claim} [claim:{claim}]" )
        lines=[]
        for line in markdown.splitlines():
            if line.strip() and not line.lstrip().startswith(('#','---','project_id:','evidence_version_sha256:','claim_evidence_graph_sha256:','hypothesis_manifest_sha256:','hypothesis_manifest_set_sha256:','hypothesis_bindings_json:','generated_at_utc:','generator_policy:','citation_policy:')) and not re.match(r'^\d+\. ',line.strip()) and '[claim:' not in line.casefold(): line += f" [claim:{claim_id}]"
            lines.append(line)
        markdown='\n'.join(lines)+'\n'
        markdown = re.sub(r"## 结果\n.*?(?=## 讨论)", f"## 结果\n\n{numeric_lines}\n\n", markdown, flags=re.S)
        discussion = f"## 讨论\n\n替代解释：{'；'.join(narrative['competing_explanations'])} [claim:{claim_id}]\n\n边界条件：{'；'.join(narrative['boundaries'])} [claim:{claim_id}]\n\n局限：{'；'.join(narrative['limitations'])} [claim:{claim_id}]\n\n"
        markdown = re.sub(r"## 讨论\n.*?(?=## 参考文献)", discussion, markdown, flags=re.S)
        latex_references = "\n".join(f"\\item {card['title']} ({card['publication_year'] or 'n.d.'}). \\url{{{card['canonical_url']}}}" for card in evidence)
        latex = f"""\\documentclass{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{hyperref}}
\\title{{{project['title']}}}
\\begin{{document}}
\\maketitle
\\section{{研究问题}}
{project['research_question']}
\\section{{证据综合}}
仅列入人工核对的引用；claim support 仍需独立审批。
\\begin{{enumerate}}
{latex_references}
\\end{{enumerate}}
\\end{{document}}
"""
        workspace = _workspace(project_id); paper = workspace / "paper"; paper.mkdir(parents=True, exist_ok=True)
        md_path = paper / "main.md"; tex_path = paper / "main.tex"
        md_path.write_text(markdown, encoding="utf-8", newline="\n"); tex_path.write_text(latex, encoding="utf-8", newline="\n")
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        _validate_hypothesis_frontmatter(markdown, project_id, hypothesis_set)
        draft_id = uuid.uuid4().hex
        artifact_id = uuid.uuid4().hex
        previous = await (await db.execute(
            "SELECT id,artifact_id FROM approved_drafts WHERE project_id=? AND status='current'",
            (project_id,),
        )).fetchall()
        await db.execute(
            "UPDATE approved_drafts SET status='superseded',stale_reason='A new draft was generated',updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND status='current'",
            (project_id,),
        )
        for old in previous:
            await db.execute("UPDATE research_artifacts SET status='superseded' WHERE id=?", (old["artifact_id"],))
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, project_id, "approved_draft", digest, f"approved-evidence:{evidence_version}:hypotheses:{hypothesis_set['manifest_set_sha256']}", "needs_review"),
        )
        await db.execute(
            "INSERT INTO approved_drafts (id,project_id,artifact_id,path,sha256,evidence_version_sha256,claim_evidence_graph_sha256,hypothesis_manifest_set_sha256,hypothesis_bindings_json,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                draft_id,
                project_id,
                artifact_id,
                "paper/main.md",
                digest,
                evidence_version,
                graph["artifact"]["sha256"],
                hypothesis_set["manifest_set_sha256"],
                _canonical(hypothesis_set["bindings"]),
                "current",
            ),
        )
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"approved_draft_generated","system",json.dumps({"draft_id":draft_id,"path":"paper/main.md","sha256":digest,"evidence_version_sha256":evidence_version,"claim_evidence_graph_sha256":graph["artifact"]["sha256"],"hypothesis_manifest_set_sha256":hypothesis_set["manifest_set_sha256"],"hypothesis_bindings":hypothesis_set["bindings"]}, ensure_ascii=False, sort_keys=True)))
        await db.commit()
        return {"project_id":project_id,"draft_id":draft_id,"path":"paper/main.md","latex_path":"paper/main.tex","content":markdown,"sha256":digest,"evidence_version_sha256":evidence_version,"claim_evidence_graph_sha256":graph["artifact"]["sha256"],"hypothesis_manifest_set_sha256":hypothesis_set["manifest_set_sha256"],"hypothesis_bindings":hypothesis_set["bindings"],"status":"current"}
    except Exception:
        await db.rollback()
        raise
    finally: await db.close()


async def read(project_id: str) -> dict[str, Any]:
    path = _workspace(project_id) / "paper" / "main.md"
    if not path.is_file(): raise HTTPException(status_code=404, detail="Draft has not been generated")
    content = path.read_text(encoding="utf-8")
    from services import hypothesis_lifecycle

    db = await get_db()
    try:
        await hypothesis_lifecycle._ensure_schema(db)
        record = await (await db.execute(
            "SELECT * FROM approved_drafts WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (project_id,),
        )).fetchone()
        hypothesis_set = await hypothesis_lifecycle.current_frozen_manifest_set(db, project_id, require=False)
    finally:
        await db.close()
    validation: dict[str, Any]
    try:
        _validate_hypothesis_frontmatter(content, project_id, hypothesis_set)
        validation = {"passed": True, "issues": []}
    except HTTPException as error:
        validation = {"passed": False, "issues": [error.detail]}
    digest = hashlib.sha256(content.encode()).hexdigest()
    value = dict(record) if record else None
    if value and value["sha256"] != digest:
        validation["passed"] = False
        validation["issues"].append("draft_file_hash_mismatch")
    return {
        "project_id": project_id,
        "draft_id": value["id"] if value else None,
        "path": "paper/main.md",
        "content": content,
        "sha256": digest,
        "status": value["status"] if value else "stale",
        "stale_reason": value["stale_reason"] if value else "Draft predates the registered hypothesis ledger",
        "hypothesis_validation": validation,
    }


async def save(project_id: str, content: str) -> dict[str, Any]:
    path = _workspace(project_id) / "paper" / "main.md"
    if not path.is_file(): raise HTTPException(status_code=404, detail="Draft has not been generated")
    from services.scientific_narrative import audit_text
    from services.claim_evidence import read_graph
    from services import hypothesis_lifecycle
    from domain.assurance.paper_numbers import PaperNumericVerifier

    dependency_db = await get_db()
    try:
        await hypothesis_lifecycle.current_frozen_manifest_set(dependency_db, project_id)
    finally:
        await dependency_db.close()
    graph = await read_graph(project_id)
    if not graph["gate"]["passed"]:
        raise HTTPException(status_code=409, detail="Claim-Evidence graph no longer satisfies the writing gate; regenerate the draft")
    audit = await audit_text(project_id, body_for_scientific_audit(content))
    if not audit["passed"]: raise HTTPException(status_code=409, detail={"message":"Scientific narrative audit failed","issues":audit["issues"]})
    db = await get_db()
    try:
        await db.execute("BEGIN IMMEDIATE")
        await hypothesis_lifecycle._ensure_schema(db)
        hypothesis_set = await hypothesis_lifecycle.current_frozen_manifest_set(db, project_id)
        frontmatter = _validate_hypothesis_frontmatter(content, project_id, hypothesis_set)
        if frontmatter.get("claim_evidence_graph_sha256") != graph["artifact"]["sha256"]:
            raise HTTPException(status_code=409, detail="Draft Claim-Evidence graph version is stale; regenerate the draft")
        record = await (await db.execute(
            "SELECT * FROM approved_drafts WHERE project_id=? AND status='current' ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (project_id,),
        )).fetchone()
        if not record:
            raise HTTPException(409, detail="The persisted draft is stale; regenerate it from current frozen hypotheses")
        persisted_content = path.read_text(encoding="utf-8")
        if hashlib.sha256(persisted_content.encode("utf-8")).hexdigest() != record["sha256"]:
            raise HTTPException(409, detail="The persisted draft file no longer matches its artifact ledger")
        if _frontmatter(content) != _frontmatter(persisted_content):
            raise HTTPException(409, detail="Draft provenance frontmatter is immutable")
        if (
            record["hypothesis_manifest_set_sha256"] != hypothesis_set["manifest_set_sha256"]
            or record["hypothesis_bindings_json"] != _canonical(hypothesis_set["bindings"])
            or frontmatter["evidence_version_sha256"] != record["evidence_version_sha256"]
            or frontmatter["claim_evidence_graph_sha256"] != record["claim_evidence_graph_sha256"]
        ):
            raise HTTPException(409, detail="The draft provenance dependency record is stale or modified")
        eligible_registry = await _eligible_numeric_registry(db, project_id)
        invalid_numbers = [
            finding.__dict__
            for finding in PaperNumericVerifier().verify(content, eligible_registry)
            if not finding.verified
        ]
        if invalid_numbers:
            raise HTTPException(409, detail={"message": "Draft contains numbers without a current confirmatory experiment", "issues": invalid_numbers})
        candidate_path = path.with_suffix(".md.candidate")
        candidate_path.write_text(content, encoding="utf-8", newline="\n")
        try:
            if candidate_path.read_bytes() != content.encode("utf-8"):
                raise HTTPException(500, detail="Draft candidate staging verification failed; original preserved")
            candidate_path.replace(path)
        finally:
            candidate_path.unlink(missing_ok=True)
        digest = hashlib.sha256(content.encode()).hexdigest()
        artifact_id = uuid.uuid4().hex
        await db.execute("UPDATE research_artifacts SET status='superseded' WHERE id=?", (record["artifact_id"],))
        await db.execute(
            "INSERT INTO research_artifacts (id,project_id,kind,sha256,provenance,status) VALUES (?,?,?,?,?,?)",
            (artifact_id, project_id, "approved_draft", digest, f"human-edit:{record['id']}:hypotheses:{hypothesis_set['manifest_set_sha256']}", "needs_review"),
        )
        await db.execute(
            "UPDATE approved_drafts SET artifact_id=?,sha256=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (artifact_id, digest, record["id"]),
        )
        await db.execute("INSERT INTO research_events (project_id,event_type,actor,payload) VALUES (?,?,?,?)", (project_id,"draft_saved","human",json.dumps({"draft_id":record["id"],"path":"paper/main.md","sha256":digest,"hypothesis_manifest_set_sha256":hypothesis_set["manifest_set_sha256"]}, ensure_ascii=False, sort_keys=True)))
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally: await db.close()
    return {"ok":True,"sha256":digest,"hypothesis_manifest_set_sha256":hypothesis_set["manifest_set_sha256"]}
