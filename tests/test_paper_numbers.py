from domain.assurance.numeric_registry import NumericValue
from domain.assurance.paper_numbers import PaperNumericVerifier
H='a'*64
R=[NumericValue('raw',0.953,'control',H,'run','accuracy')]
def test_experimental_number_matches_with_legal_rounding_and_locator():
 f=PaperNumericVerifier().verify('## Results\nAccuracy was 0.95.',R)[0];assert f.verified and f.locator=='line:2'
def test_fabricated_experimental_number_rejected_but_year_and_formula_classified():
 fs=PaperNumericVerifier().verify('## Results\nAccuracy was 0.71.\nPrior work (2024).\nx = 3.14',R)
 assert fs[0].category=='experimental' and not fs[0].verified
 assert fs[1].category=='citation_year' and fs[1].verified
 assert fs[2].category=='formula_constant' and fs[2].verified
