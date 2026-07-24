"""Deterministically classify and verify manuscript numbers against registry values."""
from __future__ import annotations
import re
from dataclasses import dataclass
from .numeric_registry import NumericValue

_PROVENANCE_IDENTIFIER = re.compile(
 r"\b(?:run(?:_id)?|artifact(?:_sha256)?|sha256)\s*(?::|=)?\s*(?:[0-9a-f]{64}|[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\b",
 re.IGNORECASE,
)
_INDEXED_FIELD = re.compile(r"\b([a-z_][a-z_0-9]*)\[\d+\]", re.IGNORECASE)
@dataclass(frozen=True)
class NumberFinding: value:float; category:str; locator:str; verified:bool
class PaperNumericVerifier:
 def verify(self,text:str,registry:list[NumericValue])->list[NumberFinding]:
  findings=[]; values=[x.value for x in registry]
  section=''
  for line_no,line in enumerate(text.splitlines(),1):
   if line.lstrip().startswith('#'):section=line.lstrip('#').strip().casefold();continue
   if any(line.startswith(prefix) for prefix in ('evidence_version_sha256:','project_id:','generated_at_utc:')):continue
   clean_line=re.sub(r'\[claim:[^\]]+\]','',line,flags=re.I)
   clean_line=re.sub(r'\bclaim\s+support\b','',clean_line,flags=re.I)
   # Run UUIDs and artifact hashes are provenance locators, not manuscript results.
   clean_line=_PROVENANCE_IDENTIFIER.sub('',clean_line)
   # `ci95[0]` is a field locator; the adjacent reported value remains auditable.
   clean_line=_INDEXED_FIELD.sub(r'\1',clean_line)
   in_results=section in {'results','结果','缁撴灉'} or clean_line.casefold().startswith('results:')
   category='citation_year' if re.search(r'\b(19|20)\d{2}\b',clean_line) else ('reference_index' if re.match(r'^\s*\d+\. ',clean_line) else ('formula_constant' if '=' in clean_line else ('experimental' if in_results else 'narrative_count')))
   tokens=re.findall(r'(?<![\w.])-?\d+(?:\.\d+)?',clean_line)
   if category=='reference_index' and tokens:tokens=tokens[1:]
   for token in tokens:
    value=float(token); ok=category!='experimental' or any(abs(value-x)<=0.005 for x in values)
    findings.append(NumberFinding(value,category,f'line:{line_no}',ok))
  return findings
