#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import functools
import hashlib
import http.server
import json
import platform
import socketserver
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *args], text=True
    ).strip()


class SmokeHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/favicon.ico":
            self.send_response(http.HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--export-dir", type=Path, default=ROOT / "build" / "web-smoke"
    )
    parser.add_argument(
        "--browser", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--mode", choices=("smoke", "rollback"), default="smoke")
    parser.add_argument(
        "--profile", choices=("web_core", "web_extended"), default="web_core"
    )
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--evidence-dir", type=Path, default=ROOT / "build" / "evidence"
    )
    parser.add_argument("--browser-toolchain-receipt", type=Path)
    parser.add_argument("--template-receipt", type=Path)
    return parser.parse_args()


def load_receipt(
    path: Path | None, expected_schema: str, label: str
) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read {label} {resolved}: {error}") from error
    if not isinstance(value, dict) or value.get("schema") != expected_schema:
        raise SystemExit(f"Unexpected {label} schema: {resolved}")
    value["receipt_sha256"] = sha256(resolved)
    return value


async def run_browser(args: argparse.Namespace, url: str) -> dict[str, object]:
    console: list[dict[str, str]] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    http_errors: list[str] = []
    async with async_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = await browser_type.launch(headless=not args.headed)
        browser_version = browser.version
        page = await browser.new_page(viewport={"width": 640, "height": 360})
        page.on(
            "console",
            lambda message: console.append(
                {"type": message.type, "text": message.text}
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "requestfailed",
            lambda request: request_failures.append(
                f"{request.url}: {request.failure or 'request failed'}"
            ),
        )
        page.on(
            "response",
            lambda response: http_errors.append(
                f"{response.status} {response.url}"
            )
            if response.status >= 400
            else None,
        )
        started = time.monotonic()
        await page.goto(url, wait_until="domcontentloaded", timeout=int(args.timeout * 1000))
        marker = ""
        success_marker = (
            "MTERRAIN_WEB_SMOKE_OK"
            if args.mode == "smoke"
            else "MTERRAIN_WEB_ROLLBACK_OK"
        )
        failure_marker = (
            "MTERRAIN_WEB_SMOKE_FAILED"
            if args.mode == "smoke"
            else "MTERRAIN_WEB_ROLLBACK_FAILED"
        )
        while time.monotonic() - started < args.timeout:
            marker = next(
                (
                    entry["text"]
                    for entry in console
                    if success_marker in entry["text"]
                ),
                "",
            )
            if marker:
                break
            if any(failure_marker in entry["text"] for entry in console):
                break
            await page.wait_for_timeout(100)
        # Console events can be delivered between the final loop condition and
        # the report snapshot, especially in software-rendered Firefox.
        marker = next(
            (
                entry["text"]
                for entry in console
                if success_marker in entry["text"]
            ),
            marker,
        )
        if marker:
            # The marker is emitted from _ready() before every browser has
            # presented its first completed WebGL frame. Leave one bounded
            # render interval so the screenshot is visual evidence, not merely
            # proof that script initialization ran.
            await page.wait_for_timeout(1000)
        canvas = page.locator("canvas")
        await canvas.wait_for(state="visible", timeout=int(args.timeout * 1000))
        box = await canvas.bounding_box()
        frame_probe = await page.evaluate(
            """
            () => new Promise((resolve) => requestAnimationFrame(() => {
                const canvas = document.querySelector("canvas");
                const gl = canvas ? canvas.getContext("webgl2") : null;
                if (!canvas || !gl) {
                    resolve({ok: false, reason: "webgl2_context_unavailable"});
                    return;
                }
                const width = canvas.width;
                const height = canvas.height;
                const debugInfo = gl.getExtension("WEBGL_debug_renderer_info");
                const renderer = debugInfo
                    ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                    : gl.getParameter(gl.RENDERER);
                const vendor = debugInfo
                    ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
                    : gl.getParameter(gl.VENDOR);
                const pixels = new Uint8Array(width * height * 4);
                gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
                let channelMin = 255;
                let channelMax = 0;
                const buckets = new Set();
                for (let index = 0; index < pixels.length; index += 4) {
                    const red = pixels[index];
                    const green = pixels[index + 1];
                    const blue = pixels[index + 2];
                    channelMin = Math.min(channelMin, red, green, blue);
                    channelMax = Math.max(channelMax, red, green, blue);
                    buckets.add(`${red >> 4},${green >> 4},${blue >> 4}`);
                }
                const capture = document.createElement("canvas");
                capture.width = width;
                capture.height = height;
                const captureContext = capture.getContext("2d");
                const imageData = captureContext.createImageData(width, height);
                const rowBytes = width * 4;
                for (let y = 0; y < height; y += 1) {
                    const sourceStart = (height - 1 - y) * rowBytes;
                    imageData.data.set(
                        pixels.subarray(sourceStart, sourceStart + rowBytes),
                        y * rowBytes,
                    );
                }
                captureContext.putImageData(imageData, 0, 0);
                resolve({
                    ok: gl.getError() === gl.NO_ERROR,
                    width,
                    height,
                    channel_min: channelMin,
                    channel_max: channelMax,
                    color_bucket_count: buckets.size,
                    renderer,
                    vendor,
                    user_agent: navigator.userAgent,
                    frame_data_url: capture.toDataURL("image/png"),
                });
            }))
            """
        )
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        frame_data_url = str(frame_probe.pop("frame_data_url", ""))
        frame_prefix = "data:image/png;base64,"
        framebuffer_capture = (
            args.evidence_dir / f"web-smoke-{args.browser}-framebuffer.png"
        )
        framebuffer_capture_written = False
        if frame_data_url.startswith(frame_prefix):
            framebuffer_capture.write_bytes(
                base64.b64decode(
                    frame_data_url.removeprefix(frame_prefix), validate=True
                )
            )
            framebuffer_capture_written = True
        screenshot = args.evidence_dir / f"web-smoke-{args.browser}.png"
        await page.screenshot(path=str(screenshot))
        # Firefox can batch the console callback until the WebGL readback or
        # screenshot yields to its event loop. Re-sample after both operations
        # so an on-time success marker cannot be misreported as absent.
        marker = next(
            (
                entry["text"]
                for entry in console
                if success_marker in entry["text"]
            ),
            marker,
        )
        await browser.close()

    report: dict[str, object] = {
        "schema": "mterrain-web-smoke-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "commit": git("rev-parse", "HEAD"),
            "tree": git("rev-parse", "HEAD^{tree}"),
            "dirty": bool(
                git(
                    "status",
                    "--porcelain",
                    "--untracked-files=normal",
                    "--ignore-submodules=dirty",
                )
            ),
        },
        "host": platform.platform(),
        "browser": args.browser,
        "mode": args.mode,
        "browser_version": browser_version,
        "headless": not args.headed,
        "viewport": {"width": 640, "height": 360},
        "url": url,
        "success_marker": marker,
        "canvas_box": box,
        "console": console,
        "page_errors": page_errors,
        "request_failures": request_failures,
        "http_errors": http_errors,
        "frame_probe": frame_probe,
        "framebuffer_capture": (
            str(framebuffer_capture) if framebuffer_capture_written else None
        ),
        "screenshot": str(screenshot),
        "web_side_module": {
            "name": "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
            "sha256": sha256(
                args.export_dir
                / "libMTerrain.web.template_debug.wasm32.nothreads.wasm"
            ),
        },
        "browser_toolchain_receipt": args.browser_toolchain_receipt,
        "template_receipt": args.template_receipt,
    }
    console_errors = [
        entry["text"] for entry in console if entry["type"] == "error"
    ]
    report["console_errors"] = console_errors
    frame_is_nonblank = bool(frame_probe.get("ok")) and int(
        frame_probe.get("color_bucket_count", 0)
    ) >= 2
    required_tokens = [
        "initialized_tile_samples=4489",
        "rejected_non_finite=1",
    ]
    if args.mode == "smoke":
        required_tokens.extend(
            [
                "rejected_border=1",
                "lod_transitions=1",
                "recreate=1",
                "phase_timings=1",
                "scheduler_visual=1",
            ]
        )
    else:
        required_tokens.extend(
            [
                "bounded_scheduler=1",
                "bounded_collision=1",
                "eviction_recovery=1",
                f"profile={args.profile}",
                f"extended_companion={int(args.profile == 'web_extended')}",
            ]
        )
    passed = not (
        not marker
        or any(token not in marker for token in required_tokens)
        or not frame_is_nonblank
        or console_errors
        or page_errors
        or request_failures
        or http_errors
        or not box
        or not framebuffer_capture_written
    )
    report["passed"] = passed
    return report


