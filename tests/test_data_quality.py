from domain.assurance.data_quality import DataQualityGate
def test_report_detects_missing_duplicates_split_overlap_leakage_and_is_reproducible():
 rows=[{'id':'a','x':1,'y':1},{'id':'a','x':1,'y':1}];r=DataQualityGate().evaluate(rows,rows,required={'id','x','y'},target='y')
 assert r.duplicate_rows==3 and r.split_overlap==('a',) and r.target_leakage==('x',) and r.to_json()==r.to_json()
def test_clean_split_has_no_contamination():
 r=DataQualityGate().evaluate([{'id':'a','x':1,'y':0}],[{'id':'b','x':2,'y':1}],required={'id','x','y'},target='y')
 assert r.schema_ok and not r.contamination and not r.target_leakage
