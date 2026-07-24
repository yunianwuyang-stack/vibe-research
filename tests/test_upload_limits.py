import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
class F:
 def __init__(self,b):self.b=b
 async def read(self,n):x,self.b=self.b[:n],self.b[n:];return x
def test_streaming_upload_limit_rejects_oversize():
 from services.upload_limits import read_limited
 async def go():
  try:await read_limited(F(b'x'*11),10)
  except Exception as e:return e.status_code
 assert asyncio.run(go())==413
