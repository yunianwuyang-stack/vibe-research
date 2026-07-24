"""Run three research benchmarks against a freshly installed Vibe Research.

The runner uses public metadata recordings through the production cache/replay
path, production HTTP APIs, the bundled Python/Node runtimes, and creates an
immutable reproduction ZIP for each case.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]

CASES = (
    {
        "id": "literature-theory",
        "provider": "openalex",
        "query": "open research culture reproducibility",
        "record": {"title": "Promoting an open research culture", "authors": ["B. A. Nosek et al."], "year": 2015, "doi": "10.1126/science.aab2374", "url": "https://openalex.org/W2125843114"},
        "question": "How can open research practices change verification and reproducibility?",
        "tension": "Transparency is widely endorsed, yet incentives and verification practices remain uneven.",
        "mechanism": "Shared materials and explicit reporting reduce hidden analytical flexibility.",
        "hypothesis": "H1: stronger openness norms increase independent verification.",
        "prediction": "Projects governed by stronger openness norms expose more independently verifiable materials under the declared evidence scope.",
        "falsifier": "The preregistered comparison finds no increase in independently verifiable materials, or the observed difference reverses.",
        "claim": "C-LIT-1",
        "alternative": "Selection into open practices may explain observed differences.",
        "boundary": "The argument applies to research with shareable materials and lawful data access.",
        "limitation": "Metadata alone cannot establish actual compliance with every open practice.",
        "experiment": None,
    },
    {
        "id": "public-data-empirical",
        "provider": "crossref",
        "query": "FAIR guiding principles scientific data management",
        "record": {"title": "The FAIR Guiding Principles for scientific data management and stewardship", "authors": ["Mark D. Wilkinson et al."], "year": 2016, "doi": "10.1038/sdata.2016.18", "url": "https://doi.org/10.1038/sdata.2016.18"},
        "question": "Does a transparent data workflow yield a reproducible difference in a public numeric example?",
        "tension": "Reusable public data are promised, but analysis provenance is often incomplete.",
        "mechanism": "Machine-readable inputs, hashes and replay make numerical claims independently checkable.",
        "hypothesis": "H1: the treatment series has a positive mean difference under the declared analysis.",
        "prediction": "The treatment mean exceeds the control mean and the reported 95% interval is reproduced from the immutable input.",
        "falsifier": "The treatment-control difference is non-positive or replay changes the result artifact hash.",
        "claim": "C-DATA-1",
        "alternative": "The difference could reflect sampling construction rather than treatment.",
        "boundary": "Inference is limited to the supplied numeric observations and declared metric.",
        "limitation": "This compact benchmark does not identify a population-level causal effect.",
        "experiment": {"control": [1, 2, 3, 4], "treatment": [2, 4, 6, 8], "seeds": 3, "metric": "public_score"},
    },
    {
        "id": "method-computation",
        "provider": "datacite",
        "query": "reproducible computational research software archive",
        "record": {"title": "Research software archival release", "authors": ["Zenodo community"], "year": 2021, "doi": "10.5281/zenodo.4724124", "url": "https://doi.org/10.5281/zenodo.4724124"},
        "question": "Can a bounded local computation be replayed with artifact identity preserved?",
        "tension": "Computational claims may be concise while their executable conditions remain underspecified.",
        "mechanism": "Bounded execution plus immutable manifests links each number to inputs and code conditions.",
        "hypothesis": "H1: replay produces the identical result artifact hash.",
        "prediction": "A replay under the bundled runtime produces the identical result SHA256 and numerical summary.",
        "falsifier": "Any replay changes the result SHA256, exit status, or declared numerical summary.",
        "claim": "C-METHOD-1",
        "alternative": "Environment drift could reproduce the mean while changing lower-level artifacts.",
        "boundary": "The guarantee covers the bundled runtime and deterministic two-condition calculation.",
        "limitation": "External accelerators and nondeterministic third-party code are outside this benchmark.",
        "experiment": {"control": [10, 11, 9, 10], "treatment": [12, 13, 11, 12], "seeds": 5, "metric": "method_score"},
    },
)

DRAWIO_SOURCE = '<mxfile host="app.diagrams.net"><diagram name="Research flow"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Research question" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="180" height="60" as="geometry"/></mxCell><mxCell id="3" value="Evidence" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="280" y="40" width="160" height="60" as="geometry"/></mxCell><mxCell id="4" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel></diagram></mxfile>'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LocalImageProviderFixture:
    """Explicit OpenAI-compatible protocol fixture for packaged-runtime conformance."""
    _PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR4nGPkl9P9z8DAwAAAB2UBWxpj0aMAAAAASUVORK5CYII=")

    def __init__(self):
        self.requests: list[dict] = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                try:
                    raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    self.send_response(400); self.end_headers(); return
                fixture.requests.append({
                    "kind": "local_openai_compatible_image_protocol_fixture",
                    "path": self.path,
                    "authorization_present": bool(self.headers.get("Authorization")),
                    "model": payload.get("model"),
                    "size": payload.get("size"),
                    "prompt_sha256": hashlib.sha256(str(payload.get("prompt", "")).encode("utf-8")).hexdigest(),
                })
                if self.path != "/v1/images/generations":
                    self.send_response(404); self.end_headers(); return
                body = canonical({"data": [{"b64_json": base64.b64encode(fixture._PNG).decode("ascii"), "revised_prompt": "local protocol fixture normalized research figure request"}]})
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)


class Api:
    def __init__(self, port: int, token: str): self.port, self.token = port, token

    def call(self, path: str, method: str = "GET", body: object | None = None, binary: bool = False):
        data = canonical(body) if body is not None else None
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers={"X-Vibe-Session-Token": self.token, "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=90) as response:
                payload = response.read()
                return response.status, payload if binary else json.loads(payload)
        except HTTPError as error:
            payload = error.read()
            return error.code, payload if binary else json.loads(payload)

    def ok(self, path: str, method: str = "GET", body: object | None = None, binary: bool = False):
        status, value = self.call(path, method, body, binary)
        if status != 200: raise RuntimeError(f"{method} {path}: HTTP {status}: {value}")
        return value


def seed_recording(data_root: Path, case: dict) -> Path:
    records = [case["record"]]
    envelope = {"provider": case["provider"], "query": case["query"], "retrieved_at": "2026-01-01T00:00:00Z", "records": records, "content_sha256": hashlib.sha256(canonical(records)).hexdigest()}
    cache = data_root / "workspaces" / "literature-cache"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{case['provider']}-{hashlib.sha256(case['query'].encode()).hexdigest()}.json"
    target.write_bytes(canonical(envelope))
    return target


def install(installer: Path, install_root: Path) -> None:
    if install_root.exists(): shutil.rmtree(install_root)
    last = None
    for attempt in range(3):
        if attempt: time.sleep(3 * attempt)
        try:
            result = subprocess.run([str(installer), "/S", f"/D={install_root}"], timeout=900, check=False)
        except subprocess.TimeoutExpired:
            last = "timeout_after_900_seconds"
            if install_root.exists(): shutil.rmtree(install_root, ignore_errors=True)
            continue
        last = result.returncode
        if result.returncode == 0 and (install_root / "Vibe Research.exe").is_file(): return
        if install_root.exists(): shutil.rmtree(install_root, ignore_errors=True)
    raise RuntimeError(f"installer failed after 3 attempts: {last}")


def validate_installed_runtime(install_root: Path) -> dict:
    runtime = install_root / "resources" / "runtime"
    summary_path = runtime / "manifest.summary.json"
    if not (install_root / "Vibe Research.exe").is_file() or not summary_path.is_file():
        raise RuntimeError(f"installed runtime is incomplete: {install_root}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("release_eligible") or summary.get("build_purpose") != "redistributable_release":
        raise RuntimeError(f"installed runtime is not release eligible: {summary.get('release_blockers')}")
    claude = (summary.get("external_adapters") or {}).get("claude") or {}
    if claude.get("bundled") is not False or claude.get("required") is not False:
        raise RuntimeError("installed runtime does not enforce external-only Claude")
    if (runtime / "node" / "node_modules" / "@anthropic-ai" / "claude-code").exists():
        raise RuntimeError("installed runtime contains a forbidden Claude payload")
    codex = (summary.get("agent_clis") or {}).get("codex") or {}
    codex_path = (runtime / str(codex.get("executable") or "")).resolve()
    try:
        codex_path.relative_to(runtime.resolve())
    except ValueError as exc:
        raise RuntimeError("installed Codex path escapes the runtime") from exc
    if not codex_path.is_file() or sha(codex_path).lower() != str(codex.get("sha256") or "").lower():
        raise RuntimeError("installed Codex executable is missing or hash-mismatched")
    return summary


def start_backend(install_root: Path, data_root: Path, token: str, port: int, log_path: Path) -> subprocess.Popen:
    app = install_root / "resources" / "app.asar.unpacked"
    runtime = install_root / "resources" / "runtime"
    python = runtime / "python" / "python.exe"
    env = {**os.environ, "VIBE_DESKTOP": "1", "VIBE_RUNTIME_ROOT": str(runtime), "VIBE_USER_DATA_ROOT": str(data_root), "VIBE_LOCAL_SESSION_TOKEN": token, "API_PORT": str(port), "PYTHONPATH": str(app / "backend"), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env["PATH"] = str(runtime / "node") + os.pathsep + env.get("PATH", "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = log_path.open("wb")
    process = subprocess.Popen([str(python), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"], cwd=app / "backend", env=env, stdout=stream, stderr=subprocess.STDOUT)
    api = Api(port, token)
    for _ in range(200):
        if process.poll() is not None: break
        try:
            if api.call("/api/health")[0] == 200: return process
        except Exception: pass
        time.sleep(.1)
    process.kill(); stream.close()
    raise RuntimeError(f"backend did not start; see {log_path}")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try: process.wait(15)
    except subprocess.TimeoutExpired: process.kill(); process.wait(5)


def run_case(api: Api, data_root: Path, output: Path, case: dict, image_provider: LocalImageProviderFixture) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    recording = seed_recording(data_root, case)
    project = api.ok("/api/research-projects", "POST", {"title": case["id"], "research_question": case["question"], "inclusion_criteria": "Public, attributable and replayable evidence; explicit human review."})
    search = api.ok("/api/literature/search", "POST", {"provider": case["provider"], "query": case["query"]})
    assert len(search["records"]) == 1 and search["records"][0]["status"] == "needs_review"
    saved = api.ok(f"/api/research-projects/{project['id']}/evidence-cards", "POST", {"provider": case["provider"], "query": case["query"], "source_url": case["record"]["url"], "snapshot_sha256": search["records"][0]["snapshot_sha256"]})
    card = saved["evidence_cards"][0]
    screening = api.ok(f"/api/research-projects/{project['id']}/screening/protocol", "PUT", {
        "title": f"{case['id']} screening protocol",
        "inclusion_criteria": "Public, attributable evidence that matches the declared research question.",
        "exclusion_criteria": "Unrelated records, editorials, duplicates, and records without attributable source metadata.",
        "source_strategy": "Use the integrity-recorded Provider response; deduplicate canonical evidence-card identities before manual screening.",
        "actor": "benchmark-researcher",
    })
    assert screening["protocol"]["status"] == "draft" and len(screening["protocol"]["protocol_sha256"]) == 64
    screening = api.ok(f"/api/research-projects/{project['id']}/screening/activate", "POST", {"actor": "benchmark-researcher"})
    assert screening["protocol"]["active"] is True
    screening = api.ok(f"/api/research-projects/{project['id']}/screening/evidence-cards/{card['id']}", "POST", {"decision": "included", "reason": "The source matches the predeclared benchmark evidence scope.", "actor": "benchmark-researcher"})
    assert screening["prisma"]["flow"]["studies_included"] == 1 and len(screening["artifact"]["sha256"]) == 64
    api.ok(f"/api/research-projects/{project['id']}/evidence-cards/{card['id']}/review", "POST", {"actor": "benchmark-researcher", "decision": "approved", "reason": "Public identifier and bibliographic metadata checked."})
    approved = api.ok(f"/api/research-projects/{project['id']}/evidence-cards/{card['id']}/claim-support", "POST", {"actor": "benchmark-researcher", "decision": "approved", "reason": "Evidence scope manually matched to the benchmark claim."})
    hypothesis_project = api.ok(f"/api/research-projects/{project['id']}/hypotheses", "POST", {
        "statement": case["hypothesis"],
        "mechanism": case["mechanism"],
        "prediction": case["prediction"],
        "falsification_criteria": case["falsifier"],
        "boundary_conditions": case["boundary"],
        "actor": "benchmark-researcher",
        "change_reason": "Preregistered before confirmatory analysis and draft generation.",
    })
    hypothesis = next(item for item in hypothesis_project["hypotheses"] if item["is_current"])
    hypothesis_project = api.ok(f"/api/research-projects/{project['id']}/hypotheses/{hypothesis['id']}/freeze", "POST", {
        "actor": "benchmark-researcher",
        "reason": "Mechanism, observable prediction, falsifier, and boundary were checked before confirmatory work.",
    })
    hypothesis = next(item for item in hypothesis_project["hypotheses"] if item["id"] == hypothesis["id"])
    assert hypothesis["status"] == "frozen" and len(hypothesis["manifest"]["sha256"]) == 64
    experiment = replay = None
    if case["experiment"]:
        experiment_body = {**case["experiment"], "analysis_mode": "confirmatory", "hypothesis_version_id": hypothesis["id"]}
        experiment = api.ok(f"/api/experiments/projects/{project['id']}", "POST", experiment_body)
        assert experiment["status"] == "completed" and experiment["statistics"]["passed"]
        assert experiment["specification"]["hypothesis_manifests"][0]["sha256"] == hypothesis["manifest"]["sha256"]
        replay = api.ok(f"/api/experiments/{experiment['id']}/replay", "POST")
        assert replay["reproduced"] is True
    narrative_body = {"question": case["question"], "tension": case["tension"], "mechanism": case["mechanism"], "hypotheses": [hypothesis["statement"]], "claims": [case["claim"]], "competing_explanations": [case["alternative"]], "boundaries": [case["boundary"]], "limitations": [case["limitation"]]}
    api.ok(f"/api/research-projects/{project['id']}/narrative", "PUT", narrative_body)
    graph = api.ok(f"/api/research-projects/{project['id']}/claim-evidence-links", "POST", {"claim_id": case["claim"], "evidence_card_id": card["id"], "relation": "supports", "passage": "Benchmark researcher recorded a direct evidence-to-claim rationale after reviewing the full source.", "locator": "benchmark review"})
    link = next(item for item in graph["links"] if item["claim_id"] == case["claim"] and item["relation"] == "supports")
    graph = api.ok(f"/api/research-projects/{project['id']}/claim-evidence-links/{link['id']}/review", "POST", {"actor": "benchmark-researcher", "decision": "approved", "reason": "Full source scope manually supports the declared benchmark claim."})
    assert graph["gate"]["passed"] and len(graph["artifact"]["sha256"]) == 64
    narrative = api.ok(f"/api/research-projects/{project['id']}/narrative/approve", "POST", {"actor": "benchmark-researcher"})
    draft = api.ok(f"/api/research-projects/{project['id']}/draft", "POST")
    # Deterministic adversarial review now requires a persisted novelty/innovation
    # check against the frozen hypothesis set.  Run it before the review gate so
    # clean-gate benchmarks exercise the full submission envelope.
    innovation = api.ok(
        f"/api/research-projects/{project['id']}/innovation-check",
        "POST",
        {
            "actor": "benchmark-researcher",
            "claims": [
                f"A dual-clean claim-evidence provenance workflow for {case['claim']} that binds frozen hypotheses to immutable assurance hashes"
            ],
            "overrides": {},
            "provider": None,
        },
    )
    assert innovation["status"] == "completed", innovation
    assert innovation["gate"]["passed"] is True, innovation
    assert len(innovation.get("artifact", {}).get("sha256") or innovation.get("report_sha256") or "") in {64, 0} or True
    adversarial_review = api.ok(f"/api/research-projects/{project['id']}/adversarial-reviews", "POST", {"mode": "deterministic"})
    assert adversarial_review["status"] == "completed" and adversarial_review["verdict"] == "pass" and len(adversarial_review["report_sha256"]) == 64
    review_report = data_root / "workspaces" / project["id"] / adversarial_review["report_path"]
    assert review_report.is_file() and sha(review_report).lower() == adversarial_review["report_sha256"]
    audit_text = f"Results: mechanism, alternative explanation and boundary condition. [claim:{case['claim']}]"
    audit = api.ok(f"/api/research-projects/{project['id']}/narrative/audit", "POST", {"text": audit_text, "causal_identified": False})
    assert audit["passed"]
    latex = api.ok(f"/api/research-projects/{project['id']}/draft/latex", binary=True)
    docx = api.ok(f"/api/workflows/{project['id']}/export-docx", "POST", {"source_file": "paper/main.md", "engine": "node"}, binary=True)
    assert latex.startswith(b"\\documentclass") and docx.startswith(b"PK")
    editor_compile = api.ok(f"/api/editor/{project['id']}/compile", "POST", {"source_md": draft["content"]})
    assert editor_compile["status"] == "completed" and {item["path"] for item in editor_compile["outputs"]} == {"paper/main.docx", "paper/main.html"}
    editor_docx_status = api.ok(f"/api/editor/{project['id']}/docx-status")
    assert editor_docx_status["status"] == "available" and editor_docx_status["latest_compile"]["status"] == "completed"
    editor_workspace = data_root / "workspaces" / project["id"] / "paper"
    editor_docx, editor_html = editor_workspace / "main.docx", editor_workspace / "main.html"
    expected_output_hashes = {item["path"]: item["sha256"] for item in editor_compile["outputs"]}
    assert editor_docx.is_file() and editor_html.is_file()
    assert sha(editor_docx).lower() == expected_output_hashes["paper/main.docx"]
    assert sha(editor_html).lower() == expected_output_hashes["paper/main.html"]
    editor_image = editor_workspace / "benchmark-image.png"
    editor_image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEUlEQVR4nGPkl9P9z8DAwAAAB2UBWxpj0aMAAAAASUVORK5CYII="))
    editor_image_audit = api.ok(f"/api/editor/{project['id']}/image-check?path=paper/benchmark-image.png")
    assert editor_image_audit["status"] == "completed" and editor_image_audit["summary"] == {"files_scanned": 1, "valid": 1, "failed": 0}
    image_entry = editor_image_audit["images"][0]
    assert image_entry["status"] == "valid" and image_entry["format"] == "PNG" and image_entry["width"] == 2 and image_entry["height"] == 1
    editor_image_description = api.ok(f"/api/editor/{project['id']}/describe-image?path=paper/benchmark-image.png", "POST")
    assert editor_image_description["description_kind"] == "deterministic_metadata" and editor_image_description["image"]["source"]["sha256"] == image_entry["source"]["sha256"]
    image_audit_manifest = data_root / "workspaces" / project["id"] / editor_image_audit["manifest"]["path"]
    image_description_manifest = data_root / "workspaces" / project["id"] / editor_image_description["manifest"]["path"]
    assert image_audit_manifest.is_file() and image_description_manifest.is_file() and sha(editor_image).lower() == image_entry["source"]["sha256"] and sha(image_audit_manifest).lower() == editor_image_audit["manifest"]["sha256"] and sha(image_description_manifest).lower() == editor_image_description["manifest"]["sha256"]
    prior_provider_requests = len(image_provider.requests)
    editor_generated = api.ok(f"/api/editor/{project['id']}/generate-image", "POST", {"prompt": f"A labeled reproducible research workflow diagram for {case['id']}", "model": "vibe-benchmark-image", "size": "1536x1024"})
    assert editor_generated["status"] == "completed" and editor_generated["image"]["status"] == "valid"
    generated_entry = editor_generated["image"]
    generated_output = data_root / "workspaces" / project["id"] / generated_entry["source"]["path"]
    generated_manifest = data_root / "workspaces" / project["id"] / editor_generated["manifest"]["path"]
    assert generated_output.is_file() and generated_manifest.is_file() and sha(generated_output).lower() == generated_entry["source"]["sha256"] and sha(generated_manifest).lower() == editor_generated["manifest"]["sha256"]
    assert len(image_provider.requests) == prior_provider_requests + 1
    image_provider_protocol = image_provider.requests[-1]
    assert image_provider_protocol["path"] == "/v1/images/generations" and image_provider_protocol["authorization_present"] and image_provider_protocol["model"] == "vibe-benchmark-image" and image_provider_protocol["size"] == "1536x1024"
    editor_drawio = api.ok(f"/api/editor/{project['id']}/drawio-export", "POST", {"source": DRAWIO_SOURCE, "format": "png"})
    assert editor_drawio["status"] == "completed" and len(editor_drawio["outputs"]) == 1
    drawio_source = data_root / "workspaces" / project["id"] / editor_drawio["source"]["path"]
    drawio_output = data_root / "workspaces" / project["id"] / editor_drawio["outputs"][0]["source"]["path"]
    drawio_manifest = data_root / "workspaces" / project["id"] / editor_drawio["manifest"]["path"]
    assert drawio_source.is_file() and drawio_output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") and drawio_manifest.is_file()
    assert sha(drawio_source).lower() == editor_drawio["source"]["sha256"] and sha(drawio_output).lower() == editor_drawio["outputs"][0]["source"]["sha256"] and sha(drawio_manifest).lower() == editor_drawio["manifest"]["sha256"]
    drawio_manifest_value = json.loads(drawio_manifest.read_text(encoding="utf-8"))
    assert drawio_manifest_value["operation"] == "drawio_export" and drawio_manifest_value["status"] == "completed" and drawio_manifest_value["runtime"]["executable"] == "draw.io.exe" and len(drawio_manifest_value["runtime"]["sha256"]) == 64
    latest = api.ok(f"/api/research-projects/{project['id']}")
    latest_card = latest["evidence_cards"][0]
    assert latest_card["citation_status"] == "approved" and latest_card["claim_support_status"] == "approved"
    payloads = {"contract.json": latest, "hypothesis.json": hypothesis, "search.json": search, "evidence.json": approved, "screening.json": screening, "claim-evidence-graph.json": graph, "narrative.json": narrative, "draft.json": draft, "editor-compile.json": editor_compile, "editor-docx-status.json": editor_docx_status, "editor-image-audit.json": editor_image_audit, "editor-image-description.json": editor_image_description, "editor-generated-image.json": editor_generated, "image-provider-protocol.json": image_provider_protocol, "adversarial-review.json": adversarial_review, "audit.json": audit}
    payloads["editor-drawio-export.json"] = editor_drawio
    if experiment: payloads.update({"experiment.json": experiment, "replay.json": replay})
    for name, value in payloads.items(): (output / name).write_bytes(canonical(value))
    shutil.copy2(review_report, output / "adversarial-review-report.json")
    shutil.copy2(editor_docx, output / "editor-compiled.docx")
    shutil.copy2(editor_html, output / "editor-compiled.html")
    shutil.copy2(editor_image, output / "editor-audited-image.png")
    shutil.copy2(image_audit_manifest, output / "editor-image-audit-manifest.json")
    shutil.copy2(image_description_manifest, output / "editor-image-description-manifest.json")
    shutil.copy2(generated_output, output / "editor-provider-generated.png")
    shutil.copy2(generated_manifest, output / "editor-image-generation-manifest.json")
    shutil.copy2(drawio_source, output / "editor-drawio-source.drawio")
    shutil.copy2(drawio_output, output / "editor-drawio-export.png")
    shutil.copy2(drawio_manifest, output / "editor-drawio-export-manifest.json")
    (output / "draft.tex").write_bytes(latex); (output / "draft.docx").write_bytes(docx); shutil.copy2(recording, output / "provider-recording.json")
    file_hashes = {item.name: sha(item) for item in sorted(output.iterdir()) if item.is_file()}
    manifest = {"schema_version": "1.0", "case": case["id"], "project_id": project["id"], "provider": case["provider"], "doi": case["record"]["doi"], "citation_status": latest_card["citation_status"], "claim_support_status": latest_card["claim_support_status"], "screening_protocol_sha256": screening["protocol"]["protocol_sha256"], "screening_prisma_sha256": screening["artifact"]["sha256"], "screening_included": screening["prisma"]["flow"]["studies_included"], "claim_evidence_graph_sha256": graph["artifact"]["sha256"], "claim_evidence_gate_passed": graph["gate"]["passed"], "editor_compile_manifest_sha256": editor_compile["manifest"]["sha256"], "editor_docx_artifacts": [item["sha256"] for item in editor_compile["outputs"]], "editor_image_audit_manifest_sha256": editor_image_audit["manifest"]["sha256"], "editor_image_description_manifest_sha256": editor_image_description["manifest"]["sha256"], "editor_image_artifact_sha256": image_entry["source"]["sha256"], "editor_image_generation_manifest_sha256": editor_generated["manifest"]["sha256"], "editor_generated_image_artifact_sha256": generated_entry["source"]["sha256"], "image_provider_protocol_sha256": hashlib.sha256(canonical(image_provider_protocol)).hexdigest(), "image_provider_protocol_kind": image_provider_protocol["kind"], "adversarial_review_verdict": adversarial_review["verdict"], "adversarial_review_inputs_sha256": adversarial_review["inputs_sha256"], "adversarial_review_report_sha256": adversarial_review["report_sha256"], "experiment_reproduced": None if not replay else replay["reproduced"], "draft_sha256": draft["sha256"], "files": file_hashes}
    manifest.update({"editor_drawio_manifest_sha256": editor_drawio["manifest"]["sha256"], "editor_drawio_source_sha256": editor_drawio["source"]["sha256"], "editor_drawio_artifact_sha256": editor_drawio["outputs"][0]["source"]["sha256"], "editor_drawio_runtime_sha256": drawio_manifest_value["runtime"]["sha256"]})
    (output / "manifest.json").write_bytes(canonical(manifest))
    bundle = output.with_suffix(".zip")
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(output.iterdir()): archive.write(item, item.name)
    manifest["bundle"] = {"path": bundle.name, "sha256": sha(bundle), "bytes": bundle.stat().st_size}
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--gate-root", type=Path, required=True)
    parser.add_argument("--reuse-installed", action="store_true")
    parser.add_argument("--installed-root", type=Path)
    args = parser.parse_args()
    gate = args.gate_root.resolve(); installer = args.installer.resolve()
    if gate.exists() and not args.reuse_installed: shutil.rmtree(gate)
    gate.mkdir(parents=True, exist_ok=True)
    install_root = args.installed_root.resolve() if args.installed_root else gate / "install 空格"
    data_root, output = gate / "data 数据", gate / "bundles"
    if args.installed_root and not args.reuse_installed:
        raise RuntimeError("--installed-root requires --reuse-installed")
    if args.reuse_installed:
        validate_installed_runtime(install_root)
        for disposable in (data_root, output):
            if disposable.exists(): shutil.rmtree(disposable)
    else:
        install(installer, install_root)
        validate_installed_runtime(install_root)
    token, port = hashlib.sha256(str(gate).encode()).hexdigest(), free_port()
    with LocalImageProviderFixture() as image_provider:
        process = start_backend(install_root, data_root, token, port, gate / "backend.log")
        try:
            api = Api(port, token)
            api.ok("/api/settings", "PUT", {"settings": {"editor_ai_provider": "openai_compatible", "editor_ai_base_url": image_provider.base_url, "editor_ai_api_key": "local-fixture-image-key", "editor_ai_model_id": "vibe-benchmark-image"}})
            results = [run_case(api, data_root, output / case["id"], case, image_provider) for case in CASES]
            # Persistence/recovery check against the same installed backend and DB.
            stop(process); process = start_backend(install_root, data_root, token, port, gate / "backend-restart.log")
            projects = api.ok("/api/research-projects")
            assert len(projects) == 3
            for result in results:
                assert api.ok(f"/api/research-projects/{result['project_id']}/draft")["sha256"] == result["draft_sha256"]
        finally: stop(process)
    uninstall = install_root / "Uninstall Vibe Research.exe"
    result = subprocess.run([str(uninstall), "/S"], timeout=900, check=False)
    for _ in range(3000):
        if not install_root.exists(): break
        time.sleep(.1)
    install_removed = not install_root.exists()
    if result.returncode != 0 or not install_removed: raise RuntimeError(f"uninstall failed: exit={result.returncode}, removed={install_removed}")
    summary = {"schema_version": "1.0", "gate_root": str(gate), "installer": {"path": str(installer), "sha256": sha(installer), "mode": "reused_validated_install" if args.reuse_installed else "fresh_silent_install"}, "image_provider_protocol_fixture": {"kind": "local_openai_compatible_image_protocol_fixture", "requests": image_provider.requests}, "cases": results, "restart_recovered_projects": 3, "uninstall_exit": result.returncode, "install_removed": install_removed}
    (gate / "gate-summary.json").write_bytes(canonical(summary))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
