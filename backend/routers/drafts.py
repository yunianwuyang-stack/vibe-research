from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import WORKSPACES_DIR
from services import approved_drafts

router=APIRouter(prefix="/api/research-projects/{project_id}/draft",tags=["approved-draft"])

class SaveDraft(BaseModel):content:str=Field(min_length=1)

@router.post("")
async def generate(project_id:str):return await approved_drafts.generate(project_id)

@router.get("")
async def read(project_id:str):return await approved_drafts.read(project_id)

@router.put("")
async def save(project_id:str,body:SaveDraft):return await approved_drafts.save(project_id,body.content)

@router.get("/latex")
async def latex(project_id:str):
 path=WORKSPACES_DIR/project_id/"paper"/"main.tex"
 if not path.is_file():await approved_drafts.generate(project_id)
 return FileResponse(str(path),filename="research-draft.tex",media_type="application/x-tex")
