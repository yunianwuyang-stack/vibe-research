from domain.narrative.submission_quality import SubmissionQualityGate
def test_short_evidence_complete_manuscript_is_ready_without_page_kb_or_score_proxy():
 r=SubmissionQualityGate().assess(claims_supported=True,citations_verified=True,numbers_verified=True,approval=True,page_count=2,file_kb=5,review_score=1);assert r.ready
def test_long_unsupported_manuscript_is_rejected_and_six_of_ten_does_not_control_ready():
 r=SubmissionQualityGate().assess(claims_supported=False,citations_verified=True,numbers_verified=True,approval=True,page_count=100,file_kb=9999,review_score=10);assert not r.ready
def test_explicit_competition_page_rule_is_format_not_filler_driver():
 r=SubmissionQualityGate().assess(claims_supported=True,citations_verified=True,numbers_verified=True,approval=True,page_count=11,file_kb=1,review_score=6,competition_page_rule=10);assert not r.ready and not r.format_compliant
