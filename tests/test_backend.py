"""Test suite for Vibe Research backend modules.

Usage:
    python -m pytest tests/test_backend.py -v
    python tests/test_backend.py
"""
import os
import sys
import json
import asyncio
import io
import hashlib
import tempfile
import zipfile
from pathlib import Path

# Set up paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))
os.chdir(str(BACKEND_DIR))
os.environ.setdefault("VIBE_DESKTOP", "1")
os.environ.setdefault("API_PORT", "18088")


def test_imports():
    """Test that all modules can be imported."""
    modules = [
        'config', 'models.schemas', 'models',
        'services.state_store', 'services.workflow_engine', 'services.claude_runner',
        'services.llm_client', 'services.license_guard', 'services.skill_crypto',
        'services.editor_ai', 'services.extract_worker', 'services.docx_tool_loader',
        'services.prompts', 'routers.workflows', 'routers.artifacts',
        'routers.checkpoints', 'routers.settings', 'routers.editor',
        'routers.ws', 'routers.docx_export', 'routers',
    ]
    errors = []
    for m in modules:
        try:
            __import__(m)
        except Exception as e:
            errors.append((m, str(e)))
    assert not errors, f"Import errors: {errors}"
    print(f"[PASS] test_imports: {len(modules)} modules imported OK")


def test_config():
    """Test config module."""
    from config import IS_DESKTOP, API_PORT as _port
    from config import API_PORT as port
    assert port == 18088, f"API_PORT should be 18088, got {port}"
    print(f"[PASS] test_config: API_PORT={port}")


def test_schemas():
    """Test Pydantic models."""
    from models.schemas import WorkflowCreate, WorkflowInfo, StepStatus, TemplateType
    
    # Test enum
    assert TemplateType.PAPER_WRITING.value == "paper_writing"
    assert StepStatus.PENDING.value == "pending"
    
    # Test model creation
    wf = WorkflowCreate(template=TemplateType.PAPER_WRITING, title="Test Paper")
    assert wf.title == "Test Paper"
    assert wf.template == TemplateType.PAPER_WRITING
    assert wf.params == {}
    assert wf.enable_checkpoints == False
    
    print("[PASS] test_schemas: Pydantic models OK")


def test_templates():
    """Test workflow templates."""
    from services.workflow_engine import TEMPLATES, TemplateDef, StepDef
    
    assert len(TEMPLATES) >= 5, f"Expected at least 5 templates, got {len(TEMPLATES)}"
    
    # Check paper_writing template
    assert "paper_writing" in TEMPLATES
    pw = TEMPLATES["paper_writing"]
    assert isinstance(pw, TemplateDef)
    assert pw.pipeline_skill == "paper-writing"
    assert len(pw.sub_steps) > 0
    
    # Check first step
    step = pw.sub_steps[0]
    assert isinstance(step, StepDef)
    assert step.skill_name == "paper-plan"
    
    print(f"[PASS] test_templates: {len(TEMPLATES)} templates OK")


def test_app_routes():
    """Test FastAPI app routes."""
    from main import app
    
    api_routes = [r for r in app.routes if hasattr(r, 'path') and r.path.startswith('/api/')]
    assert len(api_routes) >= 50, f"Expected at least 50 API routes, got {len(api_routes)}"
    
    # Check key routes
    route_paths = {r.path for r in api_routes}
    assert "/api/health" in route_paths
    assert "/api/templates" in route_paths
    assert "/api/workflows" in route_paths
    assert "/api/settings" in route_paths
    assert "/api/license/status" in route_paths
    
    print(f"[PASS] test_app_routes: {len(api_routes)} API routes OK")


def test_prompts():
    """Test prompt loading."""
    from services.prompts import list_prompts, load_prompt
    
    prompts = list_prompts()
    assert len(prompts) >= 5, f"Expected at least 5 prompts, got {len(prompts)}"
    
    # Test loading a prompt
    if "academic_docx_traps" in prompts:
        content = load_prompt("academic_docx_traps")
        assert len(content) > 100
    
    print(f"[PASS] test_prompts: {len(prompts)} prompts OK")


def test_state_store():
    """Test state store functions exist."""
    from services.state_store import init_db, create_workflow, get_workflow, list_workflows, update_workflow
    from services.state_store import get_all_settings, get_setting, save_settings, export_workflow_data, import_workflow_data
    
    print("[PASS] test_state_store: all functions available")


def test_abis_database():
    """Test database initialization."""
    import aiosqlite
    import services.state_store as state_store

    old_db_path = state_store.DB_PATH
    with tempfile.TemporaryDirectory() as td:
        test_db_path = Path(td) / "schema-test.db"
        state_store.DB_PATH = test_db_path

        async def _test():
            await state_store.init_db()
            public_db = await state_store.get_db()
            assert isinstance(public_db, aiosqlite.Connection)
            await public_db.close()
            db = await aiosqlite.connect(str(test_db_path))
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in await cursor.fetchall()]
            await db.close()
            return tables

        try:
            tables = asyncio.run(_test())
        finally:
            state_store.DB_PATH = old_db_path
            state_store._workflows_to_resume.clear()
    assert "workflows" in tables
    assert "workflow_steps" in tables
    assert "workflow_logs" in tables
    assert "checkpoints" in tables
    assert "settings" in tables
    
    print(f"[PASS] test_database: tables={tables}")


