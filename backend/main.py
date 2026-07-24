"""(docstring)"""
from __future__ import annotations
import asyncio
import logging
import sys
from contextlib import asynccontextmanager


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import IS_DESKTOP, FRONTEND_DIST, API_PORT
from services.state_store import init_db
from services.workflow_engine import set_broadcast
from routers import workflows, artifacts, checkpoints, ws, settings, editor, environment, agents, research, research_runs, literature, drafts, experiments, narrative, project_preview
from routers import docx_export as docx_export_router
from services.local_session import verify_request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from infrastructure.persistence.research_run_repository import SqliteResearchRunRepository
    from config import DB_PATH
    SqliteResearchRunRepository(DB_PATH).migrate()
    from services.project_server import project_server_manager
    try:
        await project_server_manager.recover_all()
        from services.agent_tasks import recover_interrupted
        await recover_interrupted()

        from services.workflow_operations import publish_workflow_event, resume_interrupted_operations

        # Engine events are appended to the operations ledger before live
        # delivery, so reconnecting dashboards cannot miss a transition.
        set_broadcast(publish_workflow_event)

        from services.state_store import get_workflows_to_resume
        from services.workflow_engine import run_workflow
        from routers.workflows import _tasks
        resumed_operations = await resume_interrupted_operations(_tasks)
        if resumed_operations:
            logging.getLogger(__name__).info(
                "Resumed %d interrupted workflow recovery operations",
                len(resumed_operations),
            )
        resume_ids = get_workflows_to_resume()
        for wf_id in resume_ids:
            if any(
                (key == wf_id or key.startswith(f"{wf_id}_")) and not task.done()
                for key, task in list(_tasks.items())
            ):
                continue
            logging.getLogger(__name__).info("Auto-resuming workflow %s after restart", wf_id)
            task = asyncio.create_task(run_workflow(wf_id))
            _tasks[wf_id] = task

        from routers.workflows import start_heartbeat
        start_heartbeat()

        yield
    finally:
        # Preview servers are owned children.  A normal desktop shutdown must
        # never leave Vite/uvicorn/node process trees behind.
        await project_server_manager.stop_all()


app = FastAPI(title="Vibe Research Local API", version="1.2.2", lifespan=lifespan)

@app.middleware("http")
async def local_session_guard(request: Request, call_next):
    # Source-mode development runs the SPA on Vite and has no Electron
    # preload bridge from which to obtain the per-launch session token.
    # Keep the loopback token/origin boundary for packaged desktop launches,
    # while allowing the local source server to exercise its API directly.
    if IS_DESKTOP and request.url.path.startswith("/api/"):
        try:
            verify_request(request)
        except Exception as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)

app.include_router(workflows.router)
app.include_router(artifacts.router)
app.include_router(checkpoints.router)
app.include_router(settings.router)
app.include_router(editor.router)
app.include_router(project_preview.router)
app.include_router(environment.router)
app.include_router(agents.router)
app.include_router(research.router)
app.include_router(research_runs.router)
app.include_router(literature.router)
app.include_router(drafts.router)
app.include_router(experiments.router)
app.include_router(narrative.router)
app.include_router(ws.router)
app.include_router(docx_export_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "desktop": IS_DESKTOP}


@app.get("/api/license/status")
async def license_status():
    """(docstring)"""
    return {"licensed": True}


@app.post("/api/license/verify")
async def license_verify():
    """(docstring)"""
    return {"valid": True, "message": "Unlocked without activation"}


@app.get("/api/templates")
async def get_templates():
    """(docstring)"""
    from services.workflow_engine import TEMPLATES
    result = {}
    for key, tmpl in TEMPLATES.items():
        result[key] = {
            "name": tmpl.display_name,
            "pipeline_skill": tmpl.pipeline_skill,
            "steps": [
                {"skill_name": s.skill_name, "display_name": s.display_name,
                 "has_checkpoint": s.has_checkpoint, "checkpoint_type": s.checkpoint_type}
                for s in tmpl.sub_steps
            ],
        }
    return result



if IS_DESKTOP and FRONTEND_DIST.is_dir():

    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="static-assets")


    @app.get("/logo.svg")
    async def serve_logo():
        logo = FRONTEND_DIST / "logo.svg"
        if logo.exists():
            return FileResponse(str(logo), media_type="image/svg+xml")


    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):

        # API typos must stay API errors. Returning index.html here makes a
        # failed API call look like a successful HTML response to the UI.
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "API endpoint not found"})

        static_file = FRONTEND_DIST / full_path
        if static_file.is_file() and not full_path.startswith("api") and not full_path.startswith("ws"):
            return FileResponse(str(static_file))

        return FileResponse(str(FRONTEND_DIST / "index.html"))
