from domain.narrative.lint import NarrativeLint
def codes(text,**kw):return {x.code for x in NarrativeLint().check(text,**kw)}
def test_lint_blocks_internal_traces_engineering_language_and_unidentified_causality():
 result=codes('The agent workflow caused outcome. /backend/x [claim:C1]')
 assert {'internal_leak','engineering_prose','unsupported_causality'} <= result
def test_lint_requires_claim_id_and_detects_metrics_only_results():
 result=codes('Results: accuracy 0.9')
 assert {'missing_claim_id','metrics_only_results'} <= result
def test_identified_causal_language_and_scientific_discussion_pass():
 text='Results: mechanism supports claim; alternative and boundary considered [claim:C1]'
 assert not codes(text,causal_identified=True)
