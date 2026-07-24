from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
def test_docx_source_rejects_escape_and_symlink(tmp_path):
 from routers.docx_export import _resolve_source
 w=tmp_path/'w';w.mkdir();outside=tmp_path/'outside.md';outside.write_text('x')
 assert _resolve_source(w,'../outside.md') is None
 link=w/'link.md'
 try:link.symlink_to(outside)
 except OSError:return
 assert _resolve_source(w,'link.md') is None
 (w/'paper').mkdir();(w/'paper'/'main.md').write_text('x');assert _resolve_source(w,None).name=='main.md'
