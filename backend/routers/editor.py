"""(docstring)"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

from models.editor_contracts import CAPABILITY_UNAVAILABLE, EDITOR_ENDPOINT_CONTRACTS
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from config import WORKSPACES_DIR
from services import editor_ai

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/editor/{wf_id}", tags=["editor"])



def _capability_unavailable(method: str, route: str) -> None:
    contract = EDITOR_ENDPOINT_CONTRACTS[f"{method} /api/editor/{{wf_id}}{route}"]
    raise HTTPException(
        status_code=501,
        detail={"code": CAPABILITY_UNAVAILABLE, "reason": contract["reason"]},
    )
class SaveRequest(BaseModel):
    path: str
    content: str


class CreateFileRequest(BaseModel):
    path: str


class DrawioExportRequest(BaseModel):
    source: str
    format: str = Field(default="pdf", pattern="^(png|pdf|svg)$")


class MermaidExportRequest(BaseModel):
    source: str
    format: str = Field(default="svg", pattern="^(png|pdf|svg)$")


class GenerateImageRequest(BaseModel):
    prompt: str
    model: str = "gpt-image-1"
    size: str = Field(default="1024x1024", pattern="^(1024x1024|1536x1024|1024x1536)$")


class CompileRequest(BaseModel):
    source_md: str = ""


class RunScriptRequest(BaseModel):
    script: str
    language: str = "python"


class AiEditRequest(BaseModel):
    message: str
    current_file: str
    current_content: str
    workspace_files: list = []
    compile_log: str = ""
    extra_context: str = ""
    history: list = None
    role: str = "latex"
    chat_summary: str = ""


class AiAgentRequest(BaseModel):
    message: str


class AiAgentStageRequest(BaseModel):
    path: str
    content: str


class AiAgentApplyRequest(BaseModel):
    files: list = []


@router.get("/mode")
async def get_mode(wf_id: str):
    try:
        return {"mode": editor_ai.get_mode(wf_id)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/files")
async def list_files(wf_id: str):
    try:
        return {"files": editor_ai.list_files(wf_id)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/file-preview-html")
async def file_preview_html(wf_id: str, path: str):
    try:
        return {"html": editor_ai.file_preview_html(wf_id, path)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/file")
async def read_file(wf_id: str, path: str):
    try:
        content = editor_ai.read_file(wf_id, path)
        return {"path": path, "content": content}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/file")
async def save_file(wf_id: str, req: SaveRequest):
    try:
        await editor_ai.save_file(wf_id, req.path, req.content)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload")
async def upload_file(wf_id: str, path: str, file: UploadFile = File(...)):
    from services.upload_limits import read_limited
    data = await read_limited(file)
    try:
        await editor_ai.upload_file(wf_id, path, data)
        return {"ok": True}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/create-file")
async def create_file(wf_id: str, req: CreateFileRequest):
    try:
        await editor_ai.create_file(wf_id, req.path)
        return {"ok": True}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/file")
async def delete_file(wf_id: str, path: str):
    try:
        await editor_ai.delete_file(wf_id, path)
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/download")
async def download_file(wf_id: str, path: str):
    try:
        filepath = editor_ai.download_file(wf_id, path)
        return FileResponse(str(filepath))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/drawio-export")
async def drawio_export(wf_id: str, req: DrawioExportRequest):
    try:
        return await editor_ai.drawio_export(wf_id, req.source, req.format)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.post("/mermaid-export")
async def mermaid_export(wf_id: str, req: MermaidExportRequest):
    try:
        return await editor_ai.mermaid_export(wf_id, req.source, req.format)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.get("/image-check")
async def image_check(wf_id: str, path: str = ""):
    try:
        return await editor_ai.audit_images(wf_id, path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.post("/generate-image")
async def generate_image(wf_id: str, req: GenerateImageRequest):
    try:
        return await editor_ai.generate_image(wf_id, req.prompt, req.model, req.size)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.post("/compile")
async def compile_paper(wf_id: str, body: CompileRequest = CompileRequest(source_md="")):
    try:
        return await editor_ai.compile_paper(wf_id, body.source_md)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.get("/pdf")
async def get_pdf(wf_id: str):
    try:
        filepath = editor_ai.get_pdf(wf_id)
        return FileResponse(str(filepath), media_type="application/pdf")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/docx-status")
async def docx_status(wf_id: str):
    try:
        return editor_ai.docx_status(wf_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/docx")
async def get_docx(wf_id: str):
    try:
        filepath = editor_ai.get_docx(wf_id)
        return FileResponse(str(filepath), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stats")
async def get_stats(wf_id: str, path: str = ""):
    try:
        return editor_ai.get_stats(wf_id, path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ai-edit")
async def ai_edit_endpoint(wf_id: str, req: AiEditRequest):
    try:
        return await editor_ai.ai_edit_endpoint(
            wf_id, req.message, req.current_file, req.current_content,
            req.workspace_files, req.compile_log, req.extra_context,
            req.history, req.role, req.chat_summary,
        )
    except RuntimeError as error:
        if str(error) == "agent_provider_unavailable":
            raise HTTPException(
                status_code=501,
                detail={"code": CAPABILITY_UNAVAILABLE, "reason": "agent_provider_unavailable"},
            ) from error
        raise HTTPException(status_code=502, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/ai-agent")
async def ai_agent_endpoint(wf_id: str, req: AiAgentRequest):
    contract = EDITOR_ENDPOINT_CONTRACTS["POST /api/editor/{wf_id}/ai-agent"]
    if contract["status"] == "unavailable":
        raise HTTPException(
            status_code=501,
            detail={"code": CAPABILITY_UNAVAILABLE, "reason": contract["reason"]},
        )
    try:
        return await editor_ai.ai_agent_endpoint(wf_id, req.message)
    except RuntimeError as error:
        if str(error) == "agent_provider_unavailable":
            raise HTTPException(status_code=501, detail={"code": CAPABILITY_UNAVAILABLE, "reason": "agent_provider_unavailable"}) from error
        raise HTTPException(status_code=502, detail=str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/ai-agent-stage")
async def ai_agent_stage(wf_id: str, req: AiAgentStageRequest):
    try:
        return await editor_ai.stage_agent_proposal(wf_id, req.path, req.content)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ai-agent-apply")
async def ai_agent_apply(wf_id: str, req: AiAgentApplyRequest):
    """(docstring)"""
    try:
        return await editor_ai.ai_agent_apply(wf_id, req.files)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/ai-agent-discard")
async def ai_agent_discard(wf_id: str):
    """(docstring)"""
    return await editor_ai.ai_agent_discard(wf_id)


@router.post("/ai-agent-undo")
async def ai_agent_undo(wf_id: str):
    """(docstring)"""
    return await editor_ai.ai_agent_undo(wf_id)


@router.post("/ai-agent-stop")
async def ai_agent_stop(wf_id: str):
    """(docstring)"""
    return await editor_ai.ai_agent_stop(wf_id)


@router.get("/ai-agent-check")
async def ai_agent_check(wf_id: str, log_offset: int = 0):
    """(docstring)"""
    return await editor_ai.ai_agent_check(wf_id, log_offset)


@router.post("/run-script")
async def run_script(wf_id: str, req: RunScriptRequest):
    # Generic script execution is unavailable outside the allowlisted supervisor path.
    try:
        return await editor_ai.run_script(wf_id, req.script, req.language)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/describe-image")
async def describe_image_endpoint(wf_id: str, path: str):
    try:
        return await editor_ai.describe_image(wf_id, path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail={"code": CAPABILITY_UNAVAILABLE, "reason": str(error)}) from error


@router.get("/chat-history")
async def get_chat_history(wf_id: str):
    try:
        return {"history": editor_ai.get_chat_history(wf_id)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/chat-history")
async def clear_chat_history(wf_id: str):
    try:
        editor_ai.clear_chat_history(wf_id)
        return {"ok": True}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
