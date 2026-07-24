"""Deterministic data quality and leakage report."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, asdict
import json
@dataclass(frozen=True)
class QualityReport:
 schema_ok:bool; missing:dict[str,int]; duplicate_rows:int; split_overlap:tuple[str,...]; target_leakage:tuple[str,...]; contamination:bool
 def to_json(self)->str:return json.dumps(asdict(self),sort_keys=True,separators=(',',':'))
class DataQualityGate:
 def evaluate(self,train:list[dict],test:list[dict],*,required:set[str],target:str,id_field:str='id')->QualityReport:
  rows=train+test; schema_ok=all(required <= set(row) for row in rows); missing={key:sum(row.get(key) in (None,'') for row in rows) for key in required}; duplicates=len(rows)-len({json.dumps(row,sort_keys=True) for row in rows}); train_ids={row.get(id_field) for row in train};test_ids={row.get(id_field) for row in test}; overlap=tuple(sorted(str(x) for x in train_ids&test_ids)); leakage=tuple(sorted(key for key in required-{target,id_field} if all(row.get(key)==row.get(target) for row in rows)));return QualityReport(schema_ok,missing,duplicates,overlap,leakage,bool(overlap))
