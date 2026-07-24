"""Academic rhetorical moves, not reusable prose templates."""
from __future__ import annotations
from dataclasses import dataclass
@dataclass(frozen=True)
class RhetoricalProfile: name:str; moves:dict[str,tuple[str,...]]
PROFILES={
 'ml_mechanism':RhetoricalProfile('ml_mechanism',{'Introduction':('theoretical tension','mechanistic hypothesis'),'Methods':('identification of mechanism','evaluation design'),'Results':('mechanism evidence','competing account'),'Discussion':('boundary conditions','external validity')}),
 'causal_empirical':RhetoricalProfile('causal_empirical',{'Introduction':('estimand relevance','identification challenge'),'Methods':('assumptions','estimand'),'Results':('effect estimate','robustness'),'Discussion':('assumption sensitivity','scope')}),
 'negative_result':RhetoricalProfile('negative_result',{'Introduction':('falsifiable expectation','theoretical value of null'),'Methods':('power and design','precommitment'),'Results':('null estimate','precision'),'Discussion':('competing explanations','limits of inference')})}
def profile(name:str)->RhetoricalProfile:return PROFILES[name]