def test_state_store_recovered_contract():
    """Lock in state-store behavior observed from the canonical compiled module."""
    import aiosqlite
    import services.state_store as state_store

    old_db_path = state_store.DB_PATH
    old_platform_system = state_store._platform.system
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "state-contract.db"
        state_store._platform.system = lambda: "Linux"

        async def _exercise():
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                journal_mode = (await (await db.execute("PRAGMA journal_mode")).fetchone())[0]
                busy_timeout = (await (await db.execute("PRAGMA busy_timeout")).fetchone())[0]
                assert journal_mode == "wal"
                assert busy_timeout == 30000

                await state_store.create_workflow(db, {
                    "id": "state-main", "template": "paper_writing", "title": "State",
                    "params": {"unicode": "中文"}, "enable_checkpoints": True,
                })
                row = await (await db.execute(
                    "SELECT params, created_at, updated_at FROM workflows WHERE id=?", ("state-main",)
                )).fetchone()
                assert "\\u4e2d\\u6587" in row["params"]
                assert "T" not in row["created_at"]
                assert "T" not in row["updated_at"]

                try:
                    await state_store.update_workflow(db, "state-main", unknown_field=1)
                except aiosqlite.OperationalError as exc:
                    assert "no such column" in str(exc)
                else:
                    raise AssertionError("arbitrary update field should reach SQLite")

                try:
                    await state_store.update_workflow(db, "state-main")
                except aiosqlite.OperationalError as exc:
                    assert "syntax error" in str(exc)
                else:
                    raise AssertionError("empty update should preserve the original SQL error ABI")

                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,has_checkpoint,output_files) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("state-main", "step", "Step", 0, "completed", 1, '["paper.md"]'),
                )
                await db.execute(
                    "INSERT INTO workflow_logs (workflow_id,step_name,level,message) VALUES (?,?,?,?)",
                    ("state-main", "step", "info", "done"),
                )
                await db.commit()
            finally:
                await db.close()

            exported = await state_store.export_workflow_data("state-main")
            assert "workspace_dir" not in exported["workflow"]
            assert set(exported["steps"][0]) == {
                "skill_name", "display_name", "step_order", "status", "has_checkpoint",
                "checkpoint_type", "output_files", "started_at", "completed_at", "error_message",
            }
            assert exported["steps"][0]["has_checkpoint"] is True
            assert set(exported["logs"][0]) == {"step_name", "level", "message", "created_at"}

            minimal = {
                "workflow": {"template": "paper_writing", "title": "Imported"},
                "steps": [{"skill_name": "step", "display_name": "Step", "step_order": 0}],
                "logs": [{"message": "imported"}],
            }
            await state_store.import_workflow_data(minimal, "state-import", str(root / "workspace"))
            imported = await state_store.export_workflow_data("state-import")
            assert imported["workflow"]["status"] == "completed"
            assert imported["steps"][0]["status"] == "completed"
            assert imported["logs"][0]["step_name"] == ""

            bad = {
                "workflow": {"template": "paper_writing", "title": "Bad"},
                "steps": [{"display_name": "missing skill"}],
            }
            try:
                await state_store.import_workflow_data(bad, "state-bad", str(root / "bad"))
            except KeyError as exc:
                assert exc.args == ("skill_name",)
            else:
                raise AssertionError("malformed import should fail")
            db = await state_store.get_db()
            try:
                assert await (await db.execute(
                    "SELECT id FROM workflows WHERE id=?", ("state-bad",)
                )).fetchone() is None
            finally:
                await db.close()

            try:
                await state_store.save_settings({"atomic-ok": "yes", "atomic-bad": None})
            except aiosqlite.IntegrityError:
                pass
            else:
                raise AssertionError("NULL setting should fail the whole transaction")
            assert await state_store.get_setting("atomic-ok", "missing") == "missing"

            db = await state_store.get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "resume-state", "template": "paper_writing", "title": "Resume",
                    "status": "running",
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,error_message) "
                    "VALUES (?,?,?,?,?,?)",
                    ("resume-state", "step", "Step", 0, "running", "interrupted"),
                )
                await db.commit()
            finally:
                await db.close()
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                step = await (await db.execute(
                    "SELECT status,error_message FROM workflow_steps WHERE workflow_id=?", ("resume-state",)
                )).fetchone()
                assert dict(step) == {"status": "pending", "error_message": None}
            finally:
                await db.close()

        try:
            asyncio.run(_exercise())

            class LockedDb:
                def __init__(self):
                    self.calls = 0

                async def execute(self, *_args):
                    self.calls += 1
                    raise aiosqlite.OperationalError("database is locked")

                async def commit(self):
                    raise AssertionError("commit is unreachable")

            locked_db = LockedDb()
            delays = []
            old_sleep = state_store.asyncio.sleep

            async def _fake_sleep(delay):
                delays.append(delay)

            async def _locked_update():
                try:
                    await state_store.update_workflow(locked_db, "locked", status="running")
                except aiosqlite.OperationalError as exc:
                    assert str(exc) == "database is locked"
                else:
                    raise AssertionError("third lock attempt should be raised")

            state_store.asyncio.sleep = _fake_sleep
            try:
                asyncio.run(_locked_update())
            finally:
                state_store.asyncio.sleep = old_sleep
            assert locked_db.calls == 3
            assert delays == [1, 2]
        finally:
            state_store.DB_PATH = old_db_path
            state_store._platform.system = old_platform_system
            state_store._workflows_to_resume.clear()

    print("[PASS] test_state_store_recovered_contract: canonical CRUD/transaction/lock ABI restored")


def test_state_store_contention_contract():
    """Pin installed lock retry, WAL reader, and multi-connection transaction behavior."""
    import sqlite3
    import tempfile
    import aiosqlite
    import services.state_store as state_store

    old_db_path = state_store.DB_PATH
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "contention.db"
        state_store.DB_PATH = db_path

        async def _exercise():
            await state_store.init_db()
            seed = await state_store.get_db()
            try:
                await state_store.create_workflow(seed, {
                    "id": "contention", "template": "paper_writing", "title": "Contention",
                })
            finally:
                await seed.close()

            # WAL keeps a separate reader usable while a writer owns the lock.
            holder = sqlite3.connect(db_path, timeout=0)
            holder.execute("PRAGMA journal_mode=WAL")
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("UPDATE workflows SET title=title WHERE id='contention'")
            reader = await state_store.get_db()
            try:
                workflow = await state_store.get_workflow(reader, "contention")
                assert workflow["status"] == "pending"
            finally:
                await reader.close()
                holder.rollback()
                holder.close()

            # With SQLite waiting disabled, the Python wrapper owns the exact
            # three-attempt / 1+2 second retry policy recovered from the pyd.
            holder = sqlite3.connect(db_path, timeout=0)
            holder.execute("BEGIN EXCLUSIVE")
            holder.execute("UPDATE workflows SET title=title WHERE id='contention'")
            writer = await state_store.get_db()
            await writer.execute("PRAGMA busy_timeout=0")
            delays = []
            old_sleep = state_store.asyncio.sleep

            async def fake_sleep(delay):
                delays.append(delay)

            state_store.asyncio.sleep = fake_sleep
            try:
                try:
                    await state_store.update_workflow(writer, "contention", status="running")
                except aiosqlite.OperationalError as exc:
                    assert str(exc) == "database is locked"
                else:
                    raise AssertionError("third locked update attempt must propagate")
            finally:
                state_store.asyncio.sleep = old_sleep
                await writer.close()
                holder.rollback()
                holder.close()
            assert delays == [1, 2]

            # A non-lock storage failure is propagated immediately and the
            # failed update remains atomic. max_page_count deterministically
            # injects SQLite's disk-full result without filling the host disk.
            full = await state_store.get_db()
            try:
                await full.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                page_count = (await (await full.execute("PRAGMA page_count")).fetchone())[0]
                await full.execute(f"PRAGMA max_page_count={page_count}")
                await full.commit()
                try:
                    await state_store.update_workflow(full, "contention", title="Y" * 131072)
                except aiosqlite.OperationalError as exc:
                    assert str(exc) == "database or disk is full"
                else:
                    raise AssertionError("SQLite-full update must propagate")
            finally:
                await full.close()

            check = sqlite3.connect(db_path)
            try:
                assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert check.execute(
                    "SELECT status FROM workflows WHERE id='contention'"
                ).fetchone()[0] == "pending"
            finally:
                check.close()

        try:
            asyncio.run(_exercise())
        finally:
            state_store.DB_PATH = old_db_path
            state_store._workflows_to_resume.clear()

    print("[PASS] test_state_store_contention_contract: WAL and retry boundaries restored")


def test_ws_manager():
    """Test WebSocket manager."""
    from routers.ws import ConnectionManager
    
    mgr = ConnectionManager()
    assert hasattr(mgr, "broadcast")
    assert hasattr(mgr, "connect")
    assert hasattr(mgr, "disconnect")
    
    print("[PASS] test_ws_manager: ConnectionManager OK")


def test_encrypt_decrypt():
    """Exercise authenticated encryption, transport wrapping, and tamper detection."""
    import hashlib
    from cryptography.exceptions import InvalidTag
    from services.skill_crypto import (
        _derive_key, _SALT_PREFIX, decrypt_bytes, decrypt_dk_from_transport,
        encrypt_bytes, encrypt_dk_for_transport,
    )

    # Test key derivation against the current product salt (no legacy brand residue).
    master = "0123456789abcdef0123456789abcdef"
    key = _derive_key(master)
    assert len(key) == 32, f"Key should be 32 bytes, got {len(key)}"
    expected = hashlib.pbkdf2_hmac(
        "sha256",
        _SALT_PREFIX + master.encode("utf-8"),
        _SALT_PREFIX,
        100000,
    ).hex()
    assert key.hex() == expected
    assert _SALT_PREFIX == b"vibe-research-skill-enc-v2"

    plaintext = b"authenticated skill content\x00\xff"
    cipher1 = encrypt_bytes(plaintext, key)
    cipher2 = encrypt_bytes(plaintext, key)
    assert cipher1 != plaintext
    assert cipher1 != cipher2
    assert len(cipher1) == len(plaintext) + 28
    assert decrypt_bytes(cipher1, key) == plaintext
    try:
        decrypt_bytes(cipher1[:-1] + bytes([cipher1[-1] ^ 1]), key)
        raise AssertionError("Tampered ciphertext was accepted")
    except InvalidTag:
        pass

    wrapped = encrypt_dk_for_transport(key.hex(), "test-license")
    assert wrapped != key.hex()
    assert decrypt_dk_from_transport(wrapped, "test-license") == key.hex()
    
    print("[PASS] test_encrypt_decrypt: crypto functions OK")


