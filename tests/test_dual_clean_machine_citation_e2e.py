"""Dual Unicode user-data roots: machine citation existence gate E2E.

UI→API→CitationVerifier→literature-cache offline lookup→SQLite fields→
citation_checks/*.json artifact. Human approve is blocked on machine FAIL.
"""
from __future__ import annotations

import hashlib
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

QUERY = "dual-clean machine citation query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-machine-cite"
RECORD = {
    "title": "Dual Clean Machine Citation Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-machine-cite",
    "url": SOURCE_URL,
}


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, token: str, path: str, method: str = "GET", body: dict | None = None):
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
        with urlopen(req, timeout=45) as response:
            payload = response.read()
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
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
    for _ in range(100):
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


def _seed_literature_snapshot(user_data: Path) -> str:
    cache = user_data / "workspaces" / "literature-cache"
    cache.mkdir(parents=True, exist_ok=True)
    content_sha = hashlib.sha256(_canonical([RECORD])).hexdigest()
    envelope = {
        "provider": PROVIDER,
        "query": QUERY,
        "retrieved_at": "2026-07-16T00:00:00+00:00",
        "records": [RECORD],
        "content_sha256": content_sha,
    }
    path = cache / f"{PROVIDER}-{hashlib.sha256(QUERY.encode()).hexdigest()}.json"
    raw = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _run(label: str, base: Path) -> dict:
    user = base / f"用户数据-引用核验-{label}"
    user.mkdir(parents=True)
    snapshot_sha = _seed_literature_snapshot(user)
    token = f"dual-cite-{label}"
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
                "title": f"Machine citation dual clean {label}",
                "research_question": "Does machine citation verification persist under Unicode roots?",
                "inclusion_criteria": "peer reviewed experimental report",
            },
        )
        assert status == 200, project
        project_id = project["id"]
        ws = user / "workspaces" / project_id

        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/evidence-cards",
            "POST",
            {
                "provider": PROVIDER,
                "query": QUERY,
                "source_url": SOURCE_URL,
                "snapshot_sha256": snapshot_sha,
            },
        )
        assert status == 200, project
        cards = project.get("evidence_cards") or []
        assert cards, project
        card_id = cards[0]["id"]

        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/evidence-cards/{card_id}/review",
            "POST",
            {"actor": "researcher", "decision": "approved", "reason": "offline machine+human citation check"},
        )
        assert status == 200, project
        card = project["evidence_cards"][0]
        assert card["citation_status"] == "approved"
        assert card["citation_machine_verdict"] == "PASS"
        assert card["citation_machine_layer"] == "offline_snapshot"
        assert card["citation_machine_artifact_path"]
        artifact = ws / card["citation_machine_artifact_path"]
        assert artifact.is_file(), artifact
        payload = json.loads(artifact.read_text(encoding="utf-8"))
        assert payload["verdict"] == "PASS"
        assert payload["human_decision"] == "approved"
        assert payload.get("artifact_sha256")
        assert any(ord(ch) > 127 for ch in str(user))

        # Reject path must still record a machine check without blocking.
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/evidence-cards/{card_id}/review",
            "POST",
            {"actor": "researcher", "decision": "rejected", "reason": "re-check reject path keeps machine audit"},
        )
        assert status == 200, project
        card = next(c for c in project["evidence_cards"] if c["id"] == card_id)
        assert card["citation_status"] == "rejected"
        assert card["citation_machine_verdict"] == "PASS"
        assert (ws / card["citation_machine_artifact_path"]).is_file()

        return {
            "label": label,
            "user_data": str(user),
            "project_id": project_id,
            "card_id": card_id,
            "machine_verdict": card["citation_machine_verdict"],
            "machine_layer": card["citation_machine_layer"],
            "artifact": str(ws / card["citation_machine_artifact_path"]),
            "artifact_bytes": (ws / card["citation_machine_artifact_path"]).stat().st_size,
            "unicode_root": True,
        }
    finally:
        _stop(process)


def test_dual_clean_machine_citation_roots(tmp_path):
    base = tmp_path / "dual-clean-machine-citation"
    base.mkdir()
    run1 = _run("1", base)
    run2 = _run("2", base)
    assert run1["machine_verdict"] == "PASS" and run2["machine_verdict"] == "PASS"
    assert run1["machine_layer"] == "offline_snapshot"
    assert run2["machine_layer"] == "offline_snapshot"
    assert run1["artifact_bytes"] >= 50 and run2["artifact_bytes"] >= 50
    assert run1["project_id"] != run2["project_id"]
    assert Path(run1["user_data"]) != Path(run2["user_data"])
