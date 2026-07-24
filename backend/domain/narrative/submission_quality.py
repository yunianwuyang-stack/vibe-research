"""Evidence readiness is independent of manuscript length, size, or review score."""
from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class SubmissionAssessment: ready:bool; reasons:tuple[str,...]; format_compliant:bool
class SubmissionQualityGate:
 def assess(self,*,claims_supported:bool,citations_verified:bool,numbers_verified:bool,approval:bool,page_count:int,file_kb:int,review_score:int,competition_page_rule:int|None=None)->SubmissionAssessment:
  reasons=[]
  if not all((claims_supported,citations_verified,numbers_verified,approval)):reasons.append('scientific evidence or approval incomplete')
  compliant=competition_page_rule is None or page_count<=competition_page_rule
  if not compliant:reasons.append('competition format page limit exceeded')
  return SubmissionAssessment(not reasons,tuple(reasons),compliant)