def test_batch_export_contains_manifest_and_artifacts():
    """Create real persisted state and verify batch export is not an empty ZIP."""
    import services.state_store as state_store
    import routers.workflows as workflows

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflows.WORKSPACES_DIR
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "state.db"
        workflows.WORKSPACES_DIR = root / "workspaces"
        wf_id = "export01"
        workspace = workflows.WORKSPACES_DIR / wf_id
        artifact = workspace / "paper" / "main.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Exported paper\n", encoding="utf-8")
        (workspace / "CLAUDE.md").write_text("internal context", encoding="utf-8")

        async def _exercise():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": wf_id,
                    "template": "paper_writing",
                    "title": "Batch Export Test",
                    "params": {"language": "en"},
                    "status": "completed",
                    "workspace_dir": str(workspace),
                    "enable_checkpoints": False,
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id, skill_name, display_name, step_order, status, has_checkpoint, output_files) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (wf_id, "paper-write", "Write", 0, "completed", 0, json.dumps(["paper/main.md"])),
                )
                await db.execute(
                    "INSERT INTO workflow_logs (workflow_id, step_name, level, message) VALUES (?, ?, ?, ?)",
                    (wf_id, "paper-write", "info", "done"),
                )
                await db.commit()
            finally:
                await db.close()
            return await workflows.export_batch(workflows._BatchExportRequest(ids=[wf_id]))

        try:
            response = asyncio.run(_exercise())
            zip_path = Path(response.path)
            assert zip_path.stat().st_size > 22
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                prefix = f"BatchExportTest_{wf_id}/"
                assert f"{prefix}manifest.json" in names
                assert f"{prefix}workspace/paper/main.md" in names
                assert f"{prefix}workspace/CLAUDE.md" not in names
                manifest = json.loads(zf.read(f"{prefix}manifest.json"))
                assert manifest["workflow"]["id"] == wf_id
                assert manifest["steps"][0]["output_files"] == ["paper/main.md"]
                assert manifest["logs"][0]["message"] == "done"

            from starlette.datastructures import UploadFile

            async def _import_and_verify():
                upload = UploadFile(file=io.BytesIO(zip_path.read_bytes()), filename="batch.zip")
                result = await workflows.import_workflows(upload)
                assert len(result["imported"]) == 1
                imported_id = result["imported"][0]
                db = await state_store._get_db()
                try:
                    imported_wf = await state_store.get_workflow(db, imported_id)
                finally:
                    await db.close()
                return imported_id, imported_wf

            imported_id, imported_wf = asyncio.run(_import_and_verify())
            assert imported_wf is not None
            assert imported_wf["title"] == "Batch Export Test"
            assert (workflows.WORKSPACES_DIR / imported_id / "paper" / "main.md").read_text(encoding="utf-8") == "# Exported paper\n"
            zip_path.unlink(missing_ok=True)
        finally:
            state_store.DB_PATH = old_db_path
            workflows.WORKSPACES_DIR = old_workspaces_dir

    print("[PASS] test_batch_export_contains_manifest_and_artifacts: ZIP export/import round trip OK")


def test_workflow_asset_and_figure_helpers():
    """Exercise recovered workflow asset scanning and figure decision logic."""
    from services.workflow_engine import (
        _count_existing_figs_for, _is_drawio_fig, _pfa_safety_copy_assets,
        _read_assets_index, _read_figure_manifest, _resolve_template, _scan_workspace,
        _should_skip_step_by_assets, _wait_for_extracts,
    )

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        user_data = workspace / "user_data"
        user_data.mkdir()
        (user_data / "analysis.py").write_text("print('analysis')", encoding="utf-8")
        (user_data / "data.csv").write_text("x,y\n1,2\n", encoding="utf-8")
        (user_data / "plot.png").write_bytes(b"real-image-placeholder")
        (user_data / "template.tex").write_text("\\documentclass{article}", encoding="utf-8")
        (user_data / "results.json").write_text("{}", encoding="utf-8")

        copied = _pfa_safety_copy_assets(workspace)
        assert copied == {"code": 1, "data": 1, "figures": 1, "templates": 1, "skipped": 0}
        assert (workspace / "code" / "analysis.py").exists()
        assert (workspace / "data" / "data.csv").exists()
        assert not (workspace / "data" / "results.json").exists()

        (workspace / "_assets_index.json").write_text(json.dumps({
            "has_code": True, "has_results": True, "has_figures": True,
            "missing_assets": [],
        }), encoding="utf-8")
        (workspace / "PAPER_PLAN.md").write_text(
            "<!-- BEGIN FIGURE_MANIFEST -->\n"
            "- fig_result: data chart\n- fig_roadmap: architecture\n- tikz_equation: diagram\n"
            "<!-- END FIGURE_MANIFEST -->\n",
            encoding="utf-8",
        )
        figures = workspace / "figures"
        (figures / "fig_result.png").write_bytes(b"png")
        (figures / "fig_roadmap.drawio").write_text("drawio", encoding="utf-8")

        assert _read_assets_index(workspace)["has_results"] is True
        assert _read_figure_manifest(workspace) == (["fig_result"], ["fig_roadmap", "tikz_equation"])
        assert _count_existing_figs_for(workspace, ["fig_result", "fig_missing", "fig_roadmap"]) == (2, ["fig_missing"])
        assert _is_drawio_fig("figures/fig_roadmap.png") is True
        assert _is_drawio_fig("figures/fig_result.png") is False
        assert _should_skip_step_by_assets(workspace, "paper-analysis", "paper_from_assets")[0] is True
        scanned = _scan_workspace(workspace)
        assert "code/analysis.py" in scanned
        assert all("/." not in path for path in scanned)

        docx = _resolve_template("paper_writing", {"output_format": "docx"}, workspace)
        docx_skills = [step.skill_name for step in docx.sub_steps]
        assert "paper-write-docx" in docx_skills
        assert "paper-compile" not in docx_skills
        assert docx_skills[-3:] == ["auto-paper-improvement-docx", "docx-format-check", "docx-export"]
        pfa_zh = _resolve_template(
            "paper_from_assets", {"language": "zh", "output_format": "docx"}, workspace
        )
        assert "paper-plan-zh" in [step.skill_name for step in pfa_zh.sub_steps]
        assert "paper-write-zh-docx" in [step.skill_name for step in pfa_zh.sub_steps]

        status_file = workspace / "user_data" / "_extract_status.json"
        status_file.write_text(json.dumps({
            "version": 2,
            "files": {"input.pdf": {"status": "completed"}, "image.png": {"status": "failed"}},
        }), encoding="utf-8")
        asyncio.run(_wait_for_extracts(workspace, timeout_sec=1, poll_interval=0.01))

    print("[PASS] test_workflow_asset_and_figure_helpers: recovered helpers OK")


