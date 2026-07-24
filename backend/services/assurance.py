"""Unified deterministic final-submission assurance envelope."""
from __future__ import annotations

from typing import Any

from services import adversarial_review
from services.state_store import get_db


VERIFIER_VERSION = "vibe-assurance/1.0"
GATE_DEFINITIONS = (
    ("literature_evidence", "文献证据门"),
    ("study_design", "研究设计门"),
    ("innovation", "创新性门"),
    ("experiment_integrity", "实验完整性门"),
    ("statistical", "统计门"),
    ("result_to_claim", "结果—主张门"),
    ("numerical_paper", "稿件数字门"),
    ("reporting", "学术叙事门"),
    ("final_submission", "最终提交门"),
)


def _gate_for(code: str) -> str:
    if code.startswith("screening_") or code == "no_evidence_cards":
        return "literature_evidence"
    if code.startswith("missing_narrative") or code in {
        "narrative_not_approved", "missing_competing_explanations", "missing_boundaries", "missing_limitations",
        "missing_registered_hypothesis", "missing_frozen_hypothesis", "hypothesis_manifest_integrity_failed",
    }:
        return "study_design"
    if code.startswith("experiment_") or code in {"failed_experiment", "stale_experiment_dependency"}:
        return "experiment_integrity"
    if code == "statistics_gate_failed":
        return "statistical"
    if code.startswith("graph_") or code in {
        "missing_claim_evidence_graph", "unsupported_claims", "no_approved_support_links",
    }:
        return "result_to_claim"
    if code.startswith("innovation_") or code in {
        "missing_innovation_check", "low_novelty_without_override", "missing_novelty_claims",
    }:
        return "innovation"
    if code == "draft_unverified_number":
        return "numerical_paper"
    if code.startswith("draft_") and code != "draft_not_generated":
        return "reporting"
    return "final_submission"


def _repair_action(finding: dict[str, Any]) -> dict[str, str]:
    code = str(finding.get("code", "unknown"))
    actions = {
        "no_evidence_cards": "保存可追溯的文献记录并分别完成人工引用核验与主张支持核验。",
        "screening_protocol_inactive": "激活已保存的筛选协议。",
        "screening_incomplete": "为所有证据卡记录纳入、排除或待定决定及理由。",
        "missing_narrative_map": "建立包含竞争解释、边界条件和局限的研究者论证图。",
        "narrative_not_approved": "由研究者人工批准当前论证图。",
        "missing_claim_evidence_graph": "把论证图主张连接到证据卡并保存图谱。",
        "unsupported_claims": "为所有主张建立已人工批准的支持链接；对应证据卡的引用和主张支持状态必须同时获批。",
        "no_approved_support_links": "至少批准一条具有原文定位的文献支持，或一条绑定当前冻结假设、统计门禁与完整哈希血缘的实验支持。",
        "statistics_gate_failed": "补齐统计方案、重复种子、效应量和置信区间后重新执行实验。",
        "experiment_lineage_missing": "重新执行实验以生成完整 manifest 与结果哈希。",
        "draft_not_generated": "从已批准的论证图与证据生成并保存科学稿件。",
        "missing_independent_review": "运行确定性独立审查并保存可核验报告。",
        "stale_independent_review": "上游状态已变化；重新运行确定性独立审查。",
        "missing_innovation_check": "对当前冻结假设运行创新性/新颖性核验并保存可核验报告。",
        "innovation_report_missing": "重新运行创新性核验以重建报告产物。",
        "innovation_report_hash_mismatch": "重新运行创新性核验使报告哈希与台账一致。",
        "innovation_gate_failed": "改写主张以拉开与既有工作的差距，或对 LOW 新颖性主张填写研究者 override 理由。",
        "low_novelty_without_override": "为 LOW 新颖性主张补充研究者 override 理由，或改写主张后重跑核验。",
        "missing_novelty_claims": "先冻结假设或显式提交创新点声明。",
        "missing_registered_hypothesis": "注册规范化、可寻址的版本化假设清单。",
        "missing_frozen_hypothesis": "冻结至少一个当前注册假设后再执行确认性分析或生成稿件。",
        "hypothesis_manifest_integrity_failed": "恢复或重建与台账内容和哈希一致的假设清单。",
        "stale_experiment_dependency": "基于当前冻结假设重新执行实验；历史失效结果不得支持主张。",
        "experiment_manifest_integrity_failed": "重新执行实验，使规格、假设绑定、结果和 manifest 哈希重新一致。",
        "stale_draft_hypothesis": "从当前冻结假设注册表重新生成稿件。",
        "draft_hypothesis_frontmatter_invalid": "重新生成稿件；假设来源 frontmatter 不可编辑。",
    }
    action = actions.get(code)
    if action is None and code == "draft_unverified_number":
        action = "删除无法追溯的结果数字，或先生成通过统计门的实验结果再引用该数字。"
    if action is None and code.startswith("draft_"):
        action = "根据定位信息修订稿件并重新运行确定性审查。"
    if action is None:
        action = "处理该发现后重新运行确定性独立审查。"
    return {"finding_code": code, "action": action}


