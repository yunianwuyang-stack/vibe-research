"""Content-addressed experiment manifests; historical failed runs are retained."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict
from pathlib import Path
from domain.experiments import ExperimentManifest
class ManifestIntegrityError(ValueError):pass
class ManifestStore:
 def __init__(self,root:str|Path)->None:self.root=Path(root)
 def write(self,manifest:ExperimentManifest)->Path:
  payload=json.dumps(asdict(manifest),sort_keys=True,separators=(',',':')); digest=hashlib.sha256(payload.encode()).hexdigest();p=self.root/f'{digest}.json';self.root.mkdir(parents=True,exist_ok=True);p.write_text(payload,encoding='utf-8');return p
 def load(self,path:str|Path)->ExperimentManifest:
  p=Path(path);raw=p.read_text(encoding='utf-8');
  if hashlib.sha256(raw.encode()).hexdigest()!=p.stem:raise ManifestIntegrityError('manifest tampering detected')
  d=json.loads(raw);d['argv']=tuple(d['argv']);d['raw_artifact_hashes']=tuple(d['raw_artifact_hashes']);return ExperimentManifest(**d)
