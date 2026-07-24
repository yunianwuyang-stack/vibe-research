from infrastructure.literature.imports import parse_bibtex, parse_pubmed_xml, parse_ris


def test_bibtex_import_preserves_identity():
    result = parse_bibtex('@article{x, title={Evidence Study}, author={Doe, Jane and Roe, Alex}, year={2024}, doi={10.1000/ABC}, url={https://example.org/x}}')
    assert result == [{"title": "Evidence Study", "authors": ("Doe, Jane", "Roe, Alex"), "year": 2024, "doi": "10.1000/abc", "url": "https://example.org/x"}]


def test_ris_import_preserves_repeated_authors():
    result = parse_ris('TY  - JOUR\nTI  - Evidence Study\nAU  - Doe, Jane\nAU  - Roe, Alex\nPY  - 2024\nDO  - 10.1000/ABC\nUR  - https://example.org/x\nER  -')
    assert result[0]["authors"] == ("Doe, Jane", "Roe, Alex") and result[0]["doi"] == "10.1000/abc"


def test_pubmed_xml_import_preserves_pmid_locator():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Evidence Study</ArticleTitle><AuthorList><Author><ForeName>Jane</ForeName><LastName>Doe</LastName></Author></AuthorList><Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue></Journal></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/ABC</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
    result = parse_pubmed_xml(xml)
    assert result[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/123/" and result[0]["year"] == 2024
