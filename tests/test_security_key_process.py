import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
def test_secret_key_is_random_and_not_derived_from_home(tmp_path):
 from services.secret_store import SecretStore
 a=SecretStore(tmp_path/'one'/'a.json');b=SecretStore(tmp_path/'two'/'b.json');assert a.key!=b.key and len(a.key)==32; a.set('x','value');assert a.get('x')=='value'
def test_supervisor_timeout_returns_failure(tmp_path):
 from services.process_supervisor import ProcessSupervisor
 async def go():return await ProcessSupervisor(tmp_path,{Path(sys.executable).name}).run('x',[sys.executable,'-c','import time;time.sleep(3)'],tmp_path,.01)
 assert asyncio.run(go())['returncode']==-1
