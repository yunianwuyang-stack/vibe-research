from __future__ import annotations

import pytest

from manuscript_projection import (
    ClaimEdge,
    ClaimVersion,
    ManuscriptProjector,
    ProjectionError,
    RevisionPatch,
    ScientificFact,
    WriterDTO,
)


def supported_claim(*, claim_id: str = "C1", version: int = 1) -> ClaimVersion:
    return ClaimVersion(
        claim_id=claim_id,
        version=version,
        statement="The intervention was associated with a lower outcome.",
        strength="associational",
        scope="Adults in the registered sample",
        uncertainty="95% CI excludes the null",
        counterexamples=("No association was observed in the smallest subgroup.",),
        edges=(
            ClaimEdge("support", "evidence:E1"),
            ClaimEdge("qualify", "evidence:E2"),
        ),
        source_hash="a" * 64,
    )


def test_claim_version_requires_support_scope_uncertainty_and_counterexample():
    claim = supported_claim()
    assert claim.factual_coverage_complete
    with pytest.raises(ValueError, match="support edge"):
        ClaimVersion(
            claim_id="C2",
            version=1,
            statement="Unsupported",
            strength="causal",
            scope="sample",
            uncertainty="unknown",
            counterexamples=("none observed",),
            edges=(ClaimEdge("contradict", "evidence:E3"),),
            source_hash="b" * 64,
        )


def test_stale_claim_cannot_enter_writer_dto_and_control_plane_fields_are_unrepresentable():
    stale = supported_claim().mark_stale("evidence:E1 changed")
    with pytest.raises(ProjectionError, match="stale"):
        WriterDTO.build(
            claims=(stale,),
            facts=(ScientificFact("F1", "result", "The estimate was 2.0.", ("C1",)),),
            profile="causal_empirical",
            language="en",
        )
    assert set(WriterDTO.__dataclass_fields__) == {"claims", "facts", "profile", "language"}


def test_five_profiles_constrain_information_by_section():
    assert set(ManuscriptProjector.profile_names()) == {
        "causal_empirical",
        "ml_mechanism",
        "negative_result",
        "qualitative",
        "theory",
    }
    projector = ManuscriptProjector()
    dto = WriterDTO.build(
        claims=(supported_claim(),),
        facts=(
            ScientificFact("F1", "result", "The estimate was 2.0.", ("C1",)),
            ScientificFact("F2", "limitation", "The sample was geographically narrow.", ("C1",)),
        ),
        profile="causal_empirical",
        language="en",
    )
    with pytest.raises(ProjectionError, match="not allowed in Introduction"):
        projector.project(dto, {"Introduction": ("F1",), "Results": ("F1",), "Discussion": ("F2",)})


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Results: the agent pipeline completed module execution. [claim:C1]"),
        ("zh", "结果：智能体工作流完成了模块调用。[claim:C1]"),
    ],
)
def test_bilingual_anti_engineering_lint_blocks_control_plane_prose(language: str, text: str):
    issues = ManuscriptProjector().lint(text, language=language)
    assert "control_plane_leak" in {issue.code for issue in issues}


def test_unsupported_causal_and_novelty_upgrades_are_rejected():
    projector = ManuscriptProjector()
    causal = projector.lint("Results: treatment caused recovery. [claim:C1]", language="en")
    novelty = projector.lint("结果：这是全球首个方法。[claim:C1]", language="zh")
    assert "unsupported_causal_upgrade" in {issue.code for issue in causal}
    assert "unsupported_novelty_upgrade" in {issue.code for issue in novelty}


def test_revision_patch_is_atomic_and_compile_failure_preserves_original():
    projector = ManuscriptProjector()
    original = {
        "Introduction": "Prior evidence is mixed. [claim:C1]",
        "Results": "The estimate was 2.0. [claim:C1]",
    }
    revised = projector.apply_revision(
        original,
        RevisionPatch("Results", "The estimate was 2.0. [claim:C1]", "The adjusted estimate was 2.0. [claim:C1]"),
        compile_document=lambda sections: True,
    )
    assert revised["Results"].startswith("The adjusted")
    with pytest.raises(ProjectionError, match="compile failed"):
        projector.apply_revision(
            original,
            RevisionPatch("Results", "The estimate was 2.0. [claim:C1]", "Broken [claim:C1]"),
            compile_document=lambda sections: False,
        )
    assert original["Results"] == "The estimate was 2.0. [claim:C1]"
