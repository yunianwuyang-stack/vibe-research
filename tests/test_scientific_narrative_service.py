from __future__ import annotations

import asyncio
from pathlib import Path


async def _ready_project(db_path: Path, workspaces: Path) -> str:
    """Create a project with P5 gates green so real execution can complete."""
    import services.experiment_execution as experiments
    import services.hypothesis_lifecycle as hypothesis
    import services.p5_research_design as p5
    import services.research_contracts as contracts
    import services.state_store as store

    store.DB_PATH = db_path
    experiments.WORKSPACES_DIR = workspaces
    hypothesis.WORKSPACES_DIR = workspaces
    await store.init_db()
    project_id = (
        await contracts.create_contract(
            "Narrative",
            "Does treatment change outcome?",
            "numeric study",
        )
    )["id"]
    await p5.save_design(
        project_id,
        {"theoretical": False, "empirical": True, "falsifier": "null effect"},
        "experimental_ml",
        {
            "baseline": "baseline",
            "ablation_plan": "ablation",
            "evaluation_metric": "score",
            "falsification_criteria": "null effect",
        },
        "researcher",
    )
    await p5.freeze_prior_art(
        project_id,
        "2026-07-19",
        {},
        [
            {
                "title": "Prior A",
                "source_url": "https://a.example/paper",
                "similarities": "same question",
                "differences": "different design",
                "evidence_strength": "strong",
            },
            {
                "title": "Prior B",
                "source_url": "https://b.example/paper",
                "similarities": "same question",
                "differences": "different metric",
                "evidence_strength": "strong",
            },
        ],
        "researcher",
    )
    await p5.assess_ethics(
        project_id,
        {
            "subjects": "numeric observations",
            "jurisdiction": "local",
            "irb_status": "not_required",
            "consent_status": "not_required",
            "dua_status": "verified",
            "license_status": "verified",
            "pii_categories": [],
            "allowed_use": "research",
            "retention_deletion": "delete after study",
        },
        "researcher",
    )
    return project_id


def test_argument_map_approval_numeric_registry_and_adversarial_audit(tmp_path):
    import services.experiment_execution as experiments
    import services.hypothesis_lifecycle as hypothesis
    import services.p5_research_design as p5
    import services.scientific_narrative as narrative
    import services.state_store as store

    async def go():
        project_id = await _ready_project(tmp_path / "vibe.db", tmp_path / "workspaces")
        store.DB_PATH = tmp_path / "vibe.db"
        values = {
            "question": "Does treatment change outcome?",
            "tension": "Prior findings conflict",
            "mechanism": "Treatment changes the measured pathway",
            "hypotheses": ["H1 predicts a positive difference"],
            "claims": ["C1"],
            "competing_explanations": ["measurement drift"],
            "boundaries": ["this sample and metric"],
            "limitations": ["small sample"],
        }
        saved = await narrative.save_map(project_id, values)
        assert saved["approved"] is False
        approved = await narrative.approve_map(project_id, "researcher")
        assert approved["approved"] is True
        version = await hypothesis.create(
            project_id,
            {
                "statement": "Treatment changes the measured outcome",
                "mechanism": "Treatment changes the measured pathway",
                "prediction": "Treatment mean exceeds control mean",
                "falsification_criteria": "No positive difference after multi-seed replication",
                "boundary_conditions": "numeric observations only",
            },
            "researcher",
            "register baseline hypothesis",
        )
        frozen = await hypothesis.transition(
            project_id, version["id"], "freeze", "researcher", "lock for confirmatory run"
        )
        protocol = {
            "estimand": "difference",
            "outcome": "score",
            "exposure": "treatment",
            "baseline": "baseline",
            "ablation_plan": "ablation",
            "falsification_criteria": "null effect",
        }
        # Latest protocol mode must match analysis_mode for execution admission.
        await p5.save_protocol(project_id, protocol, "exploratory", "researcher")
        exploratory = await experiments.execute(
            project_id,
            {"control": [1, 2, 3], "treatment": [3, 4, 5], "seeds": 3, "metric": "score"},
        )
        assert exploratory["status"] == "completed"
        empty = await narrative.numeric_registry(project_id)
        assert empty == [] or all(item.run_id != exploratory["id"] for item in empty)

        await p5.save_protocol(project_id, protocol, "confirmatory", "researcher")
        run = await experiments.execute(
            project_id,
            {
                "control": [1, 2, 3],
                "treatment": [3, 4, 5],
                "seeds": 3,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": frozen["id"],
            },
        )
        assert run["status"] == "completed", run
        registry = await narrative.numeric_registry(project_id)
        assert registry and all(item.run_id == run["id"] for item in registry)
        good = await narrative.audit_text(
            project_id,
            "Results: mechanism, alternative and boundary; score difference was 2.0. [claim:C1]",
        )
        assert good["passed"]
        fake = await narrative.audit_text(project_id, "Results: score was 999.0. [claim:C1]")
        assert not fake["passed"] and any(item["code"] == "unverified_number" for item in fake["issues"])
        leaked = await narrative.audit_text(
            project_id, "The agent workflow caused outcome. /backend/x [claim:C1]"
        )
        codes = {item["code"] for item in leaked["issues"]}
        assert {"internal_leak", "engineering_prose", "unsupported_causality"} <= codes

    asyncio.run(go())


def test_three_public_case_rubrics_require_scientific_structure():
    from domain.narrative.lint import NarrativeLint

    cases = {
        "literature_theory": "Introduction: tension and mechanism with contribution [claim:C1]\nDiscussion: alternative explanation and boundary condition [claim:C1]",
        "public_data_empirical": "Results: mechanism, negative result, alternative and boundary [claim:C1]\nDiscussion: limitation and competing explanation [claim:C1]",
        "method_computation": "Methods: reproducible calculation conditions [claim:C1]\nResults: mechanism, alternative and boundary [claim:C1]",
    }
    for name, text in cases.items():
        issues = NarrativeLint().check(text, causal_identified=False)
        assert not issues, (name, issues)