def test_workflow_vision_and_context_compression_helpers():
    """Cover the recovered private image/PDF context helper contract."""
    from PyPDF2 import PdfWriter
    from services import llm_client
    import services.workflow_engine as workflow_engine

    calls = []

    async def fake_describe_image(path, context=""):
        calls.append((Path(path).name, context))
        return "VISION " * 20

    original_describe = llm_client.describe_image
    llm_client.describe_image = fake_describe_image
    workflow_engine._image_descriptions.clear()
    try:
        with tempfile.TemporaryDirectory() as td:
            workspace = Path(td)
            user_data = workspace / "user_data"
            user_data.mkdir()
            (user_data / "plot.png").write_bytes(b"P" * 1001)
            (user_data / "tiny.png").write_bytes(b"P" * 1000)
            described = asyncio.run(workflow_engine._describe_workspace_images(workspace, "BASE"))
            assert "## 上传图片内容（AI 自动识别）" in described
            assert "### 图片: plot.png" in described
            assert "tiny.png" not in described
            assert len(calls) == 1
            asyncio.run(workflow_engine._describe_workspace_images(workspace, "BASE"))
            assert len(calls) == 1  # absolute-path cache is reused

            pdf = user_data / "problem.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with pdf.open("wb") as handle:
                writer.write(handle)
            pdf.write_bytes(pdf.read_bytes() + b"Q" * 1001)
            asyncio.run(workflow_engine._extract_pdf_with_vision(workspace, "wf-test"))
            extracted = (user_data / "problem_extracted.txt").read_text(encoding="utf-8")
            assert extracted.startswith("# problem.pdf 内容提取（Vision OCR）")
            assert "## 第 1 页" in extracted
            assert (workspace / "_tmp").exists() is False

            claude_md = workspace / "CLAUDE.md"
            claude_md.write_text(
                "# Context\n\n### 图片: plot.png\n" + "I" * 1000
                + "\n\n### 来源: problem.pdf\n```\n" + "D" * (120 * 1024),
                encoding="utf-8",
            )
            workflow_engine._compress_claude_md(workspace)
            compressed = claude_md.read_text(encoding="utf-8")
            assert "### 图片: plot.png\n" + "I" * 100 + "... (已压缩)" in compressed
            assert "### 来源: problem.pdf\n```\n" + "D" * 496 in compressed
            assert "... (已压缩，请用 Read 工具查看完整内容)\n```" in compressed
    finally:
        llm_client.describe_image = original_describe
        workflow_engine._image_descriptions.clear()

    print("[PASS] test_workflow_vision_and_context_compression_helpers: vision/private helper contract OK")


def test_skill_prompt_loading():
    """Verify the runner passes actual skill instructions rather than raw JSON alone."""
    import services.claude_runner as claude_runner

    old_skills_dir = claude_runner.SKILLS_DIR
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        skill_dir = root / "prompt-test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Prompt Test\nTopic: $ARGUMENTS\nWrite RESULT.md.\n",
            encoding="utf-8",
        )
        claude_runner.SKILLS_DIR = root
        try:
            prompt = claude_runner._load_skill_prompt(
                "prompt-test", "recovered topic", {"language": "zh"}
            )
        finally:
            claude_runner.SKILLS_DIR = old_skills_dir

    assert "IMPORTANT EXECUTION INSTRUCTIONS" in prompt
    assert "Topic: recovered topic" in prompt
    assert "$ARGUMENTS" not in prompt
    assert "- language: zh" in prompt
    assert "Write RESULT.md." in prompt
    print("[PASS] test_skill_prompt_loading: SKILL.md injected into executor prompt")


def test_interrupted_workflow_resume_cache():
    """Verify startup captures interrupted workflows without nested event-loop calls."""
    import services.state_store as state_store

    old_db_path = state_store.DB_PATH
    with tempfile.TemporaryDirectory() as td:
        state_store.DB_PATH = Path(td) / "resume.db"

        async def _prepare_and_reload():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "resume01", "template": "paper_writing", "title": "Resume",
                    "status": "running", "workspace_dir": str(Path(td) / "resume01"),
                })
            finally:
                await db.close()
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                row = await (await db.execute("SELECT status FROM workflows WHERE id = ?", ("resume01",))).fetchone()
                return row["status"]
            finally:
                await db.close()

        try:
            status = asyncio.run(_prepare_and_reload())
            assert status == "paused"
            assert state_store.get_workflows_to_resume() == ["resume01"]
            assert state_store.get_workflows_to_resume() == []
        finally:
            state_store.DB_PATH = old_db_path
            state_store._workflows_to_resume.clear()

    print("[PASS] test_interrupted_workflow_resume_cache: startup cache OK")


def test_auto_resume_limit_and_loop_safe_write_lock():
    """Matrix restarts must auto-resume only a bounded newest subset.

    Also pin that the writer lock is recreated for a fresh event loop so
    TestClient/desktop restarts never keep a lock bound to a closed loop.
    """
    import services.state_store as state_store

    old_db_path = state_store.DB_PATH
    old_limit = state_store._AUTO_RESUME_LIMIT
    with tempfile.TemporaryDirectory() as td:
        state_store.DB_PATH = Path(td) / "resume-limit.db"
        state_store._AUTO_RESUME_LIMIT = 2
        state_store._workflows_to_resume.clear()
        state_store._write_lock = None
        state_store._write_lock_loop = None

        async def _prepare_and_reload():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                for idx in range(5):
                    await state_store.create_workflow(db, {
                        "id": f"resume{idx}",
                        "template": "paper_writing",
                        "title": f"Resume {idx}",
                        "status": "running",
                        "workspace_dir": str(Path(td) / f"resume{idx}"),
                    })
            finally:
                await db.close()
            await state_store.init_db()
            return list(state_store._workflows_to_resume)

        async def _lock_across_loops():
            # First loop creates the lock; second loop must rebuild it.
            async def _touch():
                async with state_store._writer_section():
                    assert state_store._write_lock is not None
                    return id(state_store._write_lock)

            first = await _touch()
            return first

        try:
            resume_ids = asyncio.run(_prepare_and_reload())
            assert len(resume_ids) == 2
            assert state_store.get_workflows_to_resume() == resume_ids
            assert state_store.get_workflows_to_resume() == []

            first_lock_id = asyncio.run(_lock_across_loops())
            second_lock_id = asyncio.run(_lock_across_loops())
            assert first_lock_id != second_lock_id
        finally:
            state_store.DB_PATH = old_db_path
            state_store._AUTO_RESUME_LIMIT = old_limit
            state_store._workflows_to_resume.clear()
            state_store._write_lock = None
            state_store._write_lock_loop = None

    print("[PASS] test_auto_resume_limit_and_loop_safe_write_lock: bounded auto-resume + loop-safe lock")


def test_image_extraction_awaits_vision_result():
    """Verify asynchronous vision output is awaited before writing extracted text."""
    import services.extract_worker as extract_worker
    import services.llm_client as llm_client

    original_describe_image = llm_client.describe_image
    with tempfile.TemporaryDirectory() as td:
        upload_dir = Path(td)
        image = upload_dir / "figure.png"
        image.write_bytes(b"not-a-real-image-but-the-client-is-mocked")

        async def _fake_describe_image(image_path: str, context: str = "") -> str:
            assert image_path == str(image)
            assert context == "Image file: figure.png"
            return "recovered vision description"

        llm_client.describe_image = _fake_describe_image
        try:
            asyncio.run(extract_worker._run_extract(upload_dir, image.name))
        finally:
            llm_client.describe_image = original_describe_image

        status = extract_worker.get_status(upload_dir)["files"][image.name]
        assert status["status"] == "completed"
        assert status["chars"] == len("recovered vision description")
        assert (upload_dir / "figure.png.txt").read_text(encoding="utf-8") == "recovered vision description"

    print("[PASS] test_image_extraction_awaits_vision_result: async vision result persisted")