async def read(project_id: str) -> dict[str, Any]:
    snapshot = await adversarial_review._snapshot(project_id)
    inputs_sha256 = adversarial_review._sha(snapshot)
    findings = list(await adversarial_review._deterministic_findings(project_id, snapshot))
    db = await get_db()
    try:
        latest = await (await db.execute(
            "SELECT id,status,verdict,inputs_sha256,report_path,report_sha256,created_at,updated_at "
            "FROM adversarial_reviews WHERE project_id=? AND mode='deterministic' ORDER BY rowid DESC LIMIT 1",
            (project_id,),
        )).fetchone()
        current = await (await db.execute(
            "SELECT id,status,verdict,inputs_sha256,report_path,report_sha256,created_at,updated_at "
            "FROM adversarial_reviews WHERE project_id=? AND mode='deterministic' AND status='completed' "
            "AND verdict='pass' AND inputs_sha256=? ORDER BY rowid DESC LIMIT 1",
            (project_id, inputs_sha256),
        )).fetchone()
    finally:
        await db.close()
    latest_value = dict(latest) if latest else None
    if current is None:
        if latest_value and latest_value["inputs_sha256"] != inputs_sha256:
            findings.append({
                "severity": "critical", "code": "stale_independent_review",
                "message": "The latest deterministic review is stale because persisted project inputs changed.",
                "locator": latest_value["id"],
            })
        else:
            findings.append({
                "severity": "critical", "code": "missing_independent_review",
                "message": "A current passing deterministic independent review is required.", "locator": "",
            })
    grouped: dict[str, list[dict[str, Any]]] = {gate_id: [] for gate_id, _ in GATE_DEFINITIONS}
    for finding in findings:
        grouped[_gate_for(str(finding.get("code", "")))].append(finding)
    gates = []
    for gate_id, label in GATE_DEFINITIONS:
        gate_findings = grouped[gate_id]
        if any(item.get("severity") in {"critical", "major"} for item in gate_findings):
            gate_status = "BLOCKED"
        elif gate_findings:
            gate_status = "WARN"
        else:
            gate_status = "PASS"
        gates.append({"id": gate_id, "label": label, "status": gate_status, "findings": gate_findings})
    if any(item["status"] == "BLOCKED" for item in gates):
        status = "BLOCKED"
    elif any(item["status"] == "WARN" for item in gates):
        status = "WARN"
    else:
        status = "PASS"
    current_value = dict(current) if current else None
    return {
        "format_version": "assurance-envelope/v1",
        "status": status,
        "submission_ready": status == "PASS",
        "input_hashes": {
            "project_snapshot_sha256": inputs_sha256,
            "latest_review_inputs_sha256": latest_value["inputs_sha256"] if latest_value else None,
            "review_report_sha256": current_value["report_sha256"] if current_value else None,
        },
        "findings": findings,
        "repair_actions": [_repair_action(item) for item in findings if item.get("severity") in {"critical", "major"}],
        "verifier_version": VERIFIER_VERSION,
        "independent_from_generator": True,
        "gates": gates,
        "current_review": current_value,
        "latest_review": latest_value,
    }
