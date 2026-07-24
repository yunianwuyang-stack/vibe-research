"""Independently verify two clean-state release benchmark outputs."""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

EXPECTED = {
    "literature-theory": ("openalex", "10.1126/science.aab2374", None),
    "public-data-empirical": ("crossref", "10.1038/sdata.2016.18", True),
    "method-computation": ("datacite", "10.5281/zenodo.4724124", True),
}

def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def verify(root: Path) -> dict:
    summary=json.loads((root/'gate-summary.json').read_text(encoding='utf-8'))
    assert summary['restart_recovered_projects']==3 and summary['install_removed'] and summary['uninstall_exit']==0
    assert set(item['case'] for item in summary['cases'])==set(EXPECTED)
    for item in summary['cases']:
        provider,doi,replay=EXPECTED[item['case']]
        assert (item['provider'],item['doi'],item['experiment_reproduced'])==(provider,doi,replay)
        assert item['citation_status']=='approved' and item['claim_support_status']=='approved'
        bundle=root/'bundles'/item['bundle']['path']; assert sha(bundle)==item['bundle']['sha256']
        with zipfile.ZipFile(bundle) as archive:
            names=set(archive.namelist()); assert {'contract.json','provider-recording.json','evidence.json','narrative.json','draft.json','draft.tex','draft.docx','audit.json','manifest.json'}<=names
            assert archive.read('draft.docx').startswith(b'PK') and archive.read('draft.tex').startswith(b'\\documentclass')
            audit=json.loads(archive.read('audit.json')); assert audit['passed'] and not audit['issues']
            evidence=json.loads(archive.read('evidence.json')); card=evidence['evidence_cards'][0]
            assert card['citation_status']=='approved' and card['claim_support_status']=='approved' and card['provenance']
            recording=json.loads(archive.read('provider-recording.json')); canonical=json.dumps(recording['records'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            assert hashlib.sha256(canonical).hexdigest()==recording['content_sha256']
            if replay is True:
                repeated=json.loads(archive.read('replay.json')); assert repeated['reproduced'] and repeated['statistics']['passed']
    return {'root':str(root),'installer_sha256':summary['installer']['sha256'],'cases':sorted(EXPECTED)}

def main():
    p=argparse.ArgumentParser();p.add_argument('roots',nargs=2,type=Path);a=p.parse_args()
    results=[verify(root.resolve()) for root in a.roots]
    assert results[0]['installer_sha256']==results[1]['installer_sha256']
    print(json.dumps({'verdict':'PASS','independent':True,'gates':results},ensure_ascii=False))

if __name__=='__main__': main()
