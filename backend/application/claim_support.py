"""Independent claim/passage alignment; not a self-review by the claim author."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from domain.evidence.cards import ExtractedPassage
from infrastructure.literature.citation_verifier import CitationVerdict
class SupportRelation(str,Enum): SUPPORT='support'; CONTRADICT='contradict'; QUALIFY='qualify'; REJECT='reject'
@dataclass(frozen=True)
class SupportAssessment:
 relation:SupportRelation; quote:str; rationale:str; confidence:float; requires_human_approval:bool
class ClaimSupportVerifier:
 """Keyword-rule fixture implementation behind a distinct verifier boundary."""
 def assess(self,claim:str,passage:ExtractedPassage,citation:CitationVerdict)->SupportAssessment:
  if citation is not CitationVerdict.PASS:return SupportAssessment(SupportRelation.REJECT,passage.quote,'citation existence not verified',1.0,False)
  words={w.casefold().strip('.,') for w in claim.split() if len(w)>3}; quoted=passage.quote.casefold(); overlap=sum(word in quoted for word in words)/max(1,len(words))
  if 'not support' in quoted or 'contradict' in quoted:return SupportAssessment(SupportRelation.CONTRADICT,passage.quote,'passage contradicts claim',.95,False)
  if 'limited' in quoted or 'only' in quoted:return SupportAssessment(SupportRelation.QUALIFY,passage.quote,'passage limits scope',.75,False)
  if overlap>=.5:return SupportAssessment(SupportRelation.SUPPORT,passage.quote,'passage directly aligns',overlap,overlap<.8)
  return SupportAssessment(SupportRelation.REJECT,passage.quote,'passage does not support claim',overlap,False)
