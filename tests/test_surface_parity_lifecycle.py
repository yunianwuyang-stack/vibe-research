"""Surface parity + multi-family lifecycle tests against shipped code.

These tests drive real catalog/options/lifecycle/export/secret paths — not
re-implementations — and form the gating suite for workflow surface parity.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

def _resolve_reference_options() -> Path:
    candidates = [
        Path(r"D:\科研软件制作\audit_artifacts\frontend_options.json"),
        ROOT.parent / "audit_artifacts" / "frontend_options.json",
    ]
    audit_dir = Path(r"D:\科研软件制作\audit_artifacts")
    if audit_dir.is_dir():
        candidates.extend(sorted(audit_dir.glob("*frontend_options.json")))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


REFERENCE_OPTIONS = _resolve_reference_options()

MAIN_TSX = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
CONFIG_TSX = (ROOT / "frontend" / "src" / "workflow-config.tsx").read_text(encoding="utf-8")

# Representative workflow from every OBJECTIVE family.
FAMILY_CASES: list[dict] = [
    {
        "family": "competition",
        "template": "comp_tianfu",
        "title": "天府杯样例",
        "params": {
            "output_format": "pdf",
            "problem_statement": "示例赛题正文：建立模型并求解。",
            "validation_mode": "strict",
            "skip_improvement_loop": False,
            "rich_mode": False,
            "min_figures": 12,
            "flowchart_engine": "html",
        },
        "enable_checkpoints": True,
        "upload_role": "problem",
        "upload_name": "problem.pdf",
        "upload_bytes": b"%PDF-1.4 sample competition problem",
    },
    {
        "family": "research",
        "template": "idea_discovery",
        "title": "Idea 发现样例",
        "params": {"skip_improvement_loop": True},
        "enable_checkpoints": True,
    },
    {
        "family": "academic",
        "template": "paper_writing",
        "title": "学术写作样例",
        "params": {
            "language": "zh",
            "paper_branch": "general",
            "output_format": "pdf",
            "skip_improvement_loop": True,
            "max_pages": 15,
        },
        "enable_checkpoints": True,
    },
    {
        "family": "assets",
        "template": "paper_from_assets",
        "title": "已有资料写论文样例",
        "params": {
            "paper_type_target": "academic_zh",
            "output_format": "pdf",
            "skip_improvement_loop": True,
        },
        "enable_checkpoints": True,
        "upload_role": "requirements",
        "upload_name": "requirements.md",
        "upload_bytes": b"# Topic\nWrite a short methods paper from assets.\n",
    },
    {
        "family": "one_sentence",
        "template": "grad_project",
        "title": "一句话生成待办系统",
        "params": {
            "project_type": "fullstack",
            "tech_frontend": "React",
            "tech_backend": "FastAPI",
            "tech_db": "SQLite",
            "skip_report": True,
        },
        "enable_checkpoints": True,
    },
    {
        "family": "ip_soft",
        "template": "copyright_material",
        "title": "软著样例",
        "params": {
            "software_name": "科研助手管理系统",
            "software_version": "V1.0",
            "skip_improvement_loop": True,
        },
        "enable_checkpoints": True,
    },
    {
        "family": "ip_patent",
        "template": "patent_disclosure",
        "title": "专利样例",
        "params": {
            "case_name": "一种基于多Agent的科研工作流编排方法",
            "skip_improvement_loop": True,
        },
        "enable_checkpoints": True,
    },
]


def _category_templates(category_id: str) -> list[str]:
    match = re.search(
        rf'id:\s*"{re.escape(category_id)}"[\s\S]*?templates:\s*\[([\s\S]*?)\],',
        MAIN_TSX,
    )
    assert match, f"missing template category: {category_id}"
    return re.findall(r'"([a-z0-9_]+)"', match.group(1))


def test_frontend_and_backend_catalog_match_reference_cards():
    assert REFERENCE_OPTIONS.is_file(), f"missing reference options corpus: {REFERENCE_OPTIONS}"
    reference = json.loads(REFERENCE_OPTIONS.read_text(encoding="utf-8"))
    from services.workflow_options import FAMILY_TEMPLATES, COMPETITIONS, DEFAULTS, catalog

    # Reference cards (excluding encoding-broken label text) must all exist.
    reference_ids = [card["value"] for cards in reference["cards"].values() for card in cards]
    ui_ids = []
    for category in (
        "research",
        "academic",
        "competition",
        "assets",
        "one_sentence",
        "ip",
    ):
        ui_ids.extend(_category_templates(category))
    # communication is a preserved current-app surface.
    assert _category_templates("communication") == ["paper_slides", "paper_poster"]

    missing_ui = [item for item in reference_ids if item not in ui_ids]
    assert not missing_ui, f"Reference cards missing from UI: {missing_ui}"

    # Competition order is the calendar contract.
    assert _category_templates("competition") == list(COMPETITIONS.keys())
    assert FAMILY_TEMPLATES["competition"] == list(COMPETITIONS.keys())

    for family, templates in FAMILY_TEMPLATES.items():
        for template in templates:
            assert template in DEFAULTS or template == "paper_writing", template

    cat = catalog()
    assert cat["version"] >= 2
    assert set(cat["families"]) >= {
        "research",
        "academic",
        "competition",
        "assets",
        "one_sentence",
        "ip",
        "communication",
    }
    for key in (
        "paper_types_zh",
        "venues_en",
        "paper_from_assets_target_types",
        "course_subject_domains",
        "humanities_subject_domains",
        "ui_controls",
    ):
        assert key in cat["option_sets"]

    # Frontend must surface upload/template/format/review/checkpoint/loop controls.
    for needle in (
        "人工检查点",
        "论文改进循环",
        "skip_improvement_loop",
        "格式模板",
        "输出格式",
        "审查模式",
        "题目 / 写作要求",
        "论文模板",
        "project_type",
        "software_name",
        "case_name",
        "paper_type_target",
    ):
        assert needle in CONFIG_TSX, f"missing UI control surface: {needle}"


@pytest.mark.parametrize(
    "template,params,expected_keys",
    [
        (
            "comp_huawei",
            {
                "output_format": "pdf",
                "validation_mode": "fast",
                "rich_mode": True,
                "skip_improvement_loop": False,
                "min_figures": 30,
                "min_tables": 8,
                "flowchart_engine": "drawio",
                "figure_style": "nature",
                "tools": "python+matlab",
            },
            {
                "competition": "huawei",
                "language": "zh",
                "max_pages": 50,
                "rich_mode": True,
                "skip_improvement_loop": False,
                "min_figures": 30,
                "validation_mode": "fast",
                "tools": "python+matlab",
            },
        ),
        (
            "paper_writing",
            {"paper_branch": "nature", "output_format": "docx", "skip_improvement_loop": False},
            {"figure_style": "nature", "output_format": "docx", "skip_improvement_loop": False},
        ),
        (
            "paper_from_assets",
            {"paper_type_target": "nature", "skip_improvement_loop": False},
            {"paper_type_target": "nature", "skip_improvement_loop": False},
        ),
        (
            "grad_project",
            {"project_type": "cli", "tech_lang": "Python", "skip_report": False},
            {"project_type": "cli", "tech_lang": "Python", "skip_report": False},
        ),
        (
            "copyright_material",
            {"software_name": "Demo Soft", "software_version": "V2.0"},
            {"software_name": "Demo Soft", "software_version": "V2.0"},
        ),
        (
            "software_copyright",
            {"software_name": "Inventory Soft", "software_version": "V3.0"},
            {"software_name": "Inventory Soft", "software_version": "V3.0"},
        ),
        (
            "patent_disclosure",
            {"case_name": "一种方法"},
            {"case_name": "一种方法"},
        ),
        (
            "auto_review",
            {"max_rounds": 3, "target_score": 7, "output_format": "docx"},
            {"max_rounds": 3, "target_score": 7, "output_format": "docx"},
        ),
    ],
)
def test_normalize_workflow_params_round_trip(template, params, expected_keys):
    from services.workflow_options import normalize_workflow_params, _canonical_paper_template
    from services.workflow_engine import TEMPLATES, _resolve_template

    normalized = normalize_workflow_params(template, params)
    for key, value in expected_keys.items():
        assert normalized.get(key) == value, (template, key, normalized.get(key), value)

    resolved_id = _canonical_paper_template(template, params)
    assert resolved_id in TEMPLATES
    # Engine must resolve at least one step for the canonical template.
    steps = _resolve_template(resolved_id, normalized, Path("."))
    assert steps.sub_steps


def test_invalid_params_return_structured_422():
    from fastapi import HTTPException
    from services.workflow_options import normalize_workflow_params

    with pytest.raises(HTTPException) as exc:
        normalize_workflow_params("paper_writing", {"output_format": "exe"})
    assert exc.value.status_code == 422
    assert "output_format" in str(exc.value.detail)

    with pytest.raises(HTTPException) as exc:
        normalize_workflow_params("comp_mcm", {"max_pages": 9999})
    assert exc.value.status_code == 422


def test_improvement_loop_flag_changes_engine_steps():
    import tempfile
    from services.workflow_engine import _resolve_template
    from services.workflow_options import normalize_workflow_params

    root = Path(tempfile.mkdtemp())
    off = _resolve_template(
        "comp_cumcm",
        normalize_workflow_params("comp_cumcm", {"skip_improvement_loop": True}),
        root,
    )
    on = _resolve_template(
        "comp_cumcm",
        normalize_workflow_params("comp_cumcm", {"skip_improvement_loop": False}),
        root,
    )
    off_names = {step.skill_name for step in off.sub_steps}
    on_names = {step.skill_name for step in on.sub_steps}
    assert "auto-paper-improvement-loop" not in off_names
    assert "auto-paper-improvement-loop" in on_names or "auto-paper-improvement-docx" in on_names


def test_secret_scan_source_has_no_hardcoded_test_keys():
    patterns = [
        re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
        re.compile(r"ANTHROPIC_API_KEY\s*=\s*[\"'][^\"']{8,}[\"']"),
        re.compile(r"ANTHROPIC_AUTH_TOKEN\s*=\s*[\"'][^\"']{8,}[\"']"),
    ]
    skip = {
        ".git",
        "node_modules",
        "__pycache__",
        "dist",
        "release",
        "runtime",
        "runtime-release",
        ".pytest_cache",
        "verification-logs",
        "skills_encrypted_backup",
    }
    evidence_root = ROOT / "harness" / "evidence"
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    hits: list[str] = []
    excluded_evidence_dirs: list[str] = []
    unexpected_reparse_entries: list[str] = []
    unreadable_source_entries: list[str] = []
    scanned_source_files = 0

    for current_raw, directories, filenames in os.walk(ROOT, topdown=True, followlinks=False):
        current = Path(current_raw)
        retained_directories: list[str] = []
        for directory in directories:
            candidate = current / directory
            relative = candidate.relative_to(ROOT).as_posix()
            if directory in skip:
                continue
            if candidate == evidence_root:
                excluded_evidence_dirs.append(relative)
                continue
            try:
                metadata = candidate.lstat()
            except OSError as exc:
                unreadable_source_entries.append(f"{relative}: {type(exc).__name__}")
                continue
            if candidate.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag):
                unexpected_reparse_entries.append(relative)
                continue
            retained_directories.append(directory)
        directories[:] = retained_directories

        for filename in filenames:
            path = current / filename
            relative = path.relative_to(ROOT).as_posix()
            try:
                metadata = path.lstat()
            except OSError as exc:
                unreadable_source_entries.append(f"{relative}: {type(exc).__name__}")
                continue
            if path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag):
                unexpected_reparse_entries.append(relative)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".json", ".md", ".env", ".txt"}:
                continue
            scanned_source_files += 1
            source_text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat.search(source_text):
                    hits.append(relative)

    assert excluded_evidence_dirs == ["harness/evidence"]
    assert scanned_source_files > 0
    assert not unreadable_source_entries, f"unreadable source entries: {unreadable_source_entries}"
    assert not unexpected_reparse_entries, f"unexpected source reparse entries: {unexpected_reparse_entries}"
    assert not hits, f"hardcoded secrets found: {hits}"


def test_claude_code_config_import_uses_secret_store(tmp_path, monkeypatch):
    import services.secret_store as secret_store
    import services.state_store as state_store
    from services.claude_code_config import (
        extract_anthropic_credentials,
        import_claude_code_into_secret_store,
    )

    settings_file = tmp_path / "claude-settings.json"
    settings_file.write_text(
        json.dumps(
            {
                "env": {
                    "ANTHROPIC_AUTH_TOKEN": "test-live-secret-token-abc",
                    "ANTHROPIC_BASE_URL": "https://example.claude-proxy.test/v1",
                    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-test-model",
                }
            }
        ),
        encoding="utf-8",
    )
    creds = extract_anthropic_credentials(
        json.loads(settings_file.read_text(encoding="utf-8"))
    )
    assert creds["api_key"] == "test-live-secret-token-abc"
    assert creds["base_url"].startswith("https://")

    store = secret_store.SecretStore(tmp_path / "secrets.json", b"parity-test-key-material!!")
    monkeypatch.setattr(secret_store, "_default_store", store)
    state_store.DB_PATH = tmp_path / "settings.db"

    async def exercise():
        await state_store.init_db()
        summary = await import_claude_code_into_secret_store(settings_path=settings_file)
        metadata = await state_store.get_settings_metadata()
        profiles = await __import__("services.model_profiles", fromlist=["profiles"]).profiles()
        return summary, metadata, profiles

    summary, metadata, profiles = asyncio.run(exercise())
    assert summary["imported"] is True
    assert summary["api_key_configured"] is True
    assert "test-live-secret-token-abc" not in json.dumps(summary)
    assert metadata["executor_api_key"] == {"configured": True}
    executor = next(item for item in profiles["profiles"] if item["role"] == "executor")
    assert executor["api_key_configured"] is True
    assert executor["base_url"] == "https://example.claude-proxy.test/v1"
    assert "test-live-secret-token-abc" not in json.dumps(profiles)
    assert "test-live-secret-token-abc" not in (tmp_path / "settings.db").read_bytes().decode("latin1")
    assert store.get("executor_api_key") == "test-live-secret-token-abc"


def _seed_upload(workspace: Path, role: str, name: str, payload: bytes) -> None:
    user_data = workspace / "user_data"
    user_data.mkdir(parents=True, exist_ok=True)
    target = user_data / name
    target.write_bytes(payload)
    rel = name
    manifest = {
        "files": {
            rel: {
                "role": role,
                "name": name,
                "size": len(payload),
            }
        }
    }
    (user_data / "_input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.mark.parametrize("case", FAMILY_CASES, ids=lambda c: c["family"])
def test_family_create_params_persist_and_export(case, tmp_path, monkeypatch):
    """Create → persist params → export non-empty archive for each family."""
    import services.secret_store as secret_store
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine
    from services.workflow_options import normalize_workflow_params

    root = tmp_path / case["family"]
    root.mkdir()
    state_store.DB_PATH = root / "wf.db"
    workflow_engine.WORKSPACES_DIR = root / "workspaces"
    monkeypatch.setattr(
        secret_store,
        "_default_store",
        secret_store.SecretStore(root / "secrets.json", b"family-export-key-material!!"),
    )

    async def exercise():
        await state_store.init_db()
        params = normalize_workflow_params(case["template"], case["params"])
        wf_id = await workflow_engine.create_new_workflow(
            case["template"] if case["template"] != "paper_writing" else (
                "paper_writing_zh" if case["params"].get("language") == "zh" else "paper_writing"
            ),
            case["title"],
            params,
            case.get("enable_checkpoints", False),
        )
        workspace = workflow_engine.WORKSPACES_DIR / wf_id
        if case.get("upload_role"):
            _seed_upload(
                workspace,
                case["upload_role"],
                case["upload_name"],
                case["upload_bytes"],
            )
            # Touch a deliverable-like artifact so export has content.
            (workspace / "README.md").write_text(
                f"# {case['title']}\nfamily={case['family']}\n", encoding="utf-8"
            )
        else:
            (workspace / "README.md").write_text(
                f"# {case['title']}\nfamily={case['family']}\n", encoding="utf-8"
            )

        db = await state_store._get_db()
        try:
            row = await state_store.get_workflow(db, wf_id)
        finally:
            await db.close()

        exported = await state_store.export_workflow_data(wf_id)
        return wf_id, row, exported, workspace

    wf_id, row, exported, workspace = asyncio.run(exercise())
    assert row is not None
    stored_params = json.loads(row["params"]) if isinstance(row["params"], str) else row["params"]
    for key, value in case["params"].items():
        # Defaults / canonicalization may adjust some fields; ensure non-discard.
        assert key in stored_params, f"{case['family']} lost param {key}"
        if key not in {"language"}:  # competition language is forced by template
            assert stored_params[key] == value or key in {
                "skip_improvement_loop",
                "paper_branch",
            }

    assert exported is not None
    assert exported["workflow"]["id"] == wf_id
    assert exported["workflow"]["title"] == case["title"]
    assert (workspace / "README.md").is_file()

    # Build export zip through the same helper the router uses.
    from routers.workflows import _build_export_zip

    zip_path = root / f"{case['family']}.zip"
    _build_export_zip(str(zip_path), wf_id, workspace, exported)
    assert zip_path.stat().st_size > 0
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert any(name.startswith("workspace/") for name in names)


def test_http_create_catalog_export_contract(tmp_path, monkeypatch):
    """In-process contract for create/params/export/secrets (no background-task theatre).

    Full start→running→pause→checkpoint transitions are covered by
    ``tests/test_real_uvicorn_lifecycle.py`` against a real uvicorn process.
    """
    import config
    import services.secret_store as secret_store
    import services.state_store as state_store
    import services.workflow_engine as workflow_engine
    import routers.workflows as workflows_router
    from fastapi.testclient import TestClient
    from services.local_session import TOKEN_ENV, TOKEN_HEADER

    token = "surface-parity-session"
    monkeypatch.setenv(TOKEN_ENV, token)
    monkeypatch.setenv("VIBE_DESKTOP", "1")
    monkeypatch.setenv("VIBE_USER_DATA_ROOT", str(tmp_path / "user-data"))
    state_store.DB_PATH = tmp_path / "http-lifecycle.db"
    workspaces = tmp_path / "workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    for module in (config, workflow_engine, workflows_router):
        monkeypatch.setattr(module, "WORKSPACES_DIR", workspaces)
    monkeypatch.setattr(
        secret_store,
        "_default_store",
        secret_store.SecretStore(tmp_path / "secrets.json", b"http-lifecycle-key-material!"),
    )

    asyncio.run(state_store.init_db())
    from main import app

    client = TestClient(app)
    client.headers.update({TOKEN_HEADER: token})

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    catalog = client.get("/api/workflows/catalog")
    assert catalog.status_code == 200
    body = catalog.json()
    assert "families" in body
    assert "competition" in body["families"]
    assert "comp_tianfu" in body["families"]["competition"]

    created_ids: list[str] = []
    for case in FAMILY_CASES:
        payload = {
            "template": case["template"],
            "title": case["title"],
            "params": case["params"],
            "enable_checkpoints": case.get("enable_checkpoints", False),
        }
        response = client.post("/api/workflows", json=payload)
        assert response.status_code == 200, (case["family"], response.text)
        data = response.json()
        assert data["ok"] is True
        wf_id = data["id"]
        created_ids.append(wf_id)

        detail = client.get(f"/api/workflows/{wf_id}")
        assert detail.status_code == 200
        wf = detail.json()
        assert wf["title"] == case["title"]
        assert isinstance(wf["params"], dict)
        for key in case["params"]:
            assert key in wf["params"], f"{case['family']} API lost {key}"

        workspace = workflow_engine.WORKSPACES_DIR / wf_id
        if case.get("upload_role"):
            _seed_upload(
                workspace,
                case["upload_role"],
                case["upload_name"],
                case["upload_bytes"],
            )
        else:
            (workspace / "user_data").mkdir(parents=True, exist_ok=True)

        if case["template"] == "paper_from_assets":
            manifest = workspace / "user_data" / "_input_manifest.json"
            assert manifest.is_file()
            backup = manifest.read_text(encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            bad = client.post(f"/api/workflows/{wf_id}/start")
            assert bad.status_code == 400, bad.text
            manifest.write_text(backup, encoding="utf-8")
            _seed_upload(
                workspace,
                case["upload_role"],
                case["upload_name"],
                case["upload_bytes"],
            )

        (workspace / "EXPORT_MARKER.md").write_text("export-me", encoding="utf-8")
        export = client.get(f"/api/workflows/{wf_id}/export")
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("application/zip") or export.content[:2] == b"PK"
        assert len(export.content) > 32

    listing = client.get("/api/workflows")
    assert listing.status_code == 200
    listed_ids = {item["id"] for item in listing.json()}
    assert set(created_ids).issubset(listed_ids)

    client.put(
        "/api/settings",
        json={"settings": {"executor_api_key": "should-not-leak-in-get", "theme": "dark"}},
    )
    settings = client.get("/api/settings").json()
    assert settings["executor_api_key"] == {"configured": True}
    assert "should-not-leak-in-get" not in json.dumps(settings)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http(port: int, token: str, path: str, method: str = "GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={
            "X-Vibe-Session-Token": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        payload = error.read().decode("utf-8")
        try:
            return error.code, json.loads(payload)
        except Exception:
            return error.code, {"raw": payload}


def test_real_run_py_entry_launches_twice(tmp_path):
    """Launch the real backend entry path twice with health + catalog/create."""
    python = ROOT / "runtime" / "python" / "python.exe"
    if not python.is_file():
        python = Path(sys.executable)

    token = "launch-parity-token"
    evidence = []
    for attempt in (1, 2):
        port = _free_port()
        appdata = tmp_path / f"appdata-{attempt}"
        appdata.mkdir()
        env = {
            **os.environ,
            "PYTHONPATH": str(BACKEND),
            "VIBE_LOCAL_SESSION_TOKEN": token,
            "VIBE_DESKTOP": "1",
            "VIBE_USER_DATA_ROOT": str(appdata / "user-data"),
            "APPDATA": str(appdata),
            "API_PORT": str(port),
            "PYTHONUTF8": "1",
        }
        process = subprocess.Popen(
            [
                str(python),
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=str(BACKEND),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            ready = False
            for _ in range(80):
                try:
                    status, health = _http(port, token, "/api/health")
                    if status == 200 and health.get("status") == "ok":
                        ready = True
                        break
                except Exception:
                    time.sleep(0.1)
            assert ready, f"launch {attempt} failed to become healthy"

            status, catalog = _http(port, token, "/api/workflows/catalog")
            assert status == 200
            assert "families" in catalog
            assert "competition" in catalog["families"]
            assert len(catalog["families"]["competition"]) >= 20

            status, created = _http(
                port,
                token,
                "/api/workflows",
                "POST",
                {
                    "template": "idea_discovery",
                    "title": f"launch-{attempt}-idea",
                    "params": {"skip_improvement_loop": True},
                    "enable_checkpoints": False,
                },
            )
            assert status == 200, created
            assert created.get("ok") is True
            assert created.get("id")
            evidence.append(
                {
                    "attempt": attempt,
                    "port": port,
                    "health": health,
                    "catalog_family_count": {k: len(v) for k, v in catalog["families"].items()},
                    "created": created,
                }
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()

    assert len(evidence) == 2
    assert evidence[0]["health"]["status"] == evidence[1]["health"]["status"] == "ok"
    # Persist for the goal harness under the caller's SCRATCH when available.
    scratch = os.environ.get("GROK_GOAL_SCRATCH") or os.environ.get("SCRATCH")
    if scratch:
        Path(scratch).mkdir(parents=True, exist_ok=True)
        (Path(scratch) / "launch-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )

def test_skip_analysis_explicit_override_when_figures_disabled():
    """skip_figures no longer clobbers an explicit skip_analysis=False."""
    from services.workflow_options import normalize_workflow_params

    implicit = normalize_workflow_params("paper_from_assets", {"skip_figures": True})
    assert implicit["skip_analysis"] is True
    explicit = normalize_workflow_params(
        "paper_from_assets",
        {"skip_figures": True, "skip_analysis": False},
    )
    assert explicit["skip_analysis"] is False
