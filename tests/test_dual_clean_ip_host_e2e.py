"""Dual Unicode user-data roots: patent/copyright/software-copyright host full chains."""
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
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(100):
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"backend exited early for {user_data}: {out[-4000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    out = ""
    try:
        process.kill()
        out = process.stdout.read() if process.stdout else ""
    except Exception:
        pass
    raise AssertionError(f"backend failed to start for {user_data}: {out[-4000:]}")


def _stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(20)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_terminal(port: int, token: str, wf_id: str, *, seconds: float = 180.0) -> dict:
    terminal = {"completed", "failed", "waiting_checkpoint", "paused"}
    deadline = time.time() + seconds
    detail = {}
    while time.time() < deadline:
        status, detail = _request(port, token, f"/api/workflows/{wf_id}")
        assert status == 200, detail
        if str(detail.get("status") or "") in terminal:
            return detail
        time.sleep(0.4)
    raise AssertionError(f"workflow {wf_id} did not reach terminal state: {detail}")


def _seed_code(port: int, token: str, wf_id: str, label: str) -> None:
    """Seed both product code and user_data inputs (start validation for soft copyright)."""
    py_body = (
        f"# dual-clean {label}\n"
        "def pipeline():\n"
        "    return {'ok': True, 'label': %r}\n" % label
    )
    ts_body = f"export const label = '{label}';\nexport function run() {{ return label; }}\n"
    for path, content in (
        ("code/main.py", py_body),
        ("code/service.ts", ts_body),
        # software_copyright start gate requires observable files under user_data/
        ("user_data/main.py", py_body),
        ("user_data/README.md", f"# {label}\n\nDual-clean host IP seed.\n"),
    ):
        status, payload = _request(
            port,
            token,
            f"/api/editor/{wf_id}/file",
            "PUT",
            {"path": path, "content": content},
        )
        assert status == 200, (path, payload)


