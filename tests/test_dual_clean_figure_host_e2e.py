"""Dual Unicode user-data roots: paper-figure-html host chain with real PDF lineage."""
from __future__ import annotations

import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
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
    timeout: int = 60,
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
        with urlopen(req, timeout=timeout) as response:
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


def _wait_terminal(port: int, token: str, wf_id: str, seconds: int = 180) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    last: dict = {}
    for _ in range(max(1, seconds * 2)):
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        last = detail
        if str(detail.get("status") or "") in terminal:
            return detail
        time.sleep(0.5)
    return last


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-图-{label}"
    user.mkdir(parents=True)
    token = f"dual-fig-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"Figure dual clean {label}",
                "research_question": "Do dual-clean roots render HTML figures with lineage?",
                "inclusion_criteria": "host renderer only",
            },
        )
        assert status == 200, project

        # thesis_proposal includes paper-figure-drawio → remapped to paper-figure-html
        status, workflow = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "thesis_proposal",
                "title": f"开题技术路线图-{label}",
                "params": {
                    "degree_level": "phd",
                    "topic": f"证据原生科研Agent dual-clean {label}",
                    "skip_drawio": False,
                    "flowchart_engine": "html",
                    "skip_figures": True,
                    "skip_analysis": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                },
                "enable_checkpoints": False,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(workspace))

        # Pre-seed an explicit HTML figure so the host renderer has a source.
        html_body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px}"
            ".box{border:2px solid #111;border-radius:8px;padding:12px 16px;display:inline-block}"
            ".arrow{font-size:22px;margin:0 8px}</style></head><body>"
            f"<h2>Dual Clean Roadmap {label}</h2>"
            "<div class='box'>Question</div><span class='arrow'>→</span>"
            "<div class='box'>Evidence</div><span class='arrow'>→</span>"
            "<div class='box'>Claim</div></body></html>\n"
        )
        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": "figures/fig_roadmap.html", "content": html_body},
        )
        assert status == 200, saved

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _wait_terminal(port, token, wf_id, seconds=240)
        assert final.get("status") == "completed", final

        pdf = workspace / "figures" / "fig_roadmap.pdf"
        include = workspace / "figures" / "latex_includes.tex"
        lineage = workspace / ".host_builds" / "paper-figure-html.json"
        proposal = workspace / "PROPOSAL.md"
        docx = workspace / "PROPOSAL.docx"
        assert proposal.is_file() and proposal.stat().st_size >= 200, proposal
        assert pdf.is_file() and pdf.stat().st_size >= 500, pdf
        assert pdf.read_bytes()[:4] == b"%PDF"
        assert include.is_file()
        assert lineage.is_file(), lineage
        lineage_payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert lineage_payload.get("skill_name") == "paper-figure-html"
        assert lineage_payload.get("executor") == "host_step_runner"
        assert docx.is_file() and docx.stat().st_size >= 1000, docx

        # Export must include the rendered figure PDF.
        status, export_bytes = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True)
        assert status == 200, export_bytes[:200]
        assert export_bytes[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
            names = archive.namelist()
            assert any(n.replace("\\", "/").endswith("figures/fig_roadmap.pdf") for n in names), names[:30]
            # Lineage lives under workspace .host_builds (may be export-filtered);
            # durable proof is the on-disk lineage file asserted above.
            assert lineage.is_file()

        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{wf_id}/recover",
            "POST",
            {"reason": "dual-clean figure recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        return {
            "label": label,
            "workflow_id": wf_id,
            "workspace_dir": str(workspace),
            "pdf_bytes": pdf.stat().st_size,
            "lineage": True,
            "export_ok": True,
            "recovery_status": recover_status,
        }
    finally:
        _stop(process)


def test_dual_clean_figure_html_host_roots(tmp_path):
    base = tmp_path / "dual-clean-fig"
    base.mkdir()
    run1 = _clean_run("1", base)
    run2 = _clean_run("2", base)
    assert run1["workflow_id"] != run2["workflow_id"]
    assert Path(run1["workspace_dir"]).resolve() != Path(run2["workspace_dir"]).resolve()
    assert run1["pdf_bytes"] >= 500 and run2["pdf_bytes"] >= 500
    assert run1["lineage"] and run2["lineage"]
    assert run1["export_ok"] and run2["export_ok"]
    assert "用户数据-图-1" in run1["workspace_dir"] or "用户数据-图-1" in run1["workspace_dir"].replace("/", "\\")
    assert "用户数据-图-2" in run2["workspace_dir"] or "用户数据-图-2" in run2["workspace_dir"].replace("/", "\\")


def _clean_run_drawio(label: str, base: Path) -> dict:
    """thesis_proposal with flowchart_engine=drawio under dual Unicode roots."""
    user = base / f"用户数据-DrawIO-{label}"
    user.mkdir(parents=True)
    token = f"dual-drawio-{label}"
    port = _free_port()
    process = _server(port, token, user)
    try:
        status, project = _request(
            port,
            token,
            "/api/research-projects",
            "POST",
            {
                "title": f"DrawIO dual clean {label}",
                "research_question": "Do dual-clean roots export DrawIO figures?",
                "inclusion_criteria": "host draw.io runtime",
            },
        )
        assert status == 200, project

        status, workflow = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "thesis_proposal",
                "title": f"DrawIO路线图-{label}",
                "params": {
                    "degree_level": "phd",
                    "topic": f"DrawIO dual-clean {label}",
                    "skip_drawio": False,
                    "flowchart_engine": "drawio",
                    "skip_figures": True,
                    "skip_analysis": True,
                    "skip_improvement_loop": True,
                    "output_format": "docx",
                },
                "enable_checkpoints": False,
                "project_id": project["id"],
            },
        )
        assert status == 200, workflow
        wf_id = workflow["id"]
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        workspace = Path(detail["workspace_dir"])
        assert any(ord(ch) > 127 for ch in str(workspace))

        drawio_src = (
            '<mxfile host="vibe-research"><diagram id="1" name="Page-1">'
            "<mxGraphModel><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/>"
            "<mxCell id=\"2\" value=\"Question\" style=\"rounded=1;whiteSpace=wrap;html=1;\" "
            "vertex=\"1\" parent=\"1\"><mxGeometry x=\"40\" y=\"40\" width=\"110\" height=\"48\" as=\"geometry\"/>"
            "</mxCell><mxCell id=\"3\" value=\"Evidence\" style=\"rounded=1;whiteSpace=wrap;html=1;\" "
            "vertex=\"1\" parent=\"1\"><mxGeometry x=\"200\" y=\"40\" width=\"110\" height=\"48\" as=\"geometry\"/>"
            "</mxCell><mxCell id=\"4\" value=\"Claim\" style=\"rounded=1;whiteSpace=wrap;html=1;\" "
            "vertex=\"1\" parent=\"1\"><mxGeometry x=\"360\" y=\"40\" width=\"100\" height=\"48\" as=\"geometry\"/>"
            "</mxCell><mxCell id=\"5\" style=\"endArrow=classic;html=1;\" edge=\"1\" parent=\"1\" "
            "source=\"2\" target=\"3\"><mxGeometry relative=\"1\" as=\"geometry\"/></mxCell>"
            "<mxCell id=\"6\" style=\"endArrow=classic;html=1;\" edge=\"1\" parent=\"1\" "
            "source=\"3\" target=\"4\"><mxGeometry relative=\"1\" as=\"geometry\"/></mxCell>"
            "</root></mxGraphModel></diagram></mxfile>\n"
        )
        status, saved = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": "figures/fig_roadmap.drawio", "content": drawio_src},
        )
        assert status == 200, saved

        status, started = _request(port, token, f"/api/workflows/{wf_id}/start", "POST")
        assert status == 200, started
        final = _wait_terminal(port, token, wf_id, seconds=300)
        assert final.get("status") == "completed", final

        pdf = workspace / "figures" / "fig_roadmap.pdf"
        lineage = workspace / ".host_builds" / "paper-figure-drawio.json"
        assert pdf.is_file() and pdf.stat().st_size >= 200, pdf
        assert lineage.is_file(), lineage
        payload = json.loads(lineage.read_text(encoding="utf-8"))
        assert payload.get("skill_name") == "paper-figure-drawio"
        assert payload.get("executor") == "host_step_runner"

        status, export_bytes = _request(port, token, f"/api/workflows/{wf_id}/export", raw=True)
        assert status == 200
        assert export_bytes[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_bytes)) as archive:
            names = archive.namelist()
            assert any(n.replace("\\", "/").endswith("figures/fig_roadmap.pdf") for n in names), names[:30]

        return {
            "label": label,
            "workflow_id": wf_id,
            "workspace_dir": str(workspace),
            "pdf_bytes": pdf.stat().st_size,
            "lineage": True,
            "export_ok": True,
        }
    finally:
        _stop(process)


def test_dual_clean_figure_drawio_host_roots(tmp_path):
    drawio_bin = ROOT / "runtime" / "draw.io" / "draw.io.exe"
    if not drawio_bin.is_file():
        import pytest

        pytest.skip("runtime draw.io binary missing")
    base = tmp_path / "dual-clean-drawio"
    base.mkdir()
    run1 = _clean_run_drawio("1", base)
    run2 = _clean_run_drawio("2", base)
    assert run1["workflow_id"] != run2["workflow_id"]
    assert Path(run1["workspace_dir"]).resolve() != Path(run2["workspace_dir"]).resolve()
    assert run1["pdf_bytes"] >= 200 and run2["pdf_bytes"] >= 200
    assert run1["lineage"] and run2["lineage"]
    assert run1["export_ok"] and run2["export_ok"]
    assert "用户数据-DrawIO-1" in run1["workspace_dir"]
    assert "用户数据-DrawIO-2" in run2["workspace_dir"]
