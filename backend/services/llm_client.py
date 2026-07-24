"""OpenAI-compatible LLM client with the original async service contract."""
from __future__ import annotations

import asyncio
import base64
import http.client
import json
import logging
import os
import re
import socket
import ssl
import threading
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

AGENT_KEYS = {
    "executor": {"provider": "executor_provider", "base_url": "executor_base_url", "api_key": "executor_api_key", "model_id": "executor_model_id"},
    "reviewer": {"provider": "reviewer_provider", "base_url": "reviewer_base_url", "api_key": "reviewer_api_key", "model_id": "reviewer_model_id"},
    "editor_ai": {"provider": "editor_ai_provider", "base_url": "editor_ai_base_url", "api_key": "editor_ai_api_key", "model_id": "editor_ai_model_id"},
}

SUPPORTED_PROVIDERS = {"openai_compatible", "openai_responses", "anthropic_messages", "gemini_generate_content"}
_MAX_GENERATED_IMAGE_BYTES = 50 * 1024 * 1024


class APIHTTPError(RuntimeError):
    """HTTP failure that preserves enough structure for protocol fallbacks."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"API 返回 HTTP {status}: {detail}")


class RequestCancelled(RuntimeError):
    """Raised when a cooperative streaming request is cancelled by its owner."""


_RESPONSES_OPTION_CACHE: dict[tuple[str, str, str], frozenset[str]] = {}
_RESPONSES_OPTION_CACHE_LOCK = threading.Lock()
_RESPONSES_OPTION_NAMES = frozenset({"temperature", "top_p", "max_output_tokens"})

ENV_MAPPING = {
    "executor_api_key": "ANTHROPIC_API_KEY",
    "executor_base_url": "ANTHROPIC_BASE_URL",
    "reviewer_api_key": "OPENAI_API_KEY",
    "reviewer_base_url": "OPENAI_BASE_URL",
    "reviewer_model_id": "REVIEWER_MODEL_ID",
    "editor_ai_api_key": "EDITOR_AI_API_KEY",
    "editor_ai_base_url": "EDITOR_AI_BASE_URL",
    "editor_ai_model_id": "EDITOR_AI_MODEL_ID",
    "minimax_api_key": "MINIMAX_API_KEY",
    "minimax_group_id": "MINIMAX_GROUP_ID",
    "gemini_api_key": "GEMINI_API_KEY",
    "codex_bin": "CODEX_BIN",
    "claude_bin": "CLAUDE_BIN",
    "executor_model_id": "EXECUTOR_MODEL_ID",
    "gpt_image_api_key": "GPT_IMAGE_API_KEY",
    "gpt_image_base_url": "GPT_IMAGE_BASE_URL",
    "aminer_api_key": "AMINER_API_KEY",
}


async def get_all_settings() -> Dict[str, str]:
    from services.state_store import get_all_settings as _get_all_settings
    return await _get_all_settings()


def _agent_keys(agent: str) -> Dict[str, str]:
    try:
        return AGENT_KEYS[agent]
    except KeyError as exc:
        raise Exception(f"未知智能体：{agent}") from exc


def _configured_agent(settings: Dict[str, str], agent: str) -> tuple[str, str, str, str]:
    keys = _agent_keys(agent)
    provider = settings.get(keys["provider"], "openai_responses").strip() or "openai_responses"
    base_url = settings.get(keys["base_url"], "").strip()
    api_key = settings.get(keys["api_key"], "").strip()
    model_id = settings.get(keys["model_id"], "").strip() or "gpt-4o"
    if provider not in SUPPORTED_PROVIDERS:
        raise Exception(f"智能体 {agent} 使用了不支持的服务商：{provider}")
    if not api_key:
        raise Exception(f"未配置 {agent} 的 API 密钥，请先在设置页面配置")
    if not base_url:
        raise Exception(f"未配置 {agent} 的服务地址（Base URL），请先在设置页面配置")
    return provider, base_url, api_key, model_id


def _request_parameters(settings: Dict[str, str], agent: str, *, default_max_tokens: int) -> dict:
    """Read persisted inference controls without silently accepting bad values."""
    _agent_keys(agent)
    try:
        temperature = float(settings.get(f"{agent}_temperature", "0.3"))
        top_p = float(settings.get(f"{agent}_top_p", "1"))
        max_tokens = int(settings.get(f"{agent}_max_tokens", str(default_max_tokens)))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"智能体 {agent} 的推理参数无效") from exc
    if not 0 <= temperature <= 2 or not 0 <= top_p <= 1 or not 1 <= max_tokens <= 32768:
        raise RuntimeError(f"智能体 {agent} 的推理参数超出允许范围")
    result = {"temperature": temperature, "top_p": top_p, "max_tokens": max_tokens}
    reasoning_effort = str(settings.get(f"{agent}_reasoning_effort", "")).strip().lower()
    if reasoning_effort:
        if reasoning_effort not in {"minimal", "low", "medium", "high"}:
            raise RuntimeError(f"智能体 {agent} 的推理强度无效")
        result["reasoning_effort"] = reasoning_effort
    return result


def _completion_path(base_url: str) -> tuple[str, str, int, str]:
    parsed = urlparse(base_url)
    scheme = parsed.scheme or "https"
    host = parsed.hostname
    if not host:
        raise RuntimeError(f"无法解析服务地址（Base URL）：{base_url}")
    port = parsed.port or (443 if scheme == "https" else 80)
    path = (parsed.path or "").rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions"
    return scheme, host, port, path.replace("/v1/v1/", "/v1/")


def _responses_path(base_url: str) -> str:
    """Build the OpenAI Responses endpoint from a provider base URL."""
    parsed = urlparse(base_url)
    if not parsed.hostname:
        raise RuntimeError(f"无法解析 OpenAI 响应协议服务地址：{base_url}")
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        path = path.removesuffix("/chat/completions")
    if path.endswith("/responses"):
        return path
    if path.endswith("/v1"):
        return f"{path}/responses"
    return f"{path}/v1/responses" if path else "/v1/responses"


def _iter_sse_events(raw: bytes) -> list[dict[str, Any]]:
    """Decode Server-Sent Events, including comments and multiline data."""
    events: list[dict[str, Any]] = []
    data_lines: list[str] = []
    event_name = ""

    def flush() -> None:
        nonlocal data_lines, event_name
        if not data_lines:
            event_name = ""
            return
        data = "\n".join(data_lines).strip()
        data_lines = []
        if not data or data == "[DONE]":
            event_name = ""
            return
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid SSE JSON event: {data[:500]}") from exc
        if isinstance(value, dict):
            if event_name and not value.get("type"):
                value["type"] = event_name
            events.append(value)
        event_name = ""

    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    for line in text.split("\n"):
        if not line:
            flush()
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
    flush()
    return events


def _aggregate_responses_sse(events: list[dict[str, Any]]) -> dict:
    """Build one Responses object from output-item SSE events.

    Some compatible relays omit ``response.completed.response.output`` and
    only send ``response.output_item.done``. Those completed items are the
    authoritative source for both assistant text and function calls.
    """
    completed: dict[str, Any] | None = None
    done_items: list[tuple[int, dict[str, Any]]] = []
    text_deltas: list[str] = []
    final_text = ""
    response_id = ""

    for event in events:
        event_type = str(event.get("type") or "")
        response = event.get("response")
        if isinstance(response, dict) and isinstance(response.get("id"), str):
            response_id = response["id"]
        if event_type == "response.output_item.done" and isinstance(event.get("item"), dict):
            try:
                index = int(event.get("output_index", len(done_items)))
            except (TypeError, ValueError):
                index = len(done_items)
            done_items.append((index, dict(event["item"])))
        elif event_type == "response.output_text.delta" and isinstance(event.get("delta"), str):
            text_deltas.append(event["delta"])
        elif event_type == "response.output_text.done" and isinstance(event.get("text"), str):
            final_text = event["text"]
        elif event_type in {"response.completed", "response.done"} and isinstance(response, dict):
            completed = dict(response)
        elif event_type in {"error", "response.failed", "response.incomplete"}:
            detail = event.get("error")
            if not detail and isinstance(response, dict):
                detail = response.get("error") or response.get("incomplete_details")
            raise RuntimeError(
                f"OpenAI Responses stream failed: {json.dumps(detail or event, ensure_ascii=False)[:1000]}"
            )

    result: dict[str, Any] = completed or {"object": "response"}
    if response_id and not result.get("id"):
        result["id"] = response_id
    existing_output = result.get("output")
    output = (
        [dict(item) for item in existing_output if isinstance(item, dict)]
        if isinstance(existing_output, list)
        else []
    )

    for index, item in sorted(done_items, key=lambda pair: pair[0]):
        item_id = item.get("id")
        matched = next(
            (i for i, old in enumerate(output) if item_id and old.get("id") == item_id),
            None,
        )
        if matched is not None:
            output[matched] = item
        elif 0 <= index < len(output):
            output[index] = item
        else:
            output.append(item)

    has_output_text = any(
        isinstance(part, dict) and part.get("type") == "output_text"
        for item in output
        if isinstance(item.get("content"), list)
        for part in item["content"]
    )
    reconstructed_text = final_text or "".join(text_deltas)
    if reconstructed_text and not has_output_text:
        output.append(
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": reconstructed_text, "annotations": []}
                ],
            }
        )
    result["output"] = output
    if reconstructed_text and not result.get("output_text"):
        result["output_text"] = reconstructed_text
    return result


def _body_looks_like_sse(raw: bytes) -> bool:
    """True only when the body is SSE-framed.

    Some local relays (e.g. CC Switch) mislabel a complete JSON chat.completion
    payload as ``text/event-stream``. Content-Type alone must not force SSE
    aggregation — that path yields ``{"object":"response","output":[]}`` and
    false "format error" failures for live providers.
    """
    stripped = raw.lstrip()
    return stripped.startswith((b"data:", b"event:", b":"))


def _decode_api_response(raw: bytes, content_type: str) -> dict:
    del content_type  # body shape is authoritative; see _body_looks_like_sse
    if _body_looks_like_sse(raw):
        return _aggregate_responses_sse(_iter_sse_events(raw))
    try:
        result = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"API response is neither JSON nor valid SSE: {raw[:500]!r}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError("API response root must be an object")
    return result


def _consume_sse_response(
    response: http.client.HTTPResponse,
    on_sse_event: Callable[[dict[str, Any]], None] | None,
    cancel_event: threading.Event | None,
) -> dict:
    events: list[dict[str, Any]] = []
    record: list[bytes] = []
    total = 0
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelled("OpenAI Responses request cancelled")
        line = response.readline()
        if not line:
            break
        total += len(line)
        if total > 64 * 1024 * 1024:
            raise RuntimeError("API response exceeded 64 MiB")
        record.append(line)
        if line.strip():
            continue
        raw_record = b"".join(record)
        decoded = _iter_sse_events(raw_record)
        record.clear()
        events.extend(decoded)
        if on_sse_event:
            for event in decoded:
                on_sse_event(event)
        if b"data: [DONE]" in raw_record or any(
            event.get("type")
            in {
                "response.completed", "response.done", "response.failed",
                "response.incomplete", "error",
            }
            for event in decoded
        ):
            break
    if record:
        decoded = _iter_sse_events(b"".join(record))
        events.extend(decoded)
        if on_sse_event:
            for event in decoded:
                on_sse_event(event)
    return _aggregate_responses_sse(events)


def _request_json(
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: int,
    *,
    path: str | None = None,
    extra_headers: dict[str, str] | None = None,
    include_authorization: bool = True,
    on_sse_event: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """POST JSON and transparently decode either JSON or Responses SSE."""
    scheme, host, port, default_path = _completion_path(base_url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body)),
    }
    if include_authorization:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra_headers:
        headers.update(extra_headers)
    connection = None
    cancel_watcher_stop = threading.Event()
    cancel_watcher: threading.Thread | None = None
    try:
        if scheme == "https":
            context = ssl.create_default_context()
            connection = http.client.HTTPSConnection(
                host, port, timeout=timeout, context=context
            )
        else:
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
        if cancel_event is not None:
            if cancel_event.is_set():
                raise RequestCancelled("OpenAI Responses request cancelled")

            def interrupt_when_cancelled() -> None:
                while not cancel_watcher_stop.is_set():
                    if not cancel_event.wait(0.1):
                        continue
                    try:
                        sock = connection.sock if connection is not None else None
                        if sock is not None:
                            sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        if connection is not None:
                            connection.close()
                    except OSError:
                        pass
                    return

            cancel_watcher = threading.Thread(
                target=interrupt_when_cancelled,
                name="responses-request-cancel",
                daemon=True,
            )
            cancel_watcher.start()
        connection.request("POST", path or default_path, body, headers)
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "")
        claims_sse = "text/event-stream" in content_type.lower()
        chunks: list[bytes] = []
        total = 0
        # Only stream-consume when the caller needs cooperative cancel AND the
        # provider claims SSE.  Mislabeled JSON bodies (common on local relays)
        # must fall through to full-body JSON decode.
        if response.status == 200 and claims_sse and cancel_event is not None:
            # ``HTTPResponse.readline`` may remain blocked on Windows even
            # after another thread closes the socket.  Keep that low-level
            # reader daemonized while this request owner remains responsive to
            # cancellation. The normal terminal event joins it immediately.
            result_box: dict[str, Any] = {}

            def consume_stream() -> None:
                try:
                    result_box["result"] = _consume_sse_response(
                        response, on_sse_event, cancel_event
                    )
                except BaseException as exc:  # delivered back to request owner
                    result_box["error"] = exc

            stream_reader = threading.Thread(
                target=consume_stream,
                name="responses-sse-reader",
                daemon=True,
            )
            stream_reader.start()
            while stream_reader.is_alive():
                stream_reader.join(timeout=0.1)
                if cancel_event.is_set():
                    try:
                        sock = connection.sock
                        if sock is not None:
                            sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    raise RequestCancelled("OpenAI Responses request cancelled")
            if cancel_event.is_set():
                raise RequestCancelled("OpenAI Responses request cancelled")
            error = result_box.get("error")
            if isinstance(error, BaseException):
                raise error
            result = result_box.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("Responses SSE reader ended without a response")
            return result
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RequestCancelled("OpenAI Responses request cancelled")
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise RuntimeError("API response exceeded 64 MiB")
            chunks.append(chunk)
        raw = b"".join(chunks)
        if response.status != 200:
            detail = raw.decode("utf-8", errors="replace")[:1000]
            raise APIHTTPError(response.status, detail)
        if _body_looks_like_sse(raw):
            events = _iter_sse_events(raw)
            if on_sse_event:
                for event in events:
                    on_sse_event(event)
            return _aggregate_responses_sse(events)
        return _decode_api_response(raw, content_type)
    except (OSError, http.client.HTTPException) as exc:
        if cancel_event is not None and cancel_event.is_set():
            raise RequestCancelled("OpenAI Responses request cancelled") from exc
        raise
    finally:
        cancel_watcher_stop.set()
        if connection is not None:
            connection.close()
        if cancel_watcher is not None and cancel_watcher is not threading.current_thread():
            cancel_watcher.join(timeout=0.2)

def _extract_content(result: dict) -> str:
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"API 响应格式错误: {json.dumps(result, ensure_ascii=False)[:500]}") from exc
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        if text_parts:
            return "".join(text_parts)
    raise RuntimeError(f"API 响应格式错误: content={content!r}")


def _responses_parameters(parameters: dict) -> dict:
    """Map the shared model profile controls to the OpenAI Responses schema."""
    result = {
        "temperature": parameters["temperature"],
        "top_p": parameters["top_p"],
        "max_output_tokens": parameters["max_tokens"],
    }
    if parameters.get("reasoning_effort"):
        result["reasoning"] = {"effort": parameters["reasoning_effort"]}
    return result


def _responses_cache_key(base_url: str, path: str, model_id: str) -> tuple[str, str, str]:
    parsed = urlparse(base_url)
    authority = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return authority, path, model_id


def _unsupported_responses_parameter(error: Exception) -> str | None:
    """Extract a rejected optional parameter from common compatible errors."""
    detail = error.detail if isinstance(error, APIHTTPError) else str(error)
    candidates: list[str] = []
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        value: Any = parsed.get("error", parsed)
        if isinstance(value, dict):
            if isinstance(value.get("param"), str):
                candidates.append(value["param"])
            if isinstance(value.get("message"), str):
                detail = f"{detail}\n{value['message']}"
    patterns = (
        r"(?i)unsupported\s+parameter\s*[:=]?\s*['\"]?([a-zA-Z0-9_.-]+)",
        r"(?i)parameter\s+['\"]([a-zA-Z0-9_.-]+)['\"]\s+(?:is\s+)?not\s+supported",
        r"(?i)does\s+not\s+support\s+(?:the\s+)?['\"]?([a-zA-Z0-9_.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, detail)
        if match:
            candidates.append(match.group(1))
    for candidate in candidates:
        normalized = candidate.rsplit(".", 1)[-1]
        if normalized in _RESPONSES_OPTION_NAMES:
            return normalized
    return None


def _clear_responses_parameter_cache() -> None:
    """Test/support hook for resetting learned provider capabilities."""
    with _RESPONSES_OPTION_CACHE_LOCK:
        _RESPONSES_OPTION_CACHE.clear()


def request_openai_response(
    base_url: str,
    api_key: str,
    payload: dict,
    timeout: int = 300,
    *,
    path: str | None = None,
    on_sse_event: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Call Responses with SSE support and learned optional-parameter fallback.

    Provider/model capability learning is process-local and contains only
    parameter names.  Credentials and response bodies are never cached.
    """
    endpoint = path or _responses_path(base_url)
    model_id = str(payload.get("model") or "")
    cache_key = _responses_cache_key(base_url, endpoint, model_id)
    with _RESPONSES_OPTION_CACHE_LOCK:
        rejected = set(_RESPONSES_OPTION_CACHE.get(cache_key, frozenset()))
    request_payload = {key: value for key, value in payload.items() if key not in rejected}

    for _ in range(len(_RESPONSES_OPTION_NAMES) + 1):
        try:
            return _request_json(
                base_url,
                api_key,
                request_payload,
                timeout,
                path=endpoint,
                on_sse_event=on_sse_event,
                cancel_event=cancel_event,
            )
        except RuntimeError as exc:
            unsupported = _unsupported_responses_parameter(exc)
            if unsupported is None or unsupported not in request_payload:
                raise
            request_payload.pop(unsupported, None)
            rejected.add(unsupported)
            with _RESPONSES_OPTION_CACHE_LOCK:
                # Negotiations for the same provider/model may happen in
                # parallel.  Merge with what another request learned instead
                # of letting the last writer accidentally re-enable an option.
                rejected.update(_RESPONSES_OPTION_CACHE.get(cache_key, frozenset()))
                _RESPONSES_OPTION_CACHE[cache_key] = frozenset(rejected)
            for option in rejected:
                request_payload.pop(option, None)
            log.info(
                "Responses provider rejected optional parameter %s; retrying without it",
                unsupported,
            )
    raise RuntimeError("Responses optional-parameter negotiation did not converge")


