from infrastructure.literature.citation_verifier import CitationVerifier,CitationVerdict
class Lookup:
 def __init__(self,doi=True,arxiv=True,metadata=True,error=False):self.doi,self.arxiv,self.metadata,self.error=doi,arxiv,metadata,error
 def doi_exists(self,x):
  if self.error:raise OSError('offline')
  return self.doi
 def arxiv_exists(self,x):return self.arxiv
 def metadata_matches(self,*x):return self.metadata
def test_doi_arxiv_and_metadata_layers_pass_or_fail():
 assert CitationVerifier(Lookup()).verify(doi='10.x').verdict is CitationVerdict.PASS
 assert CitationVerifier(Lookup(doi=False)).verify(doi='10.x').verdict is CitationVerdict.FAIL
 assert CitationVerifier(Lookup(arxiv=False)).verify(arxiv='2401.1').verdict is CitationVerdict.FAIL
 assert CitationVerifier(Lookup(metadata=False)).verify(title='Paper').verdict is CitationVerdict.FAIL
def test_network_unavailable_never_becomes_pass():
 assert CitationVerifier(Lookup(error=True)).verify(doi='10.x').verdict is CitationVerdict.UNAVAILABLE
def test_empty_claim_is_fail():assert CitationVerifier(Lookup()).verify().verdict is CitationVerdict.FAIL
