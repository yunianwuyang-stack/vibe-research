"""Passage-level evidence cards; abstracts cannot substitute for source text."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib

@dataclass(frozen=True)
class PassageLocator:
    page: int
    section: str
    paragraph: int | None = None
    table: str | None = None
    formula: str | None = None
    def __post_init__(self)->None:
        if self.page < 1 or not self.section.strip(): raise ValueError("passage requires page and section locator")
        if self.paragraph is None and self.table is None and self.formula is None: raise ValueError("passage requires paragraph, table, or formula locator")

@dataclass(frozen=True)
class ExtractedPassage:
    document_hash: str
    quote: str
    locator: PassageLocator
    def __post_init__(self)->None:
        if len(self.document_hash)!=64 or not self.quote.strip(): raise ValueError("passage needs source hash and nonempty quote")
    @property
    def content_hash(self)->str: return hashlib.sha256((self.document_hash+self.quote+repr(self.locator)).encode()).hexdigest()
    def is_stale(self, current_document_hash:str)->bool: return self.document_hash != current_document_hash

@dataclass(frozen=True)
class EvidenceCard:
    passage: ExtractedPassage
    study_type: str
    sample: str
    method: str
    limitation: str
    def __post_init__(self)->None:
        if not all(x.strip() for x in (self.study_type,self.sample,self.method,self.limitation)): raise ValueError("evidence card needs study type, sample, method, limitation")
