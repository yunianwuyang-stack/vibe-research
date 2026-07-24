"""Deterministic guard against engineering-report prose and unsupported causality."""
from __future__ import annotations
from dataclasses import dataclass
import re

_ENGINEERING_PROSE = re.compile(
 r"\b(?:agent|pipeline|module|workflow|api|queue|developer log|agent\s+(?:trace|task|run|executor)|(?:workflow|pipeline)\s+(?:run|execution|log|status|step|trace|completed))\b|"
 r"智能体|代理|流水线|管线|模块|工作流|接口调用|队列|开发日志",
 re.IGNORECASE,
)
_CAUSALITY = re.compile(r"\b(?:causes|caused|causal effect|therefore causes)\b|导致|造成|因果效应", re.IGNORECASE)
_NOVELTY = re.compile(r"\b(?:first ever|world(?:'s)? first|unprecedented)\b|全球首个|世界首次|前所未有", re.IGNORECASE)
_NEGATED_CAUSAL_PREFIX = re.compile(
 r"\b(?:no|not|never|without|lack(?:s|ing)?|(?:does|do|did|can|could|will|would|should|may|might|is|are|was|were)\s+not|(?:doesn't|don't|didn't|can't|couldn't|won't|wouldn't|shouldn't|isn't|aren't|wasn't|weren't)|fail(?:s|ed)?\s+to)(?:\s+[\w-]+){0,6}\s*$"
)
@dataclass(frozen=True)
class LintIssue: code:str; line:int
class NarrativeLint:
 def check(self,text:str,*,causal_identified:bool=False)->tuple[LintIssue,...]:
  issues=[]
  for n,line in enumerate(text.splitlines(),1):
   low=line.casefold()
   if any(x in low for x in ('/backend/','agent trace','workflow log','module path')):issues.append(LintIssue('internal_leak',n))
   if _ENGINEERING_PROSE.search(line) and 'methods' not in low:issues.append(LintIssue('engineering_prose',n))
   if not causal_identified:
    for match in _CAUSALITY.finditer(low):
     context=re.split(r'[;:.]|\b(?:but|however|yet|whereas)\b',low[:match.start()])[-1]
     if not _NEGATED_CAUSAL_PREFIX.search(context):
      issues.append(LintIssue('unsupported_causality',n));break
   exempt = not line.strip() or line.lstrip().startswith(('#','---','project_id:','evidence_version_sha256:','claim_evidence_graph_sha256:','generated_at_utc:','generator_policy:')) or re.match(r'^\d+\. ',line.strip())
   if _NOVELTY.search(line):issues.append(LintIssue('unsupported_novelty_upgrade',n))
   if not exempt and '[claim:' not in low:issues.append(LintIssue('missing_claim_id',n))
   if low.startswith('results:') and not any(x in low for x in ('mechanism','alternative','boundary','negative')):issues.append(LintIssue('metrics_only_results',n))
  return tuple(issues)
