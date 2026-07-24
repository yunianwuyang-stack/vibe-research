"""Ownership checkpoint that blocks drafting until the researcher approves claims."""
from __future__ import annotations
from dataclasses import dataclass,replace
@dataclass(frozen=True)
class ParagraphBrief: claim_id:str; rhetorical_role:str; text:str
@dataclass(frozen=True)
class ArgumentMap:
 claims:tuple[str,...]; mechanism:str; competing_explanations:tuple[str,...]; boundaries:tuple[str,...]; approved:bool=False; claim_strength:str='moderate'
 def approve(self)->'ArgumentMap':return replace(self,approved=True)
 def revise_strength(self,strength:str)->'ArgumentMap':return replace(self,claim_strength=strength,approved=False)
class NarrativeDraftGate:
 def draft(self,map:ArgumentMap,briefs:tuple[ParagraphBrief,...])->tuple[ParagraphBrief,...]:
  if not map.approved:raise PermissionError('draft blocked pending ownership approval')
  if any(x.claim_id not in map.claims for x in briefs):raise ValueError('AI cannot add a principal claim')
  if any(not x.rhetorical_role.strip() for x in briefs):raise ValueError('every paragraph needs rhetorical role')
  return briefs
