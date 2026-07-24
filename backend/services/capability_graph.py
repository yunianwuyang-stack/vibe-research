"""Runtime capability graph: inventory of reachable production surfaces."""
from __future__ import annotations
import ast
from pathlib import Path
from application.golden_path import capability_graph as golden_graph
ROOT=Path(__file__).resolve().parents[1]
def _functions(folder:str,kind:str)->list[dict]:
 out=[]
 for p in sorted((ROOT/folder).rglob("*.py")):
  if "__pycache__" in p.parts:continue
  try:tree=ast.parse(p.read_text(encoding="utf-8"))
  except (SyntaxError,UnicodeDecodeError):continue
  for n in ast.walk(tree):
   if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and not n.name.startswith("_"):out.append({"id":f"{kind}:{p.relative_to(ROOT).as_posix()}:{n.name}","kind":kind,"path":p.relative_to(ROOT).as_posix(),"name":n.name})
 return out
def build()->dict:
 nodes=_functions("routers","route")+_functions("application","application")+_functions("domain","domain")+_functions("services","service")+_functions("infrastructure","infrastructure")
 frontend=ROOT.parent/"frontend"/"src"
 if frontend.exists():nodes += [{"id":f"frontend:{p.relative_to(ROOT.parent).as_posix()}","kind":"frontend","path":p.relative_to(ROOT.parent).as_posix(),"name":p.stem} for p in sorted(frontend.rglob("*.tsx"))]
 return {"schema_version":"1.0","generated_from":"source AST","golden_path":golden_graph(),"nodes":nodes}
