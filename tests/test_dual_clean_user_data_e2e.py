"""Two clean user-data roots via real uvicorn processes must both persist artifacts."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "python" / "python.exe"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(
    port: int,
    token: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    *,
    raw: bool = False,
):
    data = json.dumps(body).encode("utf-8") if body is not None else None
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
        with urlopen(req, timeout=30) as response:
            payload = response.read()
            if raw:
                return response.status, payload
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError as error:
        payload = error.read()
        if raw:
            return error.code, payload
        text = payload.decode("utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {"detail": text}
        return error.code, parsed


def _server(port: int, token: str, user_data: Path) -> subprocess.Popen:
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "VIBE_LOCAL_SESSION_TOKEN": token,
        "VIBE_DESKTOP": "1",
        "VIBE_USER_DATA_ROOT": str(user_data),
        "VIBE_RUNTIME_ROOT": str(ROOT / "runtime"),
        "API_PORT": str(port),
        "PYTHONUTF8": "1",
    }
    process = subprocess.Popen(
        [
            str(PYTHON),
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
        cwd=str(ROOT / "backend"),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    for _ in range(80):
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    raise AssertionError(f"backend failed to start for {user_data}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(15)
    except subprocess.TimeoutExpired:
        process.kill()


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-{label}"
    user.mkdir(parents=True)
    token = f"dual-clean-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, health = _request(port, token, "/api/health")
        assert status == 200 and health.get("status") == "ok", health

        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Dual clean {label}",
                "research_question": "Do two clean user-data roots both persist artifacts?",
                "inclusion_criteria": "peer reviewed",
            },
        )
        assert status == 200, project

        status, workflow = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "idea_discovery",
                "title": f"Clean E2E {label} 路径",
                "params": {"topic": f"dual-clean-{label}"},
                "enable_checkpoints": True,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]

        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert user.resolve() in workspace.resolve().parents or str(user.resolve()) in str(workspace.resolve())

        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {
                "path": "paper/main.md",
                "content": f"# Dual Clean {label}\n\nUnicode 路径 dual-process evidence.\n",
            },
        )
        assert status == 200, saved

        status, stats = _request(port, token, f"/api/editor/{wf_id}/stats?path=paper/main.md")
        assert status == 200, stats

        status, artifacts = _request(port, token, f"/api/workflows/{wf_id}/artifacts")
        assert status == 200, artifacts

        status, ops = _request(port, token, "/api/workflows/operations")
        assert status == 200, ops

        status, executor = _request(port, token, "/api/settings/test/executor", "POST")
        assert status == 200, executor
        assert executor.get("ok") is False
        assert "密钥" in str(executor.get("message") or "") or "key" in str(executor.get("message") or "").lower()

        status, assurance = _request(port, token, f"/api/research-projects/{project['id']}/assurance")
        assert status == 200, assurance
        assurance_http = status

        # Export must open the durable workspace_dir (not a rebound process root).
        status, export_bytes = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True)
        assert status == 200, export_bytes[:200]
        assert isinstance(export_bytes, (bytes, bytearray))
        assert export_bytes[:2] == b"PK"  # ZIP magic

        md = workspace / "paper" / "main.md"
        assert md.is_file(), md
        text = md.read_text(encoding="utf-8")
        assert f"Dual Clean {label}" in text
        assert any(ord(ch) > 127 for ch in str(workspace))

        # --- Host paper-slides chain (UI→API→host executor→artifacts→export) ---
        status, slides_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "paper_slides",
                "title": f"Slides clean {label}",
                "params": {"venue": "ICML", "talk_type": "spotlight", "minutes": 8},
                "enable_checkpoints": True,
                "project_id": project["id"],
            },
        )
        assert status == 200, slides_wf
        slides_id = slides_wf["id"]
        status, slides_detail = _request(port, token, f"/api/workflows/{slides_id}")
        assert status == 200, slides_detail
        slides_ws = Path(slides_detail["workspace_dir"])
        paper_body = (
            f"# Dual Clean Slides {label}\n\n"
            "## Motivation\n- Auditable dual-clean roots\n\n"
            "## Method\n- Host beamer + PPTX builder\n\n"
            "## Results\n- Real PDF and lineage\n"
        )
        status, _ = _request(
            port,
            token,
            f"/api/editor/{slides_id}/file",
            "PUT",
            {"path": "paper/main.md", "content": paper_body},
        )
        assert status == 200
        status, _ = _request(
            port,
            token,
            f"/api/editor/{slides_id}/file",
            "PUT",
            {
                "path": "paper/main.tex",
                "content": (
                    "\\documentclass{article}\n"
                    f"\\title{{Dual Clean Slides {label}}}\n"
                    "\\author{Vibe Research}\n"
                    "\\begin{document}\n\\maketitle\n"
                    "\\section{Motivation} Auditable dual-clean roots.\n"
                    "\\section{Method} Host beamer and PPTX builder.\n"
                    "\\section{Results} Real PDF and lineage.\n"
                    "\\end{document}\n"
                ),
            },
        )
        assert status == 200

        status, started = _request(port, token, f"/api/workflows/{slides_id}/start", "POST")
        assert status == 200, started

        terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
        final_status = "running"
        for _ in range(120):
            status, detail = _request(port, token, f"/api/workflows/{slides_id}")
            assert status == 200, detail
            final_status = str(detail.get("status") or "")
            if final_status in terminal:
                break
            time.sleep(0.5)
        assert final_status in terminal, final_status

        if final_status == "waiting_checkpoint":
            status, cp = _request(
                port,
                token,
                f"/api/workflows/{slides_id}/checkpoint",
                "POST",
                {"action": "approve", "data": {"feedback": "dual-clean approve"}},
            )
            assert status == 200, cp
            for _ in range(40):
                status, detail = _request(port, token, f"/api/workflows/{slides_id}")
                assert status == 200, detail
                final_status = str(detail.get("status") or "")
                if final_status in {"completed", "failed"}:
                    break
                time.sleep(0.25)

        pdf = slides_ws / "slides" / "main.pdf"
        pptx = slides_ws / "slides" / "presentation.pptx"
        lineage = slides_ws / ".host_builds" / "paper-slides.json"
        assert pdf.is_file() and pdf.stat().st_size >= 500, pdf
        assert pptx.is_file() and pptx.stat().st_size >= 500, pptx
        assert lineage.is_file(), lineage
        lineage_payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert lineage_payload.get("skill_name") == "paper-slides"
        assert lineage_payload.get("executor") == "host_step_runner"
        assert final_status in {"completed", "waiting_checkpoint"} or pdf.is_file()

        # Product surface: GET /artifacts must list workspace deliverables, not only uploads/.
        status, slides_artifacts = _request(port, token, f"/api/workflows/{slides_id}/artifacts")
        assert status == 200, slides_artifacts
        slides_paths = {
            str(item.get("path") or "").replace("\\", "/")
            for item in (slides_artifacts or [])
            if isinstance(item, dict)
        }
        assert "slides/main.pdf" in slides_paths, slides_paths
        assert "slides/presentation.pptx" in slides_paths, slides_paths
        assert not any(p.startswith("_tmp/") for p in slides_paths), slides_paths

        # Recovery endpoint must accept a durable request (no silent 501).
        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{slides_id}/recover",
            "POST",
            {"reason": "dual-clean recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        status, slides_export = _request(port, token, f"/api/workflows/{slides_id}/export", raw=True)
        assert status == 200, slides_export[:200]
        assert slides_export[:2] == b"PK"
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(slides_export)) as archive:
            names = archive.namelist()
            assert any(n.replace("\\", "/").endswith("slides/main.pdf") for n in names), names[:20]
            assert any(n.replace("\\", "/").endswith("slides/presentation.pptx") for n in names), names[:20]

        # --- Host paper-poster chain (UI→API→host executor→artifacts→export) ---
        status, poster_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "paper_poster",
                "title": f"Poster clean {label}",
                "params": {
                    "venue": "NeurIPS",
                    "size": "A1",
                    "orientation": "landscape",
                    "columns": 3,
                },
                "enable_checkpoints": True,
                "project_id": project["id"],
            },
        )
        assert status == 200, poster_wf
        poster_id = poster_wf["id"]
        status, poster_detail = _request(port, token, f"/api/workflows/{poster_id}")
        assert status == 200, poster_detail
        poster_ws = Path(poster_detail["workspace_dir"])
        poster_body = (
            f"# Dual Clean Poster {label}\n\n"
            "## Background\n- Conference posters need visual-first summaries\n\n"
            "## Approach\n- Host A0/A1 builder + editable PPTX\n\n"
            "## Findings\n- Dual-clean Unicode roots persist lineage\n"
        )
        status, _ = _request(
            port,
            token,
            f"/api/editor/{poster_id}/file",
            "PUT",
            {"path": "paper/main.md", "content": poster_body},
        )
        assert status == 200
        status, _ = _request(
            port,
            token,
            f"/api/editor/{poster_id}/file",
            "PUT",
            {
                "path": "paper/main.tex",
                "content": (
                    "\\documentclass{article}\n"
                    f"\\title{{Dual Clean Poster {label}}}\n"
                    "\\author{Vibe Research}\n"
                    "\\begin{document}\n\\maketitle\n"
                    "\\section{Background} Visual-first conference posters.\n"
                    "\\section{Approach} Host A1 landscape poster builder.\n"
                    "\\section{Findings} Dual-clean Unicode roots persist lineage.\n"
                    "\\end{document}\n"
                ),
            },
        )
        assert status == 200

        status, started = _request(port, token, f"/api/workflows/{poster_id}/start", "POST")
        assert status == 200, started

        poster_final = "running"
        for _ in range(120):
            status, detail = _request(port, token, f"/api/workflows/{poster_id}")
            assert status == 200, detail
            poster_final = str(detail.get("status") or "")
            if poster_final in terminal:
                break
            time.sleep(0.5)
        assert poster_final in terminal, poster_final

        if poster_final == "waiting_checkpoint":
            status, cp = _request(
                port,
                token,
                f"/api/workflows/{poster_id}/checkpoint",
                "POST",
                {"action": "approve", "data": {"feedback": "dual-clean poster approve"}},
            )
            assert status == 200, cp
            for _ in range(40):
                status, detail = _request(port, token, f"/api/workflows/{poster_id}")
                assert status == 200, detail
                poster_final = str(detail.get("status") or "")
                if poster_final in {"completed", "failed"}:
                    break
                time.sleep(0.25)

        poster_pdf = poster_ws / "poster" / "main.pdf"
        poster_pptx = poster_ws / "poster" / "poster.pptx"
        poster_lineage = poster_ws / ".host_builds" / "paper-poster.json"
        assert poster_pdf.is_file() and poster_pdf.stat().st_size >= 500, poster_pdf
        assert poster_pptx.is_file() and poster_pptx.stat().st_size >= 500, poster_pptx
        assert poster_lineage.is_file(), poster_lineage
        poster_lineage_payload = json.loads(poster_lineage.read_text(encoding="utf-8"))
        assert poster_lineage_payload.get("skill_name") == "paper-poster"
        assert poster_lineage_payload.get("executor") == "host_step_runner"
        assert poster_final in {"completed", "waiting_checkpoint"} or poster_pdf.is_file()

        status, poster_artifacts = _request(port, token, f"/api/workflows/{poster_id}/artifacts")
        assert status == 200, poster_artifacts
        poster_paths = {
            str(item.get("path") or "").replace("\\", "/")
            for item in (poster_artifacts or [])
            if isinstance(item, dict)
        }
        assert "poster/main.pdf" in poster_paths, poster_paths
        assert "poster/poster.pptx" in poster_paths, poster_paths

        poster_recover_status, poster_recover = _request(
            port,
            token,
            f"/api/workflows/{poster_id}/recover",
            "POST",
            {"reason": "dual-clean poster recovery probe", "requested_by": "test"},
        )
        assert poster_recover_status in {200, 202, 409}, poster_recover

        status, poster_export = _request(port, token, f"/api/workflows/{poster_id}/export", raw=True)
        assert status == 200, poster_export[:200]
        assert poster_export[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(poster_export)) as archive:
            names = archive.namelist()
            assert any(n.replace("\\", "/").endswith("poster/main.pdf") for n in names), names[:20]
            assert any(n.replace("\\", "/").endswith("poster/poster.pptx") for n in names), names[:20]

        return {
            "label": label,
            "project_id": project["id"],
            "workflow_id": wf_id,
            "slides_workflow_id": slides_id,
            "poster_workflow_id": poster_id,
            "workspace_dir": str(workspace),
            "slides_workspace_dir": str(slides_ws),
            "poster_workspace_dir": str(poster_ws),
            "artifact_exists": True,
            "slides_pdf_bytes": pdf.stat().st_size,
            "slides_pptx_bytes": pptx.stat().st_size,
            "poster_pdf_bytes": poster_pdf.stat().st_size,
            "poster_pptx_bytes": poster_pptx.stat().st_size,
            "slides_lineage": True,
            "poster_lineage": True,
            "executor_honest_fail": True,
            "export_ok": True,
            "slides_export_ok": True,
            "poster_export_ok": True,
            "recovery_status": recover_status,
            "poster_recovery_status": poster_recover_status,
            "assurance_status": assurance_http,
            "slides_final_status": final_status,
            "poster_final_status": poster_final,
        }
    finally:
        _stop(process)


def test_dual_clean_user_data_roots_persist_independent_artifacts(tmp_path):
    base = tmp_path / "dual-clean"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["artifact_exists"] and run2["artifact_exists"]
    assert run1["workflow_id"] != run2["workflow_id"]
    assert run1["slides_workflow_id"] != run2["slides_workflow_id"]
    assert run1["poster_workflow_id"] != run2["poster_workflow_id"]
    assert Path(run1["workspace_dir"]).is_dir()
    assert Path(run2["workspace_dir"]).is_dir()
    assert Path(run1["workspace_dir"]).resolve() != Path(run2["workspace_dir"]).resolve()
    assert Path(run1["slides_workspace_dir"]).resolve() != Path(run2["slides_workspace_dir"]).resolve()
    assert Path(run1["poster_workspace_dir"]).resolve() != Path(run2["poster_workspace_dir"]).resolve()
    assert run1["slides_pdf_bytes"] >= 500 and run2["slides_pdf_bytes"] >= 500
    assert run1["slides_pptx_bytes"] >= 500 and run2["slides_pptx_bytes"] >= 500
    assert run1["poster_pdf_bytes"] >= 500 and run2["poster_pdf_bytes"] >= 500
    assert run1["poster_pptx_bytes"] >= 500 and run2["poster_pptx_bytes"] >= 500
    assert run1["slides_lineage"] and run2["slides_lineage"]
    assert run1["poster_lineage"] and run2["poster_lineage"]
    assert run1["slides_export_ok"] and run2["slides_export_ok"]
    assert run1["poster_export_ok"] and run2["poster_export_ok"]
    # Roots must not share workspace trees.
    assert "用户数据-1" in run1["workspace_dir"].replace("/", "\\") or "用户数据-1" in run1["workspace_dir"]
    assert "用户数据-2" in run2["workspace_dir"].replace("/", "\\") or "用户数据-2" in run2["workspace_dir"]
