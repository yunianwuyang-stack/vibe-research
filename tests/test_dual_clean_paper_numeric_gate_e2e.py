"""Dual Unicode user-data roots: paper numeric gate over real HTTP.

Chain (no live LLM keys):
  offline literature snapshot → evidence approve → frozen hypothesis
  → narrative approve → multi-seed confirmatory experiment (stats PASS)
  → claim-experiment approve → draft generate binds registry numbers
  → draft save with registry numbers OK
  → draft save with fabricated Results number → 409
  → assurance envelope surfaces numerical_paper / draft_unverified_number
    when fabricated content is rejected (honest fail, not silent pass)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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

QUERY = "dual-clean paper numeric gate query"
PROVIDER = "openalex"
SOURCE_URL = "https://doi.org/10.1234/dual-clean-paper-numeric"
RECORD = {
    "title": "Dual Clean Paper Numeric Gate Paper",
    "authors": ["Researcher A", "Researcher B"],
    "year": 2024,
    "doi": "10.1234/dual-clean-paper-numeric",
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
        with urlopen(req, timeout=90) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
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
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for _ in range(120):
        if process.poll() is not None:
            out = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"backend exited early: {out[-3000:]}")
        try:
            status, _ = _request(port, token, "/api/health")
            if status == 200:
                return process
        except Exception:
            time.sleep(0.1)
    process.kill()
    out = process.stdout.read() if process.stdout else ""
    raise AssertionError(f"backend failed to start: {out[-3000:]}")


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


def _replace_results_section(content: str, body: str) -> str:
    """Replace ## 结果 section body while preserving frontmatter and other sections."""
    pattern = re.compile(r"(## 结果\n)(.*?)(\n## )", re.S)
    match = pattern.search(content)
    assert match, "draft missing ## 结果 section"
    return content[: match.start()] + match.group(1) + "\n" + body.strip() + "\n" + match.group(3) + content[match.end() :]


