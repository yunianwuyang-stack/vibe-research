"""Local document ingestion port with a lightweight text/PDF plugin slot."""
from __future__ import annotations
import hashlib
from pathlib import Path
from domain.evidence.cards import ExtractedPassage, PassageLocator

class DocumentIngestor:
    def extract(self,path:str|Path, *, page:int, section:str, paragraph:int|None=None, table:str|None=None, formula:str|None=None)->ExtractedPassage:
        data=Path(path).read_bytes(); text=data.decode("utf-8",errors="replace")
        if not text.strip(): raise ValueError("document has no extractable local text")
        return ExtractedPassage(hashlib.sha256(data).hexdigest(),text,PassageLocator(page,section,paragraph,table,formula))
    @property
    def optional_docling_plugin(self)->None: return None