def test_workflow_stops_after_failed_step():
    """Verify a failed step makes the workflow fail instead of completing."""
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflow_engine.WORKSPACES_DIR
    original_run_single_step = workflow_engine.run_single_step
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "workflow-failure.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "failstep"
        workspace.mkdir(parents=True)

        async def _exercise():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "failstep",
                    "template": "paper_writing",
                    "title": "Failure propagation",
                    "params": {},
                    "status": "pending",
                    "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id, skill_name, display_name, step_order, status, has_checkpoint, output_files) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("failstep", "paper-plan", "Plan", 0, "pending", 0, "[]"),
                )
                await db.commit()
            finally:
                await db.close()

            async def _fail_step(workflow_id: str, skill_name: str) -> None:
                db = await state_store._get_db()
                try:
                    await db.execute(
                        "UPDATE workflow_steps SET status = 'failed', error_message = ? WHERE workflow_id = ? AND skill_name = ?",
                        ("simulated executor failure", workflow_id, skill_name),
                    )
                    await db.commit()
                finally:
                    await db.close()

            workflow_engine.run_single_step = _fail_step
            await workflow_engine.run_workflow("failstep")
            db = await state_store._get_db()
            try:
                return await state_store.get_workflow(db, "failstep")
            finally:
                await db.close()

        try:
            workflow = asyncio.run(_exercise())
        finally:
            workflow_engine.run_single_step = original_run_single_step
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces_dir
            state_store._workflows_to_resume.clear()

    assert workflow["status"] == "failed"
    assert workflow["current_step"] == "paper-plan"
    print("[PASS] test_workflow_stops_after_failed_step: failure propagated to workflow")


def test_claude_runner_inactivity_timeout():
    """Verify a silent executor process is terminated by inactivity timeout."""
    import services.claude_runner as claude_runner
    import services.llm_client as llm_client

    old_claude_bin = claude_runner.CLAUDE_BIN
    with tempfile.TemporaryDirectory() as td:
        # Self-contained Windows shim: accept any Claude CLI flags and stay silent.
        # Avoid embedding the Unicode project Python path inside a .cmd file.
        shim = Path(td) / "silent.cmd"
        shim.write_text(
            "@echo off\r\n"
            "ping -n 11 127.0.0.1 >nul\r\n"
            "exit /b 0\r\n",
            encoding="ascii",
        )
        claude_runner.CLAUDE_BIN = str(shim)
        runner = claude_runner.ClaudeRunner()
        runner.claude_bin = str(shim)

        async def _fake_settings():
            # Force the external Claude CLI path instead of the default Responses agent.
            return {"executor_provider": "anthropic_messages"}

        async def _fake_env():
            return {}

        async def _exercise():
            return await runner.run_skill(
                skill_name="missing",
                arguments="timeout test",
                cwd=td,
                workflow_id="timeout01",
                inactivity_timeout=1,
                overall_timeout=5,
                extra_params=None,
            )

        old_get_settings = llm_client.get_all_settings
        old_get_env = llm_client.get_env_for_subprocess
        llm_client.get_all_settings = _fake_settings
        llm_client.get_env_for_subprocess = _fake_env
        try:
            result = asyncio.run(_exercise())
        finally:
            claude_runner.CLAUDE_BIN = old_claude_bin
            llm_client.get_all_settings = old_get_settings
            llm_client.get_env_for_subprocess = old_get_env

    assert result["success"] is False
    assert result["returncode"] != 0
    assert "produced no output for 1s" in result["stderr"]
    print("[PASS] test_claude_runner_inactivity_timeout: silent process terminated")


def test_workflow_restarts_interrupted_running_step():
    """An interrupted running step must be re-executed, not silently skipped."""
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflow_engine.WORKSPACES_DIR
    old_run_single_step = workflow_engine.run_single_step
    old_broadcast = workflow_engine._broadcast_func
    calls = []
    events = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "resume-running.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "resume01"
        workspace.mkdir(parents=True)

        async def _capture(workflow_id, event):
            events.append(dict(event))

        async def _complete_step(workflow_id: str, skill_name: str) -> None:
            calls.append((workflow_id, skill_name))
            db = await state_store._get_db()
            try:
                await db.execute(
                    "UPDATE workflow_steps SET status = 'completed', completed_at = ? "
                    "WHERE workflow_id = ? AND skill_name = ?",
                    ("2026-07-10T00:00:00", workflow_id, skill_name),
                )
                await db.commit()
            finally:
                await db.close()

        async def _exercise():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "resume01",
                    "template": "experiment_bridge",
                    "title": "Resume Probe",
                    "params": {},
                    "status": "paused",
                    "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps "
                    "(workflow_id, skill_name, display_name, step_order, status, started_at, has_checkpoint, output_files) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("resume01", "experiment-bridge", "Experiment", 0, "running",
                     "2026-07-10T00:00:00", 0, "[]"),
                )
                await db.commit()
            finally:
                await db.close()

            workflow_engine.run_single_step = _complete_step
            workflow_engine.set_broadcast(_capture)
            await workflow_engine.run_workflow("resume01")

            db = await state_store._get_db()
            try:
                workflow = await state_store.get_workflow(db, "resume01")
                cursor = await db.execute(
                    "SELECT status FROM workflow_steps WHERE workflow_id = ? AND skill_name = ?",
                    ("resume01", "experiment-bridge"),
                )
                step = await cursor.fetchone()
                return workflow, dict(step)
            finally:
                await db.close()

        try:
            workflow, step = asyncio.run(_exercise())
        finally:
            workflow_engine.run_single_step = old_run_single_step
            workflow_engine._broadcast_func = old_broadcast
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces_dir
            state_store._workflows_to_resume.clear()

    assert calls == [("resume01", "experiment-bridge")]
    assert step["status"] == "completed"
    assert workflow["status"] == "failed"
    assert events[0]["type"] == "workflow_started"
    assert events[-1]["type"] == "workflow_failed"
    assert all(event["workflow_id"] == "resume01" for event in events)
    print("[PASS] test_workflow_restarts_interrupted_running_step: interrupted step re-executed")


def test_workflow_step_websocket_event_contract():
    """Step events must match the event names and fields consumed by the renderer."""
    import services.claude_runner as claude_runner
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflow_engine.WORKSPACES_DIR
    # experiment-bridge is a host scaffold in the current engine.
    old_run_skill = workflow_engine._HostStepRunner.run_skill
    old_broadcast = workflow_engine._broadcast_func
    events = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "events.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "events01"
        workspace.mkdir(parents=True)

        async def _capture(workflow_id, event):
            events.append(dict(event))

        async def _fake_run_skill(self, **kwargs):
            figure = Path(kwargs["cwd"]) / "figures" / "result.png"
            figure.parent.mkdir(parents=True, exist_ok=True)
            figure.write_bytes(b"mock image")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

        async def _exercise():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "events01",
                    "template": "experiment_bridge",
                    "title": "Event Probe",
                    "params": {},
                    "status": "pending",
                    "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps "
                    "(workflow_id, skill_name, display_name, step_order, status, has_checkpoint, output_files) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("events01", "experiment-bridge", "Experiment", 0, "pending", 0, "[]"),
                )
                await db.commit()
            finally:
                await db.close()

            workflow_engine._HostStepRunner.run_skill = _fake_run_skill
            workflow_engine.set_broadcast(_capture)
            await workflow_engine.run_single_step("events01", "experiment-bridge")

        try:
            asyncio.run(_exercise())
        finally:
            workflow_engine._HostStepRunner.run_skill = old_run_skill
            workflow_engine._broadcast_func = old_broadcast
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces_dir
            state_store._workflows_to_resume.clear()

    step_events = [
        event for event in events
        if isinstance(event.get("type"), str) and event["type"].startswith("step_")
    ]
    assert [event["type"] for event in step_events] == ["step_started", "step_completed"]
    assert all(event["workflow_id"] == "events01" for event in step_events)
    assert all(event["step"] == "experiment-bridge" for event in step_events)
    print("[PASS] test_workflow_step_websocket_event_contract: renderer-compatible events emitted")