def _extract_responses_content(result: dict) -> str:
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text
    output = result.get("output")
    if isinstance(output, list):
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
        if text_parts:
            return "".join(text_parts)
    raise RuntimeError(f"OpenAI 响应协议未返回输出文本：{json.dumps(result, ensure_ascii=False)[:500]}")


def _provider_path(base_url: str, provider: str, model_id: str) -> str | None:
    if provider == "openai_compatible":
        return None
    if provider == "openai_responses":
        return _responses_path(base_url)
    _, _, _, base_path = _completion_path(base_url)
    if provider == "anthropic_messages":
        base_path = base_path.removesuffix("/chat/completions").rstrip("/")
        if base_path.endswith("/messages"):
            return base_path
        return f"{base_path or '/v1'}/messages"
    if provider == "gemini_generate_content":
        base_path = base_path.removesuffix("/chat/completions").rstrip("/")
        if not base_path.endswith("/v1beta"):
            base_path = f"{base_path}/v1beta" if base_path else "/v1beta"
        return f"{base_path}/models/{quote(model_id, safe='')}:generateContent"
    raise RuntimeError(f"不支持的服务商：{provider}")


def _image_generation_path(base_url: str) -> str:
    """Build an OpenAI-compatible image endpoint without altering the configured host."""
    parsed = urlparse(base_url)
    if not parsed.hostname:
        raise RuntimeError(f"无法解析图像生成服务地址：{base_url}")
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/chat/completions"):
        path = path.removesuffix("/chat/completions")
    if path.endswith("/images/generations"):
        return path
    if path.endswith("/v1"):
        return f"{path}/images/generations"
    return f"{path}/v1/images/generations" if path else "/v1/images/generations"


