#!/usr/bin/env python3
"""Generate a transparent dependency inventory; non-redistributable assets stay excluded."""
from pathlib import Path
import json,datetime
root=Path(__file__).resolve().parents[1]
def packages(lock):
 data=json.loads((root/lock).read_text(encoding="utf8"));return [{"name":p.get("name",key.rsplit("node_modules/",1)[-1]),"version":p.get("version","unknown"),"path":key} for key,p in data.get("packages",{}).items() if key]
def requirements(path):
 return [{"name":line.split("==")[0].split(">=")[0],"version":line.split("==",1)[1] if "==" in line else "unlocked","path":path} for line in (root/path).read_text(encoding="utf8").splitlines() if line and not line.startswith("#")]
components=packages("package-lock.json")+packages("frontend/package-lock.json")+requirements("backend/requirements.txt")+requirements("requirements-dev.lock")
out={"bomFormat":"CycloneDX","specVersion":"1.5","metadata":{"timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat()},"components":[{"type":"library","name":x["name"],"version":x["version"],"properties":[{"name":"vibe:path","value":x["path"]}]} for x in components]}
(root/'SBOM.cdx.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(len(components))
