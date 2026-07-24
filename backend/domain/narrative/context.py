"""Strict record-to-narrative boundary for scientific writing."""
from __future__ import annotations
from dataclasses import dataclass,field
@dataclass(frozen=True)
class NarrativeContext:
 question:tuple[str,...]=(); hypothesis:tuple[str,...]=(); claim:tuple[str,...]=(); evidence:tuple[str,...]=(); boundary:tuple[str,...]=(); rhetorical_profile:tuple[str,...]=(); reproducibility_facts:tuple[str,...]=()
 @classmethod
 def from_record(cls,record:dict,*,methods_approved:bool=False)->'NarrativeContext':
  allowed={'question','hypothesis','claim','evidence','boundary','rhetorical_profile'}
  forbidden={'workflow','debug','module','log','path','agent','trace'}
  if forbidden & set(record):raise ValueError('engineering records cannot enter narrative context')
  kwargs={k:tuple(record.get(k,())) for k in allowed}
  kwargs['reproducibility_facts']=tuple(record.get('reproducibility_facts',())) if methods_approved else ()
  return cls(**kwargs)