def _numeric_run(label: str, base: Path) -> dict:
    user = base / f"用户数据-稿件数字门-{label}"
    user.mkdir(parents=True)
    snapshot_sha = _seed_literature_snapshot(user)
    token = f"dual-paper-num-{label}"
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
                "title": f"Paper numeric dual-clean {label}",
                "research_question": "Do registry-bound experimental numbers survive dual-clean draft save?",
                "inclusion_criteria": "peer-reviewed experimental report",
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
        card_id = project["evidence_cards"][0]["id"]
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/evidence-cards/{card_id}/review",
            "POST",
            {"actor": "researcher", "decision": "approved", "reason": "metadata verified offline"},
        )
        assert status == 200, project
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/evidence-cards/{card_id}/claim-support",
            "POST",
            {
                "actor": "researcher",
                "decision": "approved",
                "reason": "full text supports dual-clean numeric claim",
            },
        )
        assert status == 200, project

        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses",
            "POST",
            {
                "statement": "Treatment mean exceeds control mean under multi-seed dual-clean numeric gate",
                "mechanism": "Bounded two-condition ProcessSupervisor calculation",
                "prediction": "Positive difference with multi-seed statistics gate pass",
                "falsification_criteria": "Non-positive difference or statistics gate fail",
                "boundary_conditions": "numeric laboratory observations only",
                "actor": "researcher",
                "change_reason": "register dual-clean paper numeric hypothesis",
            },
        )
        assert status == 200, project
        hyp = project["hypotheses"][0]
        hyp_id = hyp["id"]
        status, project = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/hypotheses/{hyp_id}/freeze",
            "POST",
            {"actor": "researcher", "reason": "lock before confirmatory experiment"},
        )
        assert status == 200, project
        frozen = next(h for h in project["hypotheses"] if h["id"] == hyp_id)
        assert frozen["status"] == "frozen"
        version_id = (
            frozen.get("version_id")
            or (frozen.get("manifest") or {}).get("version_id")
            or frozen.get("id")
        )

        status, narrative = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative",
            "PUT",
            {
                "question": "Do registry-bound experimental numbers survive dual-clean draft save?",
                "tension": "Drafts could invent experimental numbers without lineage",
                "mechanism": "Eligible numeric registry + PaperNumericVerifier on draft save",
                "hypotheses": [frozen["statement"]],
                "claims": ["C1"],
                "competing_explanations": ["silent mock numbers"],
                "boundaries": ["numeric dual-clean desktop runs"],
                "limitations": ["synthetic two-condition calculator"],
            },
        )
        assert status == 200, narrative
        status, narrative = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative/approve",
            "POST",
            {"actor": "researcher"},
        )
        assert status == 200, narrative

        # Multi-seed confirmatory experiment → statistics pass + lineage.
        status, run = _request(
            port,
            token,
            f"/api/experiments/projects/{project_id}",
            "POST",
            {
                "control": [1, 2, 3],
                "treatment": [2, 4, 6],
                "seeds": 3,
                "metric": "score",
                "analysis_mode": "confirmatory",
                "hypothesis_version_id": version_id,
            },
        )
        assert status == 200, run
        assert run["status"] == "completed", run
        assert run["statistics"]["passed"] is True, run["statistics"]
        assert run.get("result_sha256") and len(run["result_sha256"]) == 64
        result = run.get("result") or {}
        if not result and Path(run["workspace_path"], "result.json").is_file():
            result = json.loads(Path(run["workspace_path"], "result.json").read_text(encoding="utf-8"))
        treatment_mean = float(result.get("treatment_mean", 0))
        control_mean = float(result.get("control_mean", 0))
        difference = float(result.get("difference", treatment_mean - control_mean))
        assert treatment_mean > 0 or difference != 0, result

        status, graph = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/claim-experiment-links",
            "POST",
            {
                "claim_id": "C1",
                "experiment_run_id": run["id"],
                "relation": "supports",
                "result_locator": "difference",
                "interpretation": "Positive treatment-control difference under multi-seed confirmatory mode",
                "evidence_card_ids": [card_id],
            },
        )
        assert status == 200, graph
        link_id = graph["experiment_links"][0]["id"]
        status, graph = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/claim-experiment-links/{link_id}/review",
            "POST",
            {
                "actor": "researcher",
                "decision": "approved",
                "reason": "locator difference matches confirmatory run with intact lineage",
            },
        )
        assert status == 200, graph
        assert graph["gate"]["passed"] is True, graph["gate"]

        # Draft generate must bind eligible registry numbers into ## 结果.
        status, draft = _request(port, token, f"/api/research-projects/{project_id}/draft", "POST")
        assert status == 200, draft
        content = draft["content"]
        draft_path = ws / draft["path"]
        assert draft_path.is_file(), draft_path
        assert "approved-citations" in content or "approved-citations-only" in content
        assert "尚无通过统计门禁的实验数字" not in content, content
        assert "尚无经验证的数字" not in content, content
        # At least one registry value appears in Results (formatted with .6g).
        registry_hits = [
            v
            for v in (treatment_mean, control_mean, difference)
            if v != 0 and (f"{v:.6g}" in content or f"{v:.6f}".rstrip("0").rstrip(".") in content)
        ]
        assert registry_hits or any(
            key in content for key in ("treatment_mean", "control_mean", "difference", "score")
        ), content
        assert run["result_sha256"] in content or run["id"] in content, content

        # Honest save of registry-bound draft (+ non-numeric researcher note).
        ok_content = content.rstrip() + "\n\nResearcher note without fabricated experimental numbers. [claim:C1]\n"
        status, saved = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/draft",
            "PUT",
            {"content": ok_content},
        )
        assert status == 200, saved
        assert saved.get("ok") is True, saved
        assert draft_path.read_text(encoding="utf-8") == ok_content

        # Fabricated experimental number in Results must hard-fail (409), not silent accept.
        fabricated = _replace_results_section(
            ok_content,
            f"- fabricated accuracy: 0.713337 [claim:C1]\n"
            f"- score / treatment_mean: {treatment_mean:.6g} [claim:C1] (run {run['id']}, artifact {run['result_sha256']})\n",
        )
        status, rejected = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/draft",
            "PUT",
            {"content": fabricated},
        )
        assert status == 409, rejected
        detail = rejected.get("detail") or rejected
        if isinstance(detail, dict):
            message = str(detail.get("message", ""))
            issues = detail.get("issues") or []
        else:
            message = str(detail)
            issues = []
        assert "number" in message.lower() or "数字" in message or issues, rejected
        # On-disk draft must remain the last honest save (no silent overwrite).
        assert draft_path.read_text(encoding="utf-8") == ok_content

        # Narrative audit endpoint also rejects fabricated experimental numbers.
        status, audit = _request(
            port,
            token,
            f"/api/research-projects/{project_id}/narrative/audit",
            "POST",
            {"text": "## 结果\n\nAccuracy was 0.713337.\n", "causal_identified": False},
        )
        assert status == 200, audit
        assert audit.get("passed") is False, audit
        assert any(
            (not item.get("verified", True)) or item.get("category") == "experimental"
            for item in (audit.get("numbers") or audit.get("findings") or [])
        ) or audit.get("issues"), audit

        # Assurance envelope must not be submission-ready with only partial gates,
        # and must include numerical_paper among gate definitions / findings path.
        status, assurance = _request(port, token, f"/api/research-projects/{project_id}/assurance")
        assert status == 200, assurance
        assert assurance.get("submission_ready") is False
        gates = assurance.get("gates") or assurance.get("gate_status") or []
        gate_ids = {
            g.get("id") or g.get("code") or g.get("name")
            for g in gates
            if isinstance(g, dict)
        }
        if not gate_ids and isinstance(assurance.get("gates"), dict):
            gate_ids = set(assurance["gates"].keys())
        # Envelope always exposes numerical_paper in definitions or findings taxonomy.
        blob = json.dumps(assurance, ensure_ascii=False)
        assert "numerical_paper" in blob or "稿件数字" in blob or "draft_unverified_number" in blob, assurance

        assert any(ord(ch) > 127 for ch in str(user))
        assert str(user.resolve()) in str(ws.resolve()) or user.resolve() in ws.resolve().parents

        return {
            "label": label,
            "project_id": project_id,
            "user_data": str(user),
            "workspace": str(ws),
            "run_id": run["id"],
            "result_sha256": run["result_sha256"],
            "treatment_mean": treatment_mean,
            "difference": difference,
            "draft_sha256": saved.get("sha256") or draft.get("sha256"),
            "registry_bound": True,
            "fabricated_rejected": True,
            "audit_rejects_fabricated": True,
            "assurance_not_ready": True,
            "gate_ids": sorted(str(x) for x in gate_ids if x),
        }
    finally:
        _stop(process)


def test_dual_clean_paper_numeric_gate_draft_save(tmp_path: Path) -> None:
    base = tmp_path / "双干净稿件数字门"
    base.mkdir()
    run1 = _numeric_run("1", base)
    run2 = _numeric_run("2", base)
    assert run1["project_id"] != run2["project_id"]
    assert run1["run_id"] != run2["run_id"]
    assert Path(run1["workspace"]).resolve() != Path(run2["workspace"]).resolve()
    assert "用户数据-稿件数字门-1" in run1["user_data"]
    assert "用户数据-稿件数字门-2" in run2["user_data"]
    for run in (run1, run2):
        assert run["registry_bound"] and run["fabricated_rejected"]
        assert run["audit_rejects_fabricated"] and run["assurance_not_ready"]
        assert len(run["result_sha256"]) == 64
        assert run["draft_sha256"]
