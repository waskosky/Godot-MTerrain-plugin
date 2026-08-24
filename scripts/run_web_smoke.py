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
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--evidence-dir", type=Path, default=ROOT / "build" / "evidence"
    )
    return parser.parse_args()


async def run_browser(args: argparse.Namespace, url: str) -> dict[str, object]:
    console: list[dict[str, str]] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    async with async_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = await browser_type.launch(headless=True)
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
        started = time.monotonic()
        await page.goto(url, wait_until="domcontentloaded", timeout=int(args.timeout * 1000))
        marker = ""
        while time.monotonic() - started < args.timeout:
            marker = next(
                (
                    entry["text"]
                    for entry in console
                    if "MTERRAIN_WEB_SMOKE_OK" in entry["text"]
                ),
                "",
            )
            if marker:
                break
            if any("MTERRAIN_WEB_SMOKE_FAILED" in entry["text"] for entry in console):
                break
            await page.wait_for_timeout(100)
        # Console events can be delivered between the final loop condition and
        # the report snapshot, especially in software-rendered Firefox.
        marker = next(
            (
                entry["text"]
                for entry in console
                if "MTERRAIN_WEB_SMOKE_OK" in entry["text"]
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
        if not frame_data_url.startswith(frame_prefix):
            raise RuntimeError("WebGL framebuffer capture did not produce a PNG")
        framebuffer_capture = (
            args.evidence_dir / f"web-smoke-{args.browser}-framebuffer.png"
        )
        framebuffer_capture.write_bytes(
            base64.b64decode(frame_data_url.removeprefix(frame_prefix), validate=True)
        )
        screenshot = args.evidence_dir / f"web-smoke-{args.browser}.png"
        await page.screenshot(path=str(screenshot))
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
        "browser_version": browser_version,
        "headless": True,
        "viewport": {"width": 640, "height": 360},
        "url": url,
        "success_marker": marker,
        "canvas_box": box,
        "console": console,
        "page_errors": page_errors,
        "request_failures": request_failures,
        "frame_probe": frame_probe,
        "framebuffer_capture": str(framebuffer_capture),
        "screenshot": str(screenshot),
        "web_side_module": {
            "name": "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
            "sha256": sha256(
                args.export_dir
                / "libMTerrain.web.template_debug.wasm32.nothreads.wasm"
            ),
        },
    }
    console_errors = [
        entry["text"] for entry in console if entry["type"] == "error"
    ]
    report["console_errors"] = console_errors
    frame_is_nonblank = bool(frame_probe.get("ok")) and int(
        frame_probe.get("color_bucket_count", 0)
    ) >= 2
    if (
        not marker
        or "initialized_tile_samples=4489" not in marker
        or "rejected_non_finite=1" not in marker
        or not frame_is_nonblank
        or console_errors
        or page_errors
        or request_failures
        or not box
    ):
        raise RuntimeError(json.dumps(report, indent=2))
    return report


def main() -> int:
    args = parse_args()
    export_dir = args.export_dir.expanduser().resolve()
    args.export_dir = export_dir
    args.evidence_dir = args.evidence_dir.expanduser().resolve()
    if not (export_dir / "index.html").is_file():
        raise SystemExit(f"Web smoke export is missing: {export_dir}")
    handler = functools.partial(SmokeHandler, directory=str(export_dir))
    with ThreadingServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
            report = asyncio.run(run_browser(args, url))
        finally:
            server.shutdown()
            thread.join()
    report_path = args.evidence_dir / f"web-smoke-{args.browser}.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
