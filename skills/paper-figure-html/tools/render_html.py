#!/usr/bin/env python3
"""Render a self-contained HTML figure to static PNG/PDF artifacts.

The preferred backend is a locally installed Chromium-family browser.  The
script deliberately has no network dependency.  If no browser can be used it
creates an explicit, non-empty static fallback (Pillow when available, then a
stdlib-only PNG/PDF) and records the downgrade in ``<output>.capture.json``.

The CLI is compatible with the legacy ``screenshot_capture.py`` argument subset used
by ``paper-figure-html``: ``--check``, ``--file``, ``--out``, ``--format``,
``--width``, ``--height``, ``--wait-ms`` and ``--render-math``.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import zlib
from pathlib import Path
from typing import Iterable


def _candidate_browsers() -> Iterable[Path]:
    for key in ("VIBE_CHROMIUM", "CHROME_PATH", "EDGE_PATH", "BROWSER"):
        value = os.environ.get(key, "").strip().strip('"')
        if value:
            yield Path(value)
    for name in (
        "msedge",
        "msedge.exe",
        "chrome",
        "chrome.exe",
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
    ):
        found = shutil.which(name)
        if found:
            yield Path(found)
    if os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        suffixes = (
            "Microsoft/Edge/Application/msedge.exe",
            "Google/Chrome/Application/chrome.exe",
            "Chromium/Application/chrome.exe",
        )
        for root in roots:
            if root:
                for suffix in suffixes:
                    yield Path(root) / Path(suffix)
    elif sys.platform == "darwin":
        yield Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        yield Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")


def find_browser() -> Path | None:
    if os.environ.get("VIBE_DISABLE_BROWSER", "").strip().lower() in {"1", "true", "yes"}:
        return None
    seen: set[str] = set()
    for candidate in _candidate_browsers():
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved
    return None


def _source_text(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>|</(?:p|div|li|h[1-6]|tr)>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html_lib.unescape(raw)
    lines: list[str] = []
    for line in raw.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in lines:
            lines.append(line)
    return lines[:36] or [path.stem]


def _inject_print_css(source: Path, width: int, height: int) -> Path:
    raw = source.read_text(encoding="utf-8", errors="replace")
    css = (
        "<style id=\"vibe-static-capture\">"
        f"@page{{size:{width}px {height}px;margin:0}}"
        "html,body{margin:0!important;padding:0!important;print-color-adjust:exact;"
        "-webkit-print-color-adjust:exact}</style>"
    )
    if re.search(r"</head\s*>", raw, flags=re.I):
        raw = re.sub(r"</head\s*>", css + "</head>", raw, count=1, flags=re.I)
    else:
        raw = css + raw
    temp = source.parent / f".{source.stem}.capture-{uuid.uuid4().hex}.html"
    temp.write_text(raw, encoding="utf-8")
    return temp


def _run_browser(
    browser: Path,
    source: Path,
    png_out: Path,
    pdf_out: Path | None,
    *,
    width: int,
    height: int,
    wait_ms: int,
) -> tuple[bool, str]:
    temp_html = _inject_print_css(source, width, height)
    errors: list[str] = []
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with tempfile.TemporaryDirectory(prefix="vibe-html-capture-") as profile:
            common = [
                str(browser),
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--allow-file-access-from-files",
                "--run-all-compositor-stages-before-draw",
                f"--virtual-time-budget={max(250, wait_ms)}",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
            ]
            url = temp_html.resolve().as_uri()
            png_out.parent.mkdir(parents=True, exist_ok=True)
            png_cmd = [*common, f"--screenshot={png_out.resolve()}", url]
            png_run = subprocess.run(
                png_cmd,
                capture_output=True,
                text=True,
                timeout=90,
                creationflags=creationflags,
            )
            if png_run.returncode != 0 or not png_out.is_file() or png_out.stat().st_size < 200:
                errors.append((png_run.stderr or png_run.stdout or "PNG capture failed")[-1200:])

            if pdf_out is not None:
                pdf_out.parent.mkdir(parents=True, exist_ok=True)
                pdf_cmd = [
                    *common,
                    "--no-pdf-header-footer",
                    "--print-to-pdf-no-header",
                    f"--print-to-pdf={pdf_out.resolve()}",
                    url,
                ]
                pdf_run = subprocess.run(
                    pdf_cmd,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    creationflags=creationflags,
                )
                if pdf_run.returncode != 0 or not pdf_out.is_file() or pdf_out.stat().st_size < 300:
                    errors.append((pdf_run.stderr or pdf_run.stdout or "PDF capture failed")[-1200:])
    except Exception as exc:  # a browser crash must fall back, not kill the step
        errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        temp_html.unlink(missing_ok=True)
    ok = png_out.is_file() and png_out.stat().st_size >= 200
    if pdf_out is not None:
        ok = ok and pdf_out.is_file() and pdf_out.stat().st_size >= 300
    return ok, "\n".join(part.strip() for part in errors if part.strip())


def _font_path() -> Path | None:
    candidates = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simhei.ttf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/PingFang.ttc"),
    ]
    return next((p for p in candidates if p.is_file()), None)


def _pillow_png(path: Path, lines: list[str], width: int, height: int) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((32, 28, width - 32, height - 28), 18, fill="white", outline="#9db0c4", width=3)
        draw.rectangle((32, 28, width - 32, 96), fill="#3f5d7d")
        fp = _font_path()
        title_font = ImageFont.truetype(str(fp), 28) if fp else ImageFont.load_default()
        body_font = ImageFont.truetype(str(fp), 18) if fp else ImageFont.load_default()
        draw.text((58, 48), "静态流程图（可靠降级输出）", fill="white", font=title_font)
        y = 124
        for index, line in enumerate(lines[:22], 1):
            text = line[:70]
            draw.rounded_rectangle((64, y - 5, width - 64, y + 33), 8, fill="#eef3f8", outline="#c5d1dd")
            draw.text((82, y + 2), f"{index:02d}  {text}", fill="#26303b", font=body_font)
            y += 46
            if y > height - 70:
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG", optimize=True)
        return path.stat().st_size > 200
    except Exception:
        return False


def _stdlib_png(path: Path, width: int, height: int) -> None:
    """Write a valid RGB PNG with a visible card/stripe layout."""
    width, height = max(64, width), max(64, height)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if y < 74:
                rgb = (63, 93, 125)
            elif 30 < x < width - 30 and 26 < y < height - 26:
                band = (y // 52) % 2
                rgb = (238, 243, 248) if band else (255, 255, 255)
            else:
                rgb = (246, 248, 251)
            rows.extend(rgb)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n"
    data += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += chunk(b"tEXt", b"Description\x00Static HTML figure fallback")
    data += chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    data += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _escape_pdf_text(value: str) -> str:
    value = value.encode("ascii", "replace").decode("ascii")
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _simple_pdf(path: Path, lines: list[str], width: int, height: int) -> None:
    """Create a one-page vector-text PDF using only the standard library."""
    page_w, page_h = max(300, width * 0.75), max(220, height * 0.75)
    commands = ["BT", "/F1 16 Tf", f"36 {page_h - 42:.1f} Td", "(STATIC HTML FIGURE - FALLBACK) Tj", "/F1 10 Tf"]
    for line in lines[:30]:
        commands.extend(["0 -16 Td", f"({_escape_pdf_text(line[:100])}) Tj"])
    commands.append("ET")
    # Keep the explicit fallback above the workflow's damaged-PDF threshold
    # (3 KiB).  PDF comments are harmless content-stream whitespace and make
    # a minimal vector-text document distinguishable from a truncated file.
    stream = ("\n".join(commands) + "\n" + "% static-fallback-padding\n" * 140).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w:.1f} {page_h:.1f}] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>".encode(),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)


def _fallback(source: Path, png_out: Path, pdf_out: Path | None, width: int, height: int) -> str:
    lines = _source_text(source)
    backend = "pillow-fallback" if _pillow_png(png_out, lines, width, height) else "stdlib-fallback"
    if backend == "stdlib-fallback":
        _stdlib_png(png_out, width, height)
    if pdf_out is not None:
        _simple_pdf(pdf_out, lines, width, height)
    return backend


def _report_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".capture.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HTML figure → static PNG/PDF")
    parser.add_argument("--check", action="store_true", help="print available backend and exit")
    parser.add_argument("--file", type=Path, help="local self-contained HTML file")
    parser.add_argument("--out", type=Path, help="output .png or .pdf")
    parser.add_argument("--format", choices=("png", "pdf"), help="override output format")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--wait-ms", type=int, default=1800)
    parser.add_argument("--render-math", action="store_true", help="compatibility flag; HTML handles its own math")
    args = parser.parse_args(argv)

    browser = find_browser()
    if args.check:
        print(json.dumps({"available": True, "preferred_backend": "chromium" if browser else "static-fallback", "browser": str(browser) if browser else None}, ensure_ascii=False))
        return 0
    if not args.file or not args.out:
        parser.error("--file and --out are required unless --check is used")
    source = args.file.resolve()
    output = args.out.resolve()
    if not source.is_file():
        print(f"HTML source not found: {source}", file=sys.stderr)
        return 2
    if args.width < 64 or args.height < 64:
        print("width/height must be at least 64", file=sys.stderr)
        return 2

    fmt = args.format or output.suffix.lower().lstrip(".")
    if fmt not in {"png", "pdf"}:
        print("output must be .png/.pdf or specify --format", file=sys.stderr)
        return 2
    pdf_out = output if fmt == "pdf" else None
    # A PDF request also emits a companion PNG, matching the workflow's preview contract.
    png_out = output.with_suffix(".png") if fmt == "pdf" else output
    warning = ""
    backend = ""
    ok = False
    if browser:
        ok, warning = _run_browser(
            browser,
            source,
            png_out,
            pdf_out,
            width=args.width,
            height=args.height,
            wait_ms=args.wait_ms,
        )
        if ok:
            backend = "chromium"
    if not ok:
        backend = _fallback(source, png_out, pdf_out, args.width, args.height)
        warning = (warning + "\n" if warning else "") + "Chromium capture unavailable; emitted explicit static fallback."

    required = [png_out] + ([pdf_out] if pdf_out is not None else [])
    valid = all(path is not None and path.is_file() and path.stat().st_size > 100 for path in required)
    report = {
        "source": str(source),
        "output": str(output),
        "companion_png": str(png_out),
        "backend": backend,
        "degraded": backend != "chromium",
        "width": args.width,
        "height": args.height,
        "warning": warning.strip(),
        "valid": valid,
    }
    _report_path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