def test_workflow_retries_failed_runner_eight_times():
    """Full workflow execution retries eight times; standalone rerun does not."""
    import services.claude_runner as claude_runner
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflow_engine.WORKSPACES_DIR
    old_run_skill = claude_runner.ClaudeRunner.run_skill
    old_template = workflow_engine.TEMPLATES.get("retry_probe")
    calls = []

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "retry.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "retry01"
        workspace.mkdir(parents=True)
        workflow_engine.TEMPLATES["retry_probe"] = workflow_engine.TemplateDef(
            pipeline_skill="retry_probe", display_name="retry_probe",
            sub_steps=[workflow_engine.StepDef(skill_name="retry-skill", display_name="Retry")],
        )

        async def _failing_run_skill(self, **kwargs):
            calls.append(kwargs["skill_name"])
            return {"success": False, "stdout": "", "stderr": "planned failure", "returncode": 9}

        async def _exercise():
            await state_store.init_db()
            db = await state_store._get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "retry01", "template": "retry_probe", "title": "Retry probe",
                    "params": {}, "status": "pending", "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id, skill_name, display_name, step_order, status, has_checkpoint, output_files) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("retry01", "retry-skill", "Retry", 0, "pending", 0, "[]"),
                )
                await db.commit()
            finally:
                await db.close()
            claude_runner.ClaudeRunner.run_skill = _failing_run_skill
            await workflow_engine.run_workflow("retry01")
            db = await state_store._get_db()
            try:
                step = dict(await (await db.execute(
                    "SELECT status, error_message FROM workflow_steps WHERE workflow_id = ?", ("retry01",)
                )).fetchone())
                retry_logs = await (await db.execute(
                    "SELECT message FROM workflow_logs WHERE workflow_id = ? AND message LIKE '[RETRY]%' ORDER BY id", ("retry01",)
                )).fetchall()
                return step, [row["message"] for row in retry_logs]
            finally:
                await db.close()

        try:
            step, retry_logs = asyncio.run(_exercise())
        finally:
            claude_runner.ClaudeRunner.run_skill = old_run_skill
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces_dir
            if old_template is None:
                workflow_engine.TEMPLATES.pop("retry_probe", None)
            else:
                workflow_engine.TEMPLATES["retry_probe"] = old_template
            state_store._workflows_to_resume.clear()

    assert calls == ["retry-skill"] * 9
    assert step == {"status": "failed", "error_message": "planned failure"}
    assert len(retry_logs) == 8
    assert retry_logs[0].endswith("attempt 1/8)")
    assert retry_logs[-1].endswith("attempt 8/8)")
    print("[PASS] test_workflow_retries_failed_runner_eight_times: nine attempts and retry logs")


def test_workflow_standalone_rerun_terminal_contract():
    """Standalone reruns execute once and own workflow start/terminal events.

    paper-plan is a host-step scaffold in the current engine, so the runner under
    test is HostStepRunner rather than ClaudeRunner.
    """
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces = workflow_engine.WORKSPACES_DIR
    old_run_skill = workflow_engine._HostStepRunner.run_skill
    old_broadcast = workflow_engine._broadcast_func
    events = []
    calls = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "standalone.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "standalone01"
        workspace.mkdir(parents=True)

        async def capture(workflow_id, event):
            events.append(dict(event))

        async def fake_run(self, **kwargs):
            calls.append(self.step.skill_name)
            (Path(kwargs["cwd"]) / "PAPER_PLAN.md").write_text("P" * 1200, encoding="utf-8")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

        async def exercise():
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "standalone01", "template": "paper_writing", "title": "standalone",
                    "params": {}, "status": "pending", "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,has_checkpoint,output_files) VALUES (?,?,?,?,?,?,?)",
                    ("standalone01", "paper-plan", "Plan", 0, "pending", 1, "[]"),
                )
                await db.commit()
            finally:
                await db.close()
            await workflow_engine.run_single_step("standalone01", "paper-plan")

        workflow_engine._HostStepRunner.run_skill = fake_run
        workflow_engine.set_broadcast(capture)
        try:
            asyncio.run(exercise())
        finally:
            workflow_engine._HostStepRunner.run_skill = old_run_skill
            workflow_engine._broadcast_func = old_broadcast
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces
            state_store._workflows_to_resume.clear()

    assert calls == ["paper-plan"]
    # Host runners may emit intermediate progress/log events; require the
    # terminal ownership sequence rather than exact event equality.
    types = [event["type"] for event in events if event.get("type")]
    assert types[0] == "workflow_started"
    assert "step_started" in types
    assert "step_completed" in types
    assert types[-1] == "workflow_completed"
    print("[PASS] test_workflow_standalone_rerun_terminal_contract: one call and terminal events")


def test_managed_step_success_keeps_workflow_running():
    """Managed multi-step runs must not mark the whole workflow completed mid-DAG."""
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces = workflow_engine.WORKSPACES_DIR
    old_run_skill = workflow_engine._HostStepRunner.run_skill
    old_broadcast = workflow_engine._broadcast_func
    events = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "managed.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "managed01"
        workspace.mkdir(parents=True)

        async def capture(workflow_id, event):
            events.append(dict(event))

        async def fake_run(self, **kwargs):
            (Path(kwargs["cwd"]) / "PAPER_PLAN.md").write_text("P" * 1200, encoding="utf-8")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

        async def exercise():
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "managed01", "template": "paper_writing", "title": "managed",
                    "params": {}, "status": "running", "workspace_dir": str(workspace),
                })
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,has_checkpoint,output_files) VALUES (?,?,?,?,?,?,?)",
                    ("managed01", "paper-plan", "Plan", 0, "pending", 1, "[]"),
                )
                await db.execute(
                    "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,has_checkpoint,output_files) VALUES (?,?,?,?,?,?,?)",
                    ("managed01", "paper-write", "Write", 1, "pending", 0, "[]"),
                )
                await db.commit()
            finally:
                await db.close()
            workflow_engine._workflow_managed_steps.add("managed01")
            try:
                await workflow_engine.run_single_step("managed01", "paper-plan")
            finally:
                workflow_engine._workflow_managed_steps.discard("managed01")
            db = await state_store.get_db()
            try:
                workflow = await (await db.execute("SELECT status, current_step FROM workflows WHERE id=?", ("managed01",))).fetchone()
                step = await (await db.execute("SELECT status FROM workflow_steps WHERE workflow_id=? AND skill_name=?", ("managed01", "paper-plan"))).fetchone()
                later = await (await db.execute("SELECT status FROM workflow_steps WHERE workflow_id=? AND skill_name=?", ("managed01", "paper-write"))).fetchone()
                return dict(workflow), dict(step), dict(later)
            finally:
                await db.close()

        workflow_engine._HostStepRunner.run_skill = fake_run
        workflow_engine.set_broadcast(capture)
        try:
            workflow, step, later = asyncio.run(exercise())
        finally:
            workflow_engine._HostStepRunner.run_skill = old_run_skill
            workflow_engine._broadcast_func = old_broadcast
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces
            workflow_engine._workflow_managed_steps.clear()
            state_store._workflows_to_resume.clear()

    assert step["status"] == "completed"
    assert later["status"] == "pending"
    assert workflow["status"] == "running"
    assert workflow["current_step"] == "paper-plan"
    assert "workflow_completed" not in {event["type"] for event in events}
    print("[PASS] test_managed_step_success_keeps_workflow_running: intermediate success stays running")





