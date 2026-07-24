"""Layered citation existence verification with explicit unavailable outcomes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

class CitationVerdict(str,Enum): PASS='PASS'; FAIL='FAIL'; UNAVAILABLE='UNAVAILABLE'
@dataclass(frozen=True)
class CitationCheck: verdict:CitationVerdict; layer:str; detail:str
class CitationLookup(Protocol):
 def doi_exists(self,doi:str)->bool: ...
 def arxiv_exists(self,identifier:str)->bool: ...
 def metadata_matches(self,title:str,authors:tuple[str,...],year:int|None)->bool: ...
class CitationVerifier:
 def __init__(self,lookup:CitationLookup)->None:self.lookup=lookup
 def verify(self,*,doi:str|None=None,arxiv:str|None=None,title:str|None=None,authors:tuple[str,...]=(),year:int|None=None)->CitationCheck:
  if not any((doi,arxiv,title)):return CitationCheck(CitationVerdict.FAIL,'input','citation identifier or metadata required')
  try:
   if doi:return CitationCheck(CitationVerdict.PASS if self.lookup.doi_exists(doi) else CitationVerdict.FAIL,'doi',doi)
   if arxiv:return CitationCheck(CitationVerdict.PASS if self.lookup.arxiv_exists(arxiv) else CitationVerdict.FAIL,'arxiv',arxiv)
   return CitationCheck(CitationVerdict.PASS if self.lookup.metadata_matches(title or '',authors,year) else CitationVerdict.FAIL,'metadata',title or '')
  except OSError as error:return CitationCheck(CitationVerdict.UNAVAILABLE,'network',str(error))