def _safe_image_provider_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}{parsed.path}".rstrip("/")


def _download_generated_image(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("图像服务商返回了非 HTTP(S) 下载地址")
    request = Request(url, headers={"User-Agent": "Vibe-Research/1.2"})
    try:
        with urlopen(request, timeout=120) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_GENERATED_IMAGE_BYTES:
                raise RuntimeError("生成图像超过 50 MB 下载上限")
            value = response.read(_MAX_GENERATED_IMAGE_BYTES + 1)
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError(f"生成图像下载失败：{type(error).__name__}：{error}") from error
    if len(value) > _MAX_GENERATED_IMAGE_BYTES:
        raise RuntimeError("生成图像超过 50 MB 下载上限")
    return value


def _call_image_generation_sync(base_url: str, api_key: str, model_id: str, prompt: str, size: str, timeout: int = 240) -> tuple[bytes, dict]:
    response = _request_json(
        base_url,
        api_key,
        {"model": model_id, "prompt": prompt, "n": 1, "size": size, "response_format": "b64_json"},
        timeout,
        path=_image_generation_path(base_url),
    )
    data = response.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise RuntimeError("图像服务商响应中未包含数据项")
    item = data[0]
    encoded = item.get("b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise RuntimeError("图像服务商返回了无效的 b64_json") from error
    elif isinstance(item.get("url"), str) and item["url"]:
        image = _download_generated_image(item["url"])
    else:
        raise RuntimeError("图像服务商响应中既没有 b64_json，也没有下载地址")
    if not image:
        raise RuntimeError("图像服务商返回了空图像")
    if len(image) > _MAX_GENERATED_IMAGE_BYTES:
        raise RuntimeError("生成图像超过 50 MB 下载上限")
    metadata = {"revised_prompt": item.get("revised_prompt") if isinstance(item.get("revised_prompt"), str) else None}
    return image, metadata


async def generate_image(agent: str, prompt: str, model_id: str = "", size: str = "1024x1024", timeout: int = 240) -> tuple[bytes, dict]:
    settings = await get_all_settings()
    try:
        provider, base_url, api_key, configured_model = _configured_agent(settings, agent)
    except Exception as error:
        # Missing key / base URL / provider misconfig must surface as RuntimeError
        # so editor routes return structured 503, never an unhandled 500.
        raise RuntimeError(str(error)) from error
    if provider != "openai_compatible":
        raise RuntimeError("图像生成当前需要使用 OpenAI 兼容协议的模型档案")
    selected_model = model_id.strip() or configured_model
    if not selected_model or len(selected_model) > 240:
        raise RuntimeError("图像生成模型 ID 无效")
    if size not in {"1024x1024", "1536x1024", "1024x1536"}:
        raise RuntimeError("图像尺寸必须是 1024x1024、1536x1024 或 1024x1536")
    try:
        image, metadata = await asyncio.to_thread(_call_image_generation_sync, base_url, api_key, selected_model, prompt, size, timeout)
    except Exception as error:
        message = str(error).replace(api_key, "[已隐藏]")
        raise RuntimeError(message) from error
    return image, {"provider": provider, "base_url": _safe_image_provider_base_url(base_url), "model_id": selected_model, "size": size, **metadata}


def _anthropic_parameters(parameters: dict) -> dict:
    result = {key: parameters[key] for key in ("temperature", "top_p", "max_tokens")}
    reasoning_effort = parameters.get("reasoning_effort")
    if reasoning_effort:
        budgets = {"minimal": 1024, "low": 2048, "medium": 4096, "high": 8192}
        result["thinking"] = {"type": "enabled", "budget_tokens": budgets[reasoning_effort]}
    return result


def _gemini_parameters(parameters: dict) -> dict:
    result = {
        "temperature": parameters["temperature"],
        "topP": parameters["top_p"],
        "maxOutputTokens": parameters["max_tokens"],
    }
    reasoning_effort = parameters.get("reasoning_effort")
    if reasoning_effort:
        budgets = {"minimal": 512, "low": 1024, "medium": 4096, "high": 8192}
        result["thinkingConfig"] = {"thinkingBudget": budgets[reasoning_effort]}
    return result


def _extract_anthropic_content(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        text_parts = [part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"]
        if text_parts:
            return "".join(text_parts)
    raise RuntimeError(f"Anthropic 响应格式错误：{json.dumps(result, ensure_ascii=False)[:500]}")


def _extract_gemini_content(result: dict) -> str:
    try:
        parts = result["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Gemini 响应格式错误：{json.dumps(result, ensure_ascii=False)[:500]}") from exc
    text_parts = [part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    if text_parts:
        return "".join(text_parts)
    raise RuntimeError(f"Gemini 响应中未包含文本：{json.dumps(result, ensure_ascii=False)[:500]}")


def _call_llm_sync(provider: str, base_url: str, api_key: str, model_id: str, prompt: str, parameters: dict, timeout: int = 300) -> str:
    if provider == "openai_compatible":
        result = _request_json(base_url, api_key, {"model": model_id, "messages": [{"role": "user", "content": prompt}], **parameters}, timeout)
        return _extract_content(result)
    if provider == "openai_responses":
        result = request_openai_response(
            base_url,
            api_key,
            {"model": model_id, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}], **_responses_parameters(parameters)},
            timeout,
            path=_provider_path(base_url, provider, model_id),
        )
        return _extract_responses_content(result)
    if provider == "anthropic_messages":
        result = _request_json(
            base_url, api_key, {"model": model_id, "messages": [{"role": "user", "content": prompt}], **_anthropic_parameters(parameters)}, timeout,
            path=_provider_path(base_url, provider, model_id), extra_headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, include_authorization=False,
        )
        return _extract_anthropic_content(result)
    if provider == "gemini_generate_content":
        path = f"{_provider_path(base_url, provider, model_id)}?{urlencode({'key': api_key})}"
        result = _request_json(
            base_url, api_key, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": _gemini_parameters(parameters)}, timeout,
            path=path, include_authorization=False,
        )
        return _extract_gemini_content(result)
    raise RuntimeError(f"不支持的服务商：{provider}")


def _call_llm_vision_sync(
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    prompt: str,
    image_b64: str,
    mime_type: str = "image/png",
    parameters: dict | None = None,
    timeout: int = 120,
) -> str:
    request_parameters = parameters or {"max_tokens": 2048, "temperature": 0.3, "top_p": 1.0}
    if provider == "openai_compatible":
        result = _request_json(base_url, api_key, {"model": model_id, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}}]}], **request_parameters}, timeout)
        return _extract_content(result)
    if provider == "openai_responses":
        result = request_openai_response(
            base_url,
            api_key,
            {"model": model_id, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": f"data:{mime_type};base64,{image_b64}"}]}], **_responses_parameters(request_parameters)},
            timeout,
            path=_provider_path(base_url, provider, model_id),
        )
        return _extract_responses_content(result)
    if provider == "anthropic_messages":
        result = _request_json(
            base_url, api_key, {"model": model_id, "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}}]}], **_anthropic_parameters(request_parameters)}, timeout,
            path=_provider_path(base_url, provider, model_id), extra_headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"}, include_authorization=False,
        )
        return _extract_anthropic_content(result)
    if provider == "gemini_generate_content":
        path = f"{_provider_path(base_url, provider, model_id)}?{urlencode({'key': api_key})}"
        result = _request_json(
            base_url, api_key, {"contents": [{"role": "user", "parts": [{"text": prompt}, {"inlineData": {"mimeType": mime_type, "data": image_b64}}]}], "generationConfig": _gemini_parameters(request_parameters)}, timeout,
            path=path, include_authorization=False,
        )
        return _extract_gemini_content(result)
    raise RuntimeError(f"不支持的服务商：{provider}")


async def call_llm(agent: str, prompt: str, timeout: int = 300) -> str:
    settings = await get_all_settings()
    provider, base_url, api_key, model_id = _configured_agent(settings, agent)
    parameters = _request_parameters(settings, agent, default_max_tokens=8192)
    return await asyncio.to_thread(_call_llm_sync, provider, base_url, api_key, model_id, prompt, parameters, timeout)


async def describe_image(image_path: str, context: str = "") -> str:
    path = Path(image_path)
    if not path.exists():
        return ""
    settings = await get_all_settings()
    try:
        provider, base_url, api_key, model_id = _configured_agent(settings, "editor_ai")
        parameters = _request_parameters(settings, "editor_ai", default_max_tokens=2048)
    except Exception:
        try:
            provider, base_url, api_key, model_id = _configured_agent(settings, "reviewer")
            parameters = _request_parameters(settings, "reviewer", default_max_tokens=2048)
        except Exception as exc:
            log.error("Vision API configuration error: %s", exc)
            return ""

    mime_type = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
    prompt = (
        "请详细描述这张图片的内容。如果是赛题中的示意图、地图、网络拓扑、流程图或数据图表，"
        "请提取所有关键信息：节点名称、连接关系、数值标注、坐标、图例等。用中文回答，尽可能详细和结构化。"
    )
    if context:
        prompt += f"\n\n背景信息：{context}"
    try:
        return await asyncio.to_thread(
            _call_llm_vision_sync,
            provider,
            base_url,
            api_key,
            model_id,
            prompt,
            base64.b64encode(path.read_bytes()).decode("ascii"),
            mime_type,
            parameters,
            120,
        )
    except Exception as exc:
        log.error("Vision API error: %s", exc)
        return ""


async def test_connection(agent: str) -> Dict:
    try:
        response = await call_llm(agent, "Say hello in one word.", timeout=30)
        return {"ok": True, "message": response[:200], "agent": agent}
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:200], "agent": agent}


async def get_env_for_subprocess() -> Dict[str, str]:
    try:
        settings = await get_all_settings()
    except Exception as exc:
        log.warning("Settings unavailable for subprocess environment: %s", exc)
        settings = {}
    env: Dict[str, str] = {}
    for settings_key, env_key in ENV_MAPPING.items():
        value = settings.get(settings_key, "")
        if value:
            env[env_key] = str(value)
    return env


def verify_endpoint_integrity() -> bool:
    """Compatibility hook; custom relay support intentionally removes URL locking."""
    return True


def _locked_url() -> str:
    """Compatibility hook returning no forced relay in the reconstructed build."""
    return ""