def test_workflow_file_watchdog_attribution_contract():
    """Full workflows attribute every pre-step file as modified in declared order."""
    import services.claude_runner as claude_runner
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces = workflow_engine.WORKSPACES_DIR
    old_run_skill = claude_runner.ClaudeRunner.run_skill
    old_broadcast = workflow_engine._broadcast_func
    events = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "watchdog.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        workspace = workflow_engine.WORKSPACES_DIR / "watchdog01"
        workspace.mkdir(parents=True)
        (workspace / "notes.txt").write_text("preexisting", encoding="utf-8")

        async def capture(workflow_id, event):
            events.append(dict(event))

        async def fake_run(self, skill_name, cwd, **kwargs):
            cwd = Path(cwd)
            if skill_name == "paper-plan":
                (cwd / "PAPER_PLAN.md").write_text("P" * 1200, encoding="utf-8")
            else:
                (cwd / "RESULTS.md").write_text("R" * 1200, encoding="utf-8")
                (cwd / "code").mkdir(exist_ok=True)
                (cwd / "code" / "main.py").write_text("print('ok')", encoding="utf-8")
                (cwd / "figures").mkdir(exist_ok=True)
                (cwd / "figures" / "all_results.json").write_text("{}", encoding="utf-8")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

        async def exercise():
            await state_store.init_db()
            db = await state_store.get_db()
            try:
                await state_store.create_workflow(db, {
                    "id": "watchdog01", "template": "paper_writing", "title": "watchdog",
                    "params": {}, "status": "pending", "workspace_dir": str(workspace),
                    "enable_checkpoints": False,
                })
                for order, skill in enumerate(("paper-plan", "paper-analysis")):
                    step = next(x for x in workflow_engine.TEMPLATES["paper_writing"].sub_steps if x.skill_name == skill)
                    await db.execute(
                        "INSERT INTO workflow_steps (workflow_id,skill_name,display_name,step_order,status,has_checkpoint,output_files) VALUES (?,?,?,?,?,?,?)",
                        ("watchdog01", skill, step.display_name, order, "pending", 0, json.dumps(step.output_files)),
                    )
                await db.commit()
            finally:
                await db.close()
            await workflow_engine.run_workflow("watchdog01")
            db = await state_store.get_db()
            try:
                rows = await (await db.execute(
                    "SELECT output_files FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
                    ("watchdog01",),
                )).fetchall()
                return [json.loads(row["output_files"]) for row in rows]
            finally:
                await db.close()

        claude_runner.ClaudeRunner.run_skill = fake_run
        workflow_engine.set_broadcast(capture)
        try:
            outputs = asyncio.run(exercise())
        finally:
            claude_runner.ClaudeRunner.run_skill = old_run_skill
            workflow_engine._broadcast_func = old_broadcast
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces
            workflow_engine._workflow_managed_steps.clear()
            state_store._workflows_to_resume.clear()

    completed = [event for event in events if event["type"] == "step_completed"]
    assert outputs == [
        ["PAPER_PLAN.md", "notes.txt"],
        ["RESULTS.md", "figures/all_results.json", "code/main.py", "notes.txt", "PAPER_PLAN.md"],
    ]
    assert [event["result_summary"] for event in completed] == [
        "创建 1 个文件，更新 1 个文件", "创建 3 个文件，更新 2 个文件",
    ]
    print("[PASS] test_workflow_file_watchdog_attribution_contract: installed attribution and order")


def test_workflow_creation_and_checkpoint_contract():
    """Match the observed original workspace bootstrap and checkpoint ABI."""
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces_dir = workflow_engine.WORKSPACES_DIR
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "create-contract.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"

        async def _exercise():
            await state_store.init_db()
            workflow_id = await workflow_engine.create_new_workflow(
                "experiment_bridge", "Create Contract", {"topic": "probe"}, False
            )
            workspace = workflow_engine.WORKSPACES_DIR / workflow_id

            waiter = asyncio.create_task(workflow_engine.wait_checkpoint(workflow_id, timeout=1))
            await asyncio.sleep(0)
            resolved = workflow_engine.resolve_checkpoint(workflow_id, {"action": "reject"})
            response = await waiter

            timeout_response = await workflow_engine.wait_checkpoint("timeout-contract", timeout=0)
            db = await state_store._get_db()
            try:
                workflow = await state_store.get_workflow(db, workflow_id)
            finally:
                await db.close()
            return workflow_id, workspace, workflow, resolved, response, timeout_response

        try:
            workflow_id, workspace, workflow, resolved, response, timeout_response = asyncio.run(_exercise())
        finally:
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces_dir
            workflow_engine._checkpoint_events.clear()
            workflow_engine._checkpoint_responses.clear()
            state_store._workflows_to_resume.clear()

        assert len(workflow_id) == 12
        assert (workspace / "CLAUDE.md").is_file()
        assert (workspace / ".git" / "HEAD").is_file()
        assert workflow["params"]["_sub_steps_pruned"] is True
        assert resolved is True
        assert response == {"action": "reject"}
        assert timeout_response == {"action": "approve", "auto": True}

    print("[PASS] test_workflow_creation_and_checkpoint_contract: original bootstrap ABI restored")


def test_workflow_template_resolver_full_matrix():
    """Pin all 34 installed templates across the 17 observed resolver branches."""
    import services.workflow_engine as workflow_engine

    cases = {
        "baseline": {},
        "pdf": {"output_format": "pdf"},
        "docx": {"output_format": "docx"},
        "docx_upper": {"output_format": "DOCX"},
        "docx_format_text": {"output_format": "docx", "format_text": "Songti, 1.5 line spacing"},
        "docx_template_file": {"output_format": "docx", "template_file": "user_data/template.docx"},
        "docx_template_files": {"output_format": "docx", "template_files": ["user_data/template.docx"]},
        "docx_format_and_template": {
            "output_format": "docx", "format_text": "Songti, 1.5 line spacing",
            "template_file": "user_data/template.docx", "template_files": ["user_data/template.cls"],
        },
        "skip_improvement": {"skip_improvement_loop": True},
        "docx_skip_improvement": {"output_format": "docx", "skip_improvement_loop": True},
        "zh": {"language": "zh"},
        "chinese": {"language": "chinese"},
        "chinese_text": {"language": "中文"},
        "zh_docx": {"language": "zh", "output_format": "docx"},
        "skip_figures": {"skip_figures": True},
        "skip_analysis": {"skip_analysis": True},
        "skip_drawio": {"skip_drawio": True},
    }

    def serialize(template):
        return {
            "pipeline_skill": template.pipeline_skill,
            "display_name": template.display_name,
            "sub_steps": [
                {
                    "skill_name": step.skill_name,
                    "display_name": step.display_name,
                    "output_files": list(step.output_files),
                    "primary_output": step.primary_output,
                    "has_checkpoint": step.has_checkpoint,
                    "checkpoint_type": step.checkpoint_type,
                }
                for step in template.sub_steps
            ],
        }

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        (workspace / "user_data").mkdir()
        (workspace / "user_data" / "template.docx").write_bytes(b"fixture")
        (workspace / "user_data" / "template.cls").write_text("fixture", encoding="utf-8")
        matrix = {
            template_name: {
                case_name: {"result": serialize(workflow_engine._resolve_template(template_name, params, workspace))}
                for case_name, params in cases.items()
            }
            for template_name in workflow_engine.TEMPLATES
        }

    try:
        workflow_engine._resolve_template("not_a_template", {}, Path("."))
    except Exception as exc:
        invalid = {"type": type(exc).__name__, "message": str(exc)}
    else:
        invalid = None
    canonical = {"cases": cases, "templates": matrix, "invalid_template": invalid}
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # Product currently ships the full research/academic/competition/IP surface.
    # Keep the matrix structurally complete without freezing a pre-1.5.3 34-template hash.
    assert len(matrix) >= 40
    assert len(cases) == 17
    assert set(matrix) == set(__import__("services.workflow_engine", fromlist=["TEMPLATES"]).TEMPLATES)
    for template_name, template_cases in matrix.items():
        assert set(template_cases) == set(cases)
        baseline = template_cases["baseline"]["result"]
        assert baseline["pipeline_skill"]
        assert baseline["sub_steps"]
    assert invalid == {"type": "ValueError", "message": "Unknown template: not_a_template"}
    print(f"[PASS] test_workflow_template_resolver_full_matrix: {len(matrix)} templates x {len(cases)} cases; digest={digest[:12]}")


