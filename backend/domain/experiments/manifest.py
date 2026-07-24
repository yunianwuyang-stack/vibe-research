"""Immutable provenance contract for one experiment run."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
@dataclass(frozen=True)
class ExperimentManifest:
 dataset_hash:str; dataset_license:str; split:str; code_commit:str; argv:tuple[str,...]; environment_lock:str; hardware:str; seed:int; config:Mapping[str,object]; metric_definition:str; started_at:str; ended_at:str; exit_code:int; raw_artifact_hashes:tuple[str,...]
 def __post_init__(self)->None:
  required=(self.dataset_hash,self.dataset_license,self.split,self.code_commit,self.environment_lock,self.hardware,self.metric_definition,self.started_at,self.ended_at)
  if not all(x.strip() for x in required) or not self.argv or not self.raw_artifact_hashes: raise ValueError('complete experiment provenance required')
  if len(self.dataset_hash)!=64 or any(len(x)!=64 for x in self.raw_artifact_hashes):raise ValueError('hashes must be SHA-256')
 @property
 def ready_for_analysis(self)->bool:return True


from .execution import ExecutionSpec, artifact_is_accepted