def main() -> int:
    args = parse_args()
    export_dir = args.export_dir.expanduser().resolve()
    args.export_dir = export_dir
    args.evidence_dir = args.evidence_dir.expanduser().resolve()
    args.browser_toolchain_receipt = load_receipt(
        args.browser_toolchain_receipt,
        "mterrain-browser-toolchain-receipt-v2",
        "browser toolchain receipt",
    )
    args.template_receipt = load_receipt(
        args.template_receipt,
        "mterrain-web-template-receipt-v1",
        "Web template receipt",
    )
    if args.browser_toolchain_receipt is not None:
        browser_records = args.browser_toolchain_receipt["playwright"]["browsers"]
        if args.browser not in browser_records:
            raise SystemExit(
                f"Browser toolchain receipt omitted requested {args.browser}"
            )
    if not (export_dir / "index.html").is_file():
        raise SystemExit(f"Web smoke export is missing: {export_dir}")
    handler = functools.partial(SmokeHandler, directory=str(export_dir))
    report: dict[str, object]
    with ThreadingServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
            try:
                report = asyncio.run(run_browser(args, url))
            except Exception as error:
                report = {
                    "schema": "mterrain-web-smoke-v1",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "source": {
                        "commit": git("rev-parse", "HEAD"),
                        "tree": git("rev-parse", "HEAD^{tree}"),
                        "dirty": bool(
                            git(
                                "status",
                                "--porcelain",
                                "--untracked-files=normal",
                                "--ignore-submodules=dirty",
                            )
                        ),
                    },
                    "browser": args.browser,
                    "mode": args.mode,
                    "headless": not args.headed,
                    "harness_error_type": type(error).__name__,
                    "harness_error": str(error).splitlines()[0][:512],
                    "browser_toolchain_receipt": args.browser_toolchain_receipt,
                    "template_receipt": args.template_receipt,
                    "passed": False,
                }
        finally:
            server.shutdown()
            thread.join()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.evidence_dir / f"web-{args.mode}-{args.browser}.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report_path)
    if report.get("passed") is not True:
        raise SystemExit(f"Web {args.mode} evidence did not pass: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
