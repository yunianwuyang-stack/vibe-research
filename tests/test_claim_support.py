from application.claim_support import ClaimSupportVerifier,SupportRelation
from domain.evidence.cards import ExtractedPassage,PassageLocator
from infrastructure.literature.citation_verifier import CitationVerdict
P=lambda q:ExtractedPassage('a'*64,q,PassageLocator(1,'Results',1))
def test_real_existing_paper_but_non_supporting_passage_is_rejected():
 a=ClaimSupportVerifier().assess('Treatment improves survival',P('The paper describes enrollment procedures.'),CitationVerdict.PASS)
 assert a.relation is SupportRelation.REJECT
def test_support_qualify_and_contradict_keep_quote_and_rationale():
 v=ClaimSupportVerifier()
 assert v.assess('Treatment improves survival',P('Treatment improves survival outcomes.'),CitationVerdict.PASS).relation is SupportRelation.SUPPORT
 assert v.assess('Treatment improves survival',P('Treatment only improves survival in subgroup.'),CitationVerdict.PASS).relation is SupportRelation.QUALIFY
 assert v.assess('Treatment improves survival',P('Results contradict survival improvement.'),CitationVerdict.PASS).relation is SupportRelation.CONTRADICT
def test_nonexistent_citation_is_rejected_before_support_reasoning():
 assert ClaimSupportVerifier().assess('claim',P('claim'),CitationVerdict.FAIL).relation is SupportRelation.REJECT
