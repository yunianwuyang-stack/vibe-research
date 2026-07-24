from pathlib import Path
import pytest
from domain.evidence.cards import EvidenceCard, ExtractedPassage, PassageLocator
from infrastructure.literature.ingestion import DocumentIngestor

H='a'*64
def test_full_text_passage_retains_page_section_and_table_locator(tmp_path:Path)->None:
 p=tmp_path/'paper.txt';p.write_text('Observed result in Table 1.',encoding='utf-8'); x=DocumentIngestor().extract(p,page=3,section='Results',table='Table 1')
 card=EvidenceCard(x,'randomized trial','n=80','regression','single site')
 assert card.passage.locator.page==3 and card.passage.locator.table=='Table 1'
def test_modified_document_marks_passage_stale(tmp_path:Path)->None:
 p=tmp_path/'paper.txt';p.write_text('full text',encoding='utf-8');x=DocumentIngestor().extract(p,page=1,section='Intro',paragraph=1);p.write_text('changed text',encoding='utf-8')
 assert x.is_stale(__import__('hashlib').sha256(p.read_bytes()).hexdigest())
def test_abstract_or_unlocated_text_cannot_be_evidence()->None:
 with pytest.raises(ValueError): ExtractedPassage(H,'abstract only',PassageLocator(1,'Abstract'))
 with pytest.raises(ValueError): EvidenceCard(ExtractedPassage(H,'quote',PassageLocator(1,'Results',1)),'','','','')
