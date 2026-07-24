"""Profile-specific statistical completeness gates for ML and causal studies."""
from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class GateResult: passed:bool; issues:tuple[str,...]
class StatisticsGate:
 def ml(self,*,seeds:int,ci:bool,effect_size:bool,baseline:bool,ablation:bool,leakage_checked:bool,metric_direction:str,stable_claim:bool)->GateResult:
  issues=[]
  if stable_claim and seeds<2:issues.append('single seed cannot support stable conclusion')
  if not ci:issues.append('missing confidence interval')
  if not effect_size:issues.append('missing effect size')
  if not all((baseline,ablation,leakage_checked)) or metric_direction not in {'higher','lower'}:issues.append('incomplete ML protocol')
  return GateResult(not issues,tuple(issues))
 def causal(self,*,estimand:str,treatment:str,outcome:str,confounders:tuple[str,...],identification:str,standard_errors:bool,robustness:bool,causal_claim:bool)->GateResult:
  issues=[]
  if causal_claim and not identification.strip():issues.append('causal claim lacks identification')
  if not all((estimand.strip(),treatment.strip(),outcome.strip(),confounders,standard_errors,robustness)):issues.append('incomplete causal protocol')
  return GateResult(not issues,tuple(issues))