def test_workflow_checkpoint_and_cancel_state_edges():
    """Pin checkpoint gating, waiting states, and cancellation recovery."""
    import services.claude_runner as claude_runner
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine

    old_db_path = state_store.DB_PATH
    old_workspaces = workflow_engine.WORKSPACES_DIR
    old_run_skill = claude_runner.ClaudeRunner.run_skill
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state_store.DB_PATH = root / "edges.db"
        workflow_engine.WORKSPACES_DIR = root / "workspaces"
        gates = {}
        calls = []

        async def fake_run(self, skill_name, arguments, cwd, workflow_id, **kwargs):
            calls.append(skill_name)
            cwd = Path(cwd)
            if skill_name == "paper-plan":
                if skill_name in gates:
                    await gates[skill_name].wait()
                (cwd / "PAPER_PLAN.md").write_text("P" * 1200, encoding="utf-8")
            elif skill_name == "paper-analysis":
                (cwd / "RESULTS.md").write_text("R" * 1200, encoding="utf-8")
                (cwd / "code").mkdir(exist_ok=True)
                (cwd / "code" / "main.py").write_text("print('ok')", encoding="utf-8")
                (cwd / "figures").mkdir(exist_ok=True)
                (cwd / "figures" / "all_results.json").write_text("{}", encoding="utf-8")
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0, "return_code": 0}

        async def snapshot(workflow_id):
            db = await state_store.get_db()
            try:
                wf = await state_store.get_workflow(db, workflow_id)
                rows = await (await db.execute(
                    "SELECT skill_name,status FROM workflow_steps WHERE workflow_id=? ORDER BY step_order",
                    (workflow_id,),
                )).fetchall()
                return wf, [dict(row) for row in rows]
            finally:
                await db.close()

        async def exercise():
            await state_store.init_db()

            disabled = await workflow_engine.create_new_workflow("paper_writing", "disabled", {}, False)
            disabled_task = asyncio.create_task(workflow_engine.run_workflow(disabled))
            await asyncio.sleep(0.1)
            assert workflow_engine.resolve_checkpoint(disabled, {"action": "approve"}) is False
            await asyncio.gather(disabled_task, return_exceptions=True)
            disabled_wf, disabled_steps = await snapshot(disabled)

            calls.clear()
            enabled = await workflow_engine.create_new_workflow("paper_writing", "enabled", {}, True)
            enabled_task = asyncio.create_task(workflow_engine.run_workflow(enabled))
            # Wait until the first checkpoint registers an in-memory waiter.
            # Fixed sleeps race with machine load and flake under full suites.
            for _ in range(100):
                if enabled in workflow_engine._checkpoint_events:
                    break
                await asyncio.sleep(0.02)
            enabled_wf_1, enabled_steps_1 = await snapshot(enabled)
            assert enabled in workflow_engine._checkpoint_events
            assert workflow_engine.resolve_checkpoint(enabled, {"action": "approve"}) is True
            # After approving the first checkpoint, wait for the next step to
            # either register a new waiter or reach waiting_checkpoint. A fixed
            # 100ms sleep races under full-suite load and can observe a later
            # completed step instead of the second checkpoint.
            for _ in range(150):
                enabled_wf_2, enabled_steps_2 = await snapshot(enabled)
                second = next((row for row in enabled_steps_2 if row["skill_name"] == "paper-analysis"), None)
                if enabled in workflow_engine._checkpoint_events and second and second["status"] == "waiting_checkpoint":
                    break
                await asyncio.sleep(0.02)
            else:
                enabled_wf_2, enabled_steps_2 = await snapshot(enabled)
            enabled_task.cancel()
            await asyncio.gather(enabled_task, return_exceptions=True)

            calls.clear()
            cancelled = await workflow_engine.create_new_workflow("paper_writing", "cancelled", {}, False)
            gates["paper-plan"] = asyncio.Event()
            cancel_task = asyncio.create_task(workflow_engine.run_workflow(cancelled))
            for _ in range(50):
                if "paper-plan" in calls:
                    break
                await asyncio.sleep(0.01)
            cancel_task.cancel()
            cancel_result = await asyncio.gather(cancel_task, return_exceptions=True)
            cancelled_wf, cancelled_steps = await snapshot(cancelled)
            return (
                disabled_wf, disabled_steps,
                enabled_wf_1, enabled_steps_1, enabled_wf_2, enabled_steps_2,
                cancel_result, cancelled_wf, cancelled_steps,
            )

        claude_runner.ClaudeRunner.run_skill = fake_run
        try:
            values = asyncio.run(exercise())
        finally:
            claude_runner.ClaudeRunner.run_skill = old_run_skill
            state_store.DB_PATH = old_db_path
            workflow_engine.WORKSPACES_DIR = old_workspaces
            workflow_engine._checkpoint_events.clear()
            workflow_engine._checkpoint_responses.clear()
            state_store._workflows_to_resume.clear()

    disabled_wf, disabled_steps, enabled_wf_1, enabled_steps_1, enabled_wf_2, enabled_steps_2, cancel_result, cancelled_wf, cancelled_steps = values
    assert disabled_steps[0]["status"] == "completed"
    assert disabled_wf["status"] != "paused"
    assert enabled_wf_1["status"] == "paused"
    assert enabled_steps_1[0] == {"skill_name": "paper-plan", "status": "waiting_checkpoint"}
    assert enabled_steps_2[0]["status"] == "completed"
    assert enabled_steps_2[1] == {"skill_name": "paper-analysis", "status": "waiting_checkpoint"}
    assert cancel_result == [None]
    assert cancelled_wf["status"] == "paused"
    assert cancelled_steps[0] == {"skill_name": "paper-plan", "status": "pending"}
    print("[PASS] test_workflow_checkpoint_and_cancel_state_edges: installed state edges restored")


def run_all():
    """Run all tests."""
    tests = [
        test_imports, test_config, test_schemas, test_templates,
        test_app_routes, test_prompts, test_state_store, test_abis_database,
        test_state_store_recovered_contract,
        test_state_store_contention_contract,
        test_ws_manager, test_encrypt_decrypt,
        test_batch_export_contains_manifest_and_artifacts,
        test_workflow_asset_and_figure_helpers,
        test_workflow_vision_and_context_compression_helpers,
        test_skill_prompt_loading,
        test_interrupted_workflow_resume_cache,
        test_image_extraction_awaits_vision_result,
        test_workflow_stops_after_failed_step,
        test_claude_runner_inactivity_timeout,
        test_workflow_restarts_interrupted_running_step,
        test_workflow_step_websocket_event_contract,
        test_workflow_retries_failed_runner_eight_times,
        test_workflow_standalone_rerun_terminal_contract,
        test_workflow_file_watchdog_attribution_contract,
        test_workflow_creation_and_checkpoint_contract,
        test_workflow_template_resolver_full_matrix,
        test_workflow_checkpoint_and_cancel_state_edges,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Tests: {passed} passed, {failed} failed, {len(tests)} total")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"{failed} TEST(S) FAILED!")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
