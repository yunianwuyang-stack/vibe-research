"""Streaming upload limits for local API endpoints."""
from fastapi import HTTPException,UploadFile
MAX_UPLOAD_BYTES=10*1024*1024
async def read_limited(file:UploadFile,limit:int=MAX_UPLOAD_BYTES)->bytes:
 chunks=[];size=0
 while True:
  chunk=await file.read(min(65536,limit-size+1))
  if not chunk:break
  size+=len(chunk)
  if size>limit:raise HTTPException(status_code=413,detail=f"Upload exceeds {limit} bytes")
  chunks.append(chunk)
 return b''.join(chunks)