def _clean_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-IP-{label}"
    user.mkdir(parents=True)
    token = f"dual-ip-{label}"
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
                "title": f"IP 双干净 {label}",
                "research_question": "Do dual-clean roots complete host IP draft/build chains?",
                "inclusion_criteria": "host executor artifacts with lineage",
            },
        )
        assert status == 200, project
        project_id = project["id"]

        # --- patent_disclosure: draft(host) -> build(host) ---
        status, patent_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "patent_disclosure",
                "title": f"一种可审计科研执行方法-{label}",
                "params": {"problem": "缺少产物血缘与诚实失败"},
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, patent_wf
        patent_id = patent_wf["id"]
        status, patent_detail = _request(port, token, f"/api/workflows/{patent_id}")
        assert status == 200, patent_detail
        patent_ws = Path(patent_detail["workspace_dir"])
        _seed_code(port, token, patent_id, f"patent-{label}")

        status, started = _request(port, token, f"/api/workflows/{patent_id}/start", "POST")
        assert status == 200, started
        patent_final = _wait_terminal(port, token, patent_id, seconds=240)
        assert patent_final["status"] == "completed", patent_final
        patent_docx = patent_ws / "专利交底书" / "交底书.docx"
        patent_draft = patent_ws / "专利交底书" / "交底书草稿.md"
        patent_lineage_draft = patent_ws / ".host_builds" / "patent-draft.json"
        patent_lineage_build = patent_ws / ".host_builds" / "patent-build.json"
        assert patent_draft.is_file() and patent_draft.stat().st_size >= 500
        assert patent_docx.is_file() and patent_docx.stat().st_size >= 1000
        assert patent_lineage_draft.is_file() and patent_lineage_build.is_file()
        assert json.loads(patent_lineage_build.read_text(encoding="utf-8"))["executor"] == "host_step_runner"
        with zipfile.ZipFile(patent_docx) as archive:
            assert "word/document.xml" in archive.namelist()

        # --- copyright_material: draft(host) -> build(host) ---
        status, copyright_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "copyright_material",
                "title": f"Vibe双干净软著-{label}",
                "params": {"software_name": f"Vibe双干净软著-{label}", "software_version": "V1.0"},
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, copyright_wf
        copyright_id = copyright_wf["id"]
        status, copyright_detail = _request(port, token, f"/api/workflows/{copyright_id}")
        assert status == 200, copyright_detail
        copyright_ws = Path(copyright_detail["workspace_dir"])
        _seed_code(port, token, copyright_id, f"copyright-{label}")

        status, started = _request(port, token, f"/api/workflows/{copyright_id}/start", "POST")
        assert status == 200, started
        copyright_final = _wait_terminal(port, token, copyright_id, seconds=240)
        assert copyright_final["status"] == "completed", copyright_final
        formal = copyright_ws / "软件著作权申请资料" / "正式资料"
        assert formal.is_dir()
        assert (formal / "申请表信息.txt").is_file()
        assert any(path.suffix.lower() == ".docx" for path in formal.glob("*.docx"))
        assert (copyright_ws / ".host_builds" / "copyright-draft.json").is_file()
        assert (copyright_ws / ".host_builds" / "copyright-build.json").is_file()

        # --- software_copyright: host inventory four-pack ---
        status, soft_wf = _request(
            port,
            token,
            "/api/workflows",
            "POST",
            {
                "template": "software_copyright",
                "title": f"软著清点-{label}",
                "params": {"software_name": f"软著清点-{label}", "software_version": "V3.0"},
                "enable_checkpoints": False,
                "project_id": project_id,
            },
        )
        assert status == 200, soft_wf
        soft_id = soft_wf["id"]
        status, soft_detail = _request(port, token, f"/api/workflows/{soft_id}")
        assert status == 200, soft_detail
        soft_ws = Path(soft_detail["workspace_dir"])
        _seed_code(port, token, soft_id, f"soft-{label}")

        status, started = _request(port, token, f"/api/workflows/{soft_id}/start", "POST")
        assert status == 200, started
        soft_final = _wait_terminal(port, token, soft_id, seconds=120)
        # may wait checkpoint if enable forced; we disabled checkpoints
        assert soft_final["status"] in {"completed", "waiting_checkpoint"}, soft_final
        if soft_final["status"] == "waiting_checkpoint":
            status, cp = _request(
                port,
                token,
                f"/api/workflows/{soft_id}/checkpoint",
                "POST",
                {"action": "approve", "data": {"feedback": "dual-clean soft approve"}},
            )
            assert status == 200, cp
            soft_final = _wait_terminal(port, token, soft_id, seconds=60)
        for name in (
            "PRODUCT_OVERVIEW.md",
            "USER_MANUAL.md",
            "SOURCE_CODE_INDEX.md",
            "REGISTRATION_CHECKLIST.md",
        ):
            path = soft_ws / "software-copyright" / name
            assert path.is_file() and path.stat().st_size > 50, path
        soft_lineage = soft_ws / ".host_builds" / "software-copyright.json"
        assert soft_lineage.is_file()
        assert "main.py" in (soft_ws / "software-copyright" / "SOURCE_CODE_INDEX.md").read_text(encoding="utf-8")

        # recovery + export evidence on patent workflow
        recover_status, recover = _request(
            port,
            token,
            f"/api/workflows/{patent_id}/recover",
            "POST",
            {"reason": "dual-clean ip recovery probe", "requested_by": "test"},
        )
        assert recover_status in {200, 202, 409}, recover

        status, export_blob = _request(port, token, f"/api/workflows/{patent_id}/export", raw=True, timeout=90)
        assert status == 200, export_blob[:200]
        assert export_blob[:2] == b"PK"
        with zipfile.ZipFile(io.BytesIO(export_blob)) as archive:
            names = [n.replace("\\", "/") for n in archive.namelist()]
            assert any(n.endswith("专利交底书/交底书.docx") for n in names), names[:30]

        return {
            "label": label,
            "project_id": project_id,
            "patent_id": patent_id,
            "copyright_id": copyright_id,
            "soft_id": soft_id,
            "patent_ws": str(patent_ws),
            "copyright_ws": str(copyright_ws),
            "soft_ws": str(soft_ws),
            "patent_docx_bytes": patent_docx.stat().st_size,
            "copyright_formal_files": len(list(formal.glob("*"))),
            "soft_index_ok": True,
            "recovery_status": recover_status,
            "export_ok": True,
        }
    finally:
        _stop(process)


def test_dual_clean_ip_host_chains_independent(tmp_path):
    base = tmp_path / "双干净IP"
    base.mkdir()
    # Keep short ASCII labels for process tokens; Unicode lives in directory roots.
    run1 = _clean_run("A", base)
    run2 = _clean_run("B", base)
    assert run1["patent_id"] != run2["patent_id"]
    assert run1["copyright_id"] != run2["copyright_id"]
    assert Path(run1["patent_ws"]).resolve() != Path(run2["patent_ws"]).resolve()
    assert run1["patent_docx_bytes"] >= 1000 and run2["patent_docx_bytes"] >= 1000
    assert run1["copyright_formal_files"] >= 2 and run2["copyright_formal_files"] >= 2
    assert run1["soft_index_ok"] and run2["soft_index_ok"]
    assert run1["export_ok"] and run2["export_ok"]
