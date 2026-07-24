"""Machine-readable user-observable contracts for every editor endpoint."""
from __future__ import annotations

from typing import Final

CAPABILITY_UNAVAILABLE = "capability_unavailable"

# Keys are FastAPI route templates prefixed by their HTTP method.  A route is
# implemented only when its handler delegates to a concrete service operation.
EDITOR_ENDPOINT_CONTRACTS: Final[dict[str, dict[str, str]]] = {
    "GET /api/editor/{wf_id}/mode": {"status": "implemented"},
    "GET /api/editor/{wf_id}/files": {"status": "implemented"},
    "GET /api/editor/{wf_id}/file-preview-html": {"status": "implemented"},
    "GET /api/editor/{wf_id}/file": {"status": "implemented"},
    "PUT /api/editor/{wf_id}/file": {"status": "implemented"},
    "POST /api/editor/{wf_id}/upload": {"status": "implemented"},
    "POST /api/editor/{wf_id}/create-file": {"status": "implemented"},
    "DELETE /api/editor/{wf_id}/file": {"status": "implemented"},
    "GET /api/editor/{wf_id}/download": {"status": "implemented"},
    "POST /api/editor/{wf_id}/drawio-export": {"status": "implemented"},
    "POST /api/editor/{wf_id}/mermaid-export": {"status": "implemented"},
    "GET /api/editor/{wf_id}/image-check": {"status": "implemented"},
    "POST /api/editor/{wf_id}/generate-image": {"status": "implemented"},
    "POST /api/editor/{wf_id}/compile": {"status": "implemented"},
    "GET /api/editor/{wf_id}/pdf": {"status": "implemented"},
    "GET /api/editor/{wf_id}/docx-status": {"status": "implemented"},
    "GET /api/editor/{wf_id}/docx": {"status": "implemented"},
    "GET /api/editor/{wf_id}/stats": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-edit": {"status": "implemented"},
    # Implemented: the handler stages reviewable file proposals via the
    # configured editor_ai provider.  Runtime 501 is reserved for missing
    # credentials / provider configuration, not a permanent capability hole.
    "POST /api/editor/{wf_id}/ai-agent": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-agent-stage": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-agent-apply": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-agent-discard": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-agent-undo": {"status": "implemented"},
    "POST /api/editor/{wf_id}/ai-agent-stop": {"status": "implemented"},
    "GET /api/editor/{wf_id}/ai-agent-check": {"status": "implemented"},
    "POST /api/editor/{wf_id}/run-script": {"status": "implemented"},
    "POST /api/editor/{wf_id}/describe-image": {"status": "implemented"},
    "GET /api/editor/{wf_id}/chat-history": {"status": "implemented"},
    "DELETE /api/editor/{wf_id}/chat-history": {"status": "implemented"},
}
