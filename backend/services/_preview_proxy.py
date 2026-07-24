"""Loopback static server with a bounded same-origin API reverse proxy."""
from __future__ import annotations

import argparse
import http.client
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
_MAX_BODY = 64 * 1024 * 1024
_COPY_CHUNK = 64 * 1024


def _connection_tokens(headers) -> set[str]:
    """Return header names nominated by RFC 9110 ``Connection`` fields."""
    values = headers.get_all("Connection", []) if hasattr(headers, "get_all") else []
    return {
        token.strip().casefold()
        for value in values
        for token in value.split(",")
        if token.strip()
    }


class _ProxyHandler(SimpleHTTPRequestHandler):
    backend_port = 0

    def _is_proxy_path(self) -> bool:
        path = self.path.split("?", 1)[0]
        return path == "/api" or path.startswith("/api/") or path in {
            "/docs", "/openapi.json", "/redoc",
        }

    def _content_length(self) -> int | None:
        values = self.headers.get_all("Content-Length", [])
        if not values:
            return 0
        normalized = {value.strip() for value in values}
        if len(normalized) != 1:
            self.send_error(400, "Conflicting Content-Length")
            return None
        try:
            length = int(normalized.pop())
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return None
        if length < 0 or length > _MAX_BODY:
            self.send_error(413, "Request body too large")
            return None
        return length

    def _proxy(self) -> None:
        if not self.backend_port:
            self.send_error(405, "No backend is running for this preview")
            return
        # Do not accept absolute-form request targets or protocol-relative
        # paths.  The upstream host is fixed as a second SSRF boundary.
        parsed = urlsplit(self.path)
        if not self.path.startswith("/") or parsed.scheme or parsed.netloc:
            self.send_error(400, "Invalid proxy target")
            return
        if self.headers.get("Transfer-Encoding"):
            self.send_error(400, "Transfer-Encoding is not supported")
            return
        if self.headers.get("Expect"):
            self.send_error(417, "Expect is not supported")
            return
        length = self._content_length()
        if length is None:
            return

        excluded = _HOP_BY_HOP | _connection_tokens(self.headers)
        connection = http.client.HTTPConnection("127.0.0.1", self.backend_port, timeout=60)
        response: http.client.HTTPResponse | None = None
        try:
            connection.putrequest(
                self.command,
                self.path,
                skip_host=True,
                skip_accept_encoding=True,
            )
            connection.putheader("Host", f"127.0.0.1:{self.backend_port}")
            for key, value in self.headers.items():
                if key.casefold() not in excluded:
                    connection.putheader(key, value)
            if length:
                connection.putheader("Content-Length", str(length))
            connection.endheaders()

            remaining = length
            while remaining:
                chunk = self.rfile.read(min(_COPY_CHUNK, remaining))
                if not chunk:
                    raise ConnectionError("request body ended before Content-Length")
                connection.send(chunk)
                remaining -= len(chunk)

            # HTTPConnection never follows redirects, so an untrusted generated
            # backend cannot turn this loopback proxy into a cross-origin SSRF.
            response = connection.getresponse()
            self._relay(response)
        except (ConnectionError, OSError, http.client.HTTPException) as error:
            if not self.wfile.closed:
                try:
                    self.send_error(502, f"Backend unavailable: {error}")
                except (BrokenPipeError, ConnectionError, OSError):
                    pass
        finally:
            if response is not None:
                response.close()
            connection.close()

    def _relay(self, response: http.client.HTTPResponse) -> None:
        connection_tokens = _connection_tokens(response.headers)
        excluded = _HOP_BY_HOP | connection_tokens
        self.send_response(response.status, response.reason)
        for key, value in response.headers.items():
            if key.casefold() not in excluded:
                self.send_header(key, value)
        upstream_length = None if "content-length" in connection_tokens else response.headers.get("Content-Length")
        trusted_length = False
        if upstream_length is not None:
            try:
                if int(upstream_length) >= 0:
                    self.send_header("Content-Length", upstream_length)
                    trusted_length = True
            except ValueError:
                pass
        if not trusted_length:
            self.close_connection = True
        # Without a trustworthy length, HTTP/1.0 connection close delimits the
        # body while allowing chunks (including SSE output) to reach the client
        # as they arrive instead of buffering the whole response in memory.
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            while True:
                read = getattr(response, "read1", response.read)
                chunk = read(_COPY_CHUNK)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionError, OSError, http.client.HTTPException):
            self.close_connection = True

    def _prepare_static_path(self) -> bool:
        raw = SimpleHTTPRequestHandler.translate_path(self, self.path)
        try:
            root = Path(self.directory).resolve(strict=True)
            candidate = Path(raw).resolve(strict=False)
            candidate.relative_to(root)
        except (OSError, ValueError):
            self.send_error(404, "Static path not found")
            return False
        self._resolved_static_path = str(candidate)
        return True

    def translate_path(self, path: str) -> str:
        resolved = getattr(self, "_resolved_static_path", None)
        if resolved is not None and path == self.path:
            return resolved
        return SimpleHTTPRequestHandler.translate_path(self, path)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self._is_proxy_path():
            self._proxy()
        elif self._prepare_static_path():
            super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._is_proxy_path():
            self._proxy()
        elif self._prepare_static_path():
            super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, *_args) -> None:
        return


class _PreviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--backend-port", default=0, type=int)
    parser.add_argument("--bind", default="127.0.0.1", choices=("127.0.0.1",))
    args = parser.parse_args()
    if not (1 <= args.port <= 65535 and 0 <= args.backend_port <= 65535):
        parser.error("ports must be between 1 and 65535 (backend may be 0)")
    static_root = Path(args.dir)
    if static_root.is_symlink():
        parser.error("static directory cannot be a symlink")
    try:
        static_root = static_root.resolve(strict=True)
    except OSError as error:
        parser.error(f"invalid static directory: {error}")
    if not static_root.is_dir():
        parser.error("static directory must exist")
    _ProxyHandler.backend_port = args.backend_port
    handler = partial(_ProxyHandler, directory=str(static_root))
    server = _PreviewHTTPServer((args.bind, args.port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
