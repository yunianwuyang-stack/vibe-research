"""(docstring)"""
from __future__ import annotations
import asyncio
import logging
import logging.handlers
import sys
from contextlib import asynccontextmanager


if sys.platform == "win32":
    # NOTE: under uvicorn >= 0.36 this policy is largely inert — uvicorn builds
    # the loop via its own loop_factory (Config.get_loop_factory), bypassing
    # asyncio.set_event_loop_policy entirely.  In particular `--reload` /
    # `--workers > 1` make uvicorn pick a SelectorEventLoop on win32, which
    # cannot spawn subprocesses (bare NotImplementedError).  The real defense
    # lives in workflow_engine._run_process's synchronous subprocess fallback;
    # prefer running without --reload when subprocess-heavy steps matter.
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import IS_DESKTOP, FRONTEND_DIST, API_PORT, DB_PATH
from services.state_store import init_db
from services.workflow_engine import set_broadcast
from routers import workflows, artifacts, checkpoints, ws, settings, editor, environment, agents, research, research_runs, literature, drafts, experiments, narrative, project_preview
from routers import docx_export as docx_export_router
from services.local_session import verify_request

_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"

# Durable file logging: the desktop/console window buffer is unreadable to
# automation and disappears on crash, so every backend run also writes a
# rotating log next to the database (<data_root>/logs/backend.log, source
# mode: runtime/backend/logs/backend.log).  Diagnosing silent workflow
# failures requires this file — see CODEBASE.md "后端日志".
_LOG_DIR = DB_PATH.parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = logging.handlers.RotatingFileHandler(
    _LOG_DIR / "backend.log",
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=[
    logging.StreamHandler(),
    _file_handler,
])
logging.getLogger(__name__).info("backend log file: %s", _LOG_DIR / "backend.log")


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

        # Reap zombie step attempts left behind by a previous backend process:
        # any attempt still in 'running' state when we start could not have a
        # live executor (we just booted), so mark it interrupted.  Without
        # this, fb4f4e5b7272-style zombie attempts confused both the UI and
        # the recovery path.
        try:
            from services.state_store import get_db
            db = await get_db()
            try:
                cursor = await db.execute(
                    "UPDATE workflow_step_attempts SET status='interrupted', "
                    "finished_at=datetime('now'), "
                    "error_message=COALESCE(NULLIF(error_message, ''), "
                    "'backend restarted while attempt was running; marked interrupted at startup') "
                    "WHERE status='running'"
                )
                reaped = cursor.rowcount or 0
                await db.commit()
                if reaped:
                    logging.getLogger(__name__).info(
                        "Reaped %d zombie 'running' step attempts at startup", reaped
                    )
            finally:
                await db.close()
        except Exception as reap_exc:
            logging.getLogger(__name__).warning(
                "zombie attempt reap failed (non-fatal): %s", reap_exc
            )

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
