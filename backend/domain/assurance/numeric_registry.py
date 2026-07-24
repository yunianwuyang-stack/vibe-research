"""Numbers derived only from a validated experiment artifact."""
from __future__ import annotations
import math
from dataclasses import dataclass
@dataclass(frozen=True)
class NumericValue:
 kind:str; value:float; condition:str; artifact_hash:str; run_id:str; metric:str
class VerifiedNumericRegistry:
 def __init__(self,validated_artifacts:set[str])->None:self.validated=validated_artifacts;self.values:list[NumericValue]=[]
 def register(self,kind:str,value:float,condition:str,artifact_hash:str,run_id:str,metric:str)->NumericValue:
  if artifact_hash not in self.validated:raise ValueError('result artifact is not validated')
  if not condition.strip() or not metric.strip() or not math.isfinite(value):raise ValueError('finite value with real condition and metric required')
  x=NumericValue(kind,value,condition,artifact_hash,run_id,metric);self.values.append(x);return x
 def mean(self,raw:list[float],**p)->NumericValue:return self.register('aggregate.mean',sum(raw)/len(raw),**p)
 def difference(self,left:float,right:float,**p)->NumericValue:return self.register('derived.difference',left-right,**p)
