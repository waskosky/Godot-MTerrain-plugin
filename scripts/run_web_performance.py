#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import functools
import json
import platform
import threading
import time
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from run_web_smoke import SmokeHandler, ThreadingServer, git
from web_evidence_common import (
    evaluate_budgets,
    extended_runtime_measurements,
    fixture_contract_passes,
    frame_summary,
    load_object,
    required_budget_results_pass,
    runtime_export_payload_valid,
    sha256,
    threshold_contract_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = ROOT / "tools" / "web_performance_budgets.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--export-dir", type=Path, default=ROOT / "build" / "web-performance"
    )
    parser.add_argument(
        "--browser", choices=("chromium", "chrome", "firefox", "webkit"),
        default="chromium",
    )
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--timeout", type=float, default=360.0)
    parser.add_argument(
        "--evidence-dir", type=Path, default=ROOT / "build" / "evidence"
    )
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument(
        "--budget-profile",
        choices=("desktop_balanced", "mobile_balanced"),
        default="desktop_balanced",
    )
    parser.add_argument(
        "--build-receipt",
        type=Path,
        default=ROOT / "build" / "receipts" / "web-template_debug.json",
    )
    parser.add_argument("--template-receipt", type=Path, required=True)
    parser.add_argument("--browser-toolchain-receipt", type=Path)
    parser.add_argument(
        "--environment-kind",
        choices=("ci_headless", "headed_desktop"),
        default="ci_headless",
    )
    parser.add_argument("--device-label", default="unspecified")
    parser.add_argument("--physical-device", action="store_true")
    return parser.parse_args()


def browser_product(requested: str) -> str:
    return {
        "chrome": "google_chrome",
        "chromium": "playwright_chromium",
        "firefox": "playwright_firefox",
        "webkit": "playwright_webkit_not_safari",
    }[requested]


async def execute(args: argparse.Namespace, url: str) -> dict[str, Any]:
    console: list[dict[str, str]] = []
    page_errors: list[str] = []
    request_failures: list[str] = []
    http_errors: list[str] = []
    fixture_started_at: float | None = None
    navigation_started = time.monotonic()

    async with async_playwright() as playwright:
        if args.browser == "chrome":
            browser_type = playwright.chromium
            browser = await browser_type.launch(headless=not args.headed, channel="chrome")
        else:
            browser_type = getattr(playwright, args.browser)
            browser = await browser_type.launch(headless=not args.headed)
        browser_version = browser.version
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.add_init_script(
            """
            globalThis.__mterrainFrameSamples = [];
            globalThis.__mterrainLastFrame = undefined;
            const collectMTerrainFrame = (now) => {
                if (globalThis.__mterrainLastFrame !== undefined) {
                    globalThis.__mterrainFrameSamples.push({
                        at: now,
                        delta: now - globalThis.__mterrainLastFrame,
                    });
                }
                globalThis.__mterrainLastFrame = now;
                requestAnimationFrame(collectMTerrainFrame);
            };
            requestAnimationFrame(collectMTerrainFrame);
            """
        )

        def on_console(message: Any) -> None:
            nonlocal fixture_started_at
            entry = {"type": message.type, "text": message.text}
            console.append(entry)
            if "MTERRAIN_WEB_PERFORMANCE_STARTED" in message.text:
                fixture_started_at = time.monotonic()

        page.on("console", on_console)
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
        await page.goto(
            url, wait_until="domcontentloaded", timeout=int(args.timeout * 1000)
        )
        success_text = ""
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            success_text = next(
                (
                    item["text"]
                    for item in console
                    if "MTERRAIN_WEB_PERFORMANCE_OK" in item["text"]
                ),
                "",
            )
            if success_text or any(
                "MTERRAIN_WEB_PERFORMANCE_FAILED" in item["text"]
                for item in console
            ):
                break
            await page.wait_for_timeout(100)
        if not success_text:
            raise RuntimeError(
                json.dumps(
                    {
                        "console": console,
                        "page_errors": page_errors,
                        "request_failures": request_failures,
                    },
                    indent=2,
                )
            )
        fixture = json.loads(
            success_text.split("MTERRAIN_WEB_PERFORMANCE_OK", 1)[1].strip()
        )
        browser_probe = await page.evaluate(
            """
            () => {
                const canvas = document.querySelector("canvas");
                const gl = canvas ? canvas.getContext("webgl2") : null;
                const debugInfo = gl
                    ? gl.getExtension("WEBGL_debug_renderer_info")
                    : null;
                const start = globalThis.__mterrainTraversalStart || 0;
                const end = globalThis.__mterrainTraversalEnd || performance.now();
                const frames = (globalThis.__mterrainFrameSamples || [])
                    .filter((sample) => sample.at >= start && sample.at <= end)
                    .map((sample) => sample.delta);
                const memory = performance.memory || null;
                return {
                    traversal_start_ms: start,
                    traversal_end_ms: end,
                    frame_deltas_ms: frames,
                    renderer: gl
                        ? (debugInfo
                            ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                            : gl.getParameter(gl.RENDERER))
                        : "",
                    vendor: gl
                        ? (debugInfo
                            ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
                            : gl.getParameter(gl.VENDOR))
                        : "",
                    webgl_error: gl ? gl.getError() : -1,
                    user_agent: navigator.userAgent,
                    javascript_heap_bytes: memory ? memory.usedJSHeapSize : null,
                    resources: performance.getEntriesByType("resource").map((entry) => ({
                        name: entry.name.split("/").pop(),
                        duration_ms: entry.duration,
                        transfer_bytes: entry.transferSize,
                        encoded_bytes: entry.encodedBodySize,
                        decoded_bytes: entry.decodedBodySize,
                    })),
                };
            }
            """
        )
        args.evidence_dir.mkdir(parents=True, exist_ok=True)
        screenshot = args.evidence_dir / f"web-performance-{args.browser}.png"
        await page.screenshot(path=str(screenshot))
        await browser.close()

    frame_deltas = [float(value) for value in browser_probe.pop("frame_deltas_ms")]
    if len(frame_deltas) < 120:
        raise RuntimeError(f"Traversal produced only {len(frame_deltas)} frame samples")
    startup_ms = (
        (fixture_started_at - navigation_started) * 1000.0
        if fixture_started_at is not None
        else -1.0
    )
    return {
        "browser_version": browser_version,
        "browser_probe": browser_probe,
        "console": console,
        "console_errors": [item["text"] for item in console if item["type"] == "error"],
        "fixture": fixture,
        "frame_time_ms": frame_summary(frame_deltas),
        "http_errors": http_errors,
        "page_errors": page_errors,
        "request_failures": request_failures,
        "screenshot": str(screenshot),
        "startup_ms": startup_ms,
    }


def main() -> int:
    args = parse_args()
    if args.environment_kind == "headed_desktop" and not args.headed:
        raise SystemExit("headed_desktop evidence requires --headed")
    if args.environment_kind == "ci_headless" and args.headed:
        raise SystemExit("--headed evidence must use environment-kind headed_desktop")
    if args.physical_device and not args.headed:
        raise SystemExit("physical-device evidence must be headed")
    args.export_dir = args.export_dir.expanduser().resolve()
    args.evidence_dir = args.evidence_dir.expanduser().resolve()
    if not (args.export_dir / "index.html").is_file():
        raise SystemExit(f"Web performance export is missing: {args.export_dir}")
    budgets_path = args.budgets.expanduser().resolve()
    budgets = load_object(budgets_path, "performance budgets")
    if budgets.get("schema") != "mterrain-web-performance-budgets-v1":
        raise SystemExit("Unexpected performance-budget schema")
    limits = budgets.get("profiles", {}).get(args.budget_profile)
    if not isinstance(limits, dict):
        raise SystemExit(f"Budget profile is missing: {args.budget_profile}")
    build_receipt_path = args.build_receipt.expanduser().resolve()
    build_receipt = load_object(build_receipt_path, "Web build receipt")
    if build_receipt.get("schema") != "mterrain-web-build-receipt-v2":
        raise SystemExit("Unexpected Web build receipt schema")
    artifact = args.export_dir / str(build_receipt.get("artifact", {}).get("name", ""))
    if not artifact.is_file() or sha256(artifact) != build_receipt["artifact"]["sha256"]:
        raise SystemExit("Exported side module does not match its build receipt")
    template_receipt_path = args.template_receipt.expanduser().resolve()
    template_receipt = load_object(template_receipt_path, "template receipt")
    if template_receipt.get("schema") != "mterrain-web-template-receipt-v1":
        raise SystemExit("Unexpected Web template receipt schema")
    performance_context = load_object(
        args.export_dir / "mterrain_performance_context.json",
        "performance export context",
    )
    if (
        performance_context.get("schema") != "mterrain-web-performance-context-v1"
        or performance_context.get("profile") != build_receipt["target"]["profile"]
        or performance_context.get("source") != build_receipt.get("source")
        or performance_context.get("build_receipt", {}).get("sha256")
        != sha256(build_receipt_path)
        or performance_context.get("build_receipt", {}).get("artifact_sha256")
        != build_receipt["artifact"]["sha256"]
        or performance_context.get("template_receipt", {}).get("sha256")
        != sha256(template_receipt_path)
        or performance_context.get("template_receipt", {}).get("artifact_sha256")
        != template_receipt.get("artifact", {}).get("sha256")
        or performance_context.get("performance_budget", {}).get("sha256")
        != sha256(budgets_path)
        or performance_context.get("performance_budget", {}).get(
            "threshold_contract_sha256"
        )
        != threshold_contract_sha256(budgets)
        or not runtime_export_payload_valid(
            performance_context.get("runtime_export_payload")
        )
    ):
        raise SystemExit("Performance export context does not match its receipts")

    handler = functools.partial(SmokeHandler, directory=str(args.export_dir))
    with ThreadingServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
            run = asyncio.run(execute(args, url))
        finally:
            server.shutdown()
            thread.join()

    fixture = run["fixture"]
    frame = run["frame_time_ms"]
    probe = run["browser_probe"]
    measurements: dict[str, float | int | None] = {
        "compressed_side_module_bytes": build_receipt["artifact"]["brotli"]["size"],
        "compressed_runtime_export_bytes": performance_context[
            "runtime_export_payload"
        ]["gzip_bytes"],
        "scheduler_longest_step_ms": float(
            fixture.get("scheduler_metrics", {}).get("longest_step_usec", -1000)
        )
        / 1000.0,
        "startup_ms": run["startup_ms"],
        "first_tile_ms": float(fixture["first_tile_usec"]) / 1000.0,
        "first_collision_ms": float(fixture["first_collision_usec"]) / 1000.0,
        "p50_frame_ms": frame["p50"],
        "p95_frame_ms": frame["p95"],
        "p99_frame_ms": frame["p99"],
        "longest_frame_ms": frame["longest"],
        "javascript_heap_bytes": probe.get("javascript_heap_bytes"),
        "estimated_region_bytes": fixture["max_estimated_region_bytes"],
        "resident_regions": fixture["max_loaded_regions"],
        "collision_regions": fixture["max_collision_regions"],
        "eviction_recovery_ms": float(fixture["eviction_recovery_usec"]) / 1000.0,
    }
    measurements.update(extended_runtime_measurements(fixture))
    budget_results = evaluate_budgets(measurements, limits)
    passed = (
        required_budget_results_pass(budget_results)
        and not run["console_errors"]
        and not run["page_errors"]
        and not run["request_failures"]
        and not run["http_errors"]
        and int(probe.get("webgl_error", -1)) == 0
        and fixture_contract_passes(
            fixture,
            budgets["fixture"],
            expected_profile=build_receipt["target"]["profile"],
        )
    )
    browser_toolchain_receipt: dict[str, Any] | None = None
    if args.browser_toolchain_receipt is not None:
        browser_toolchain_receipt = load_object(
            args.browser_toolchain_receipt, "browser toolchain receipt"
        )
        if browser_toolchain_receipt.get("schema") != (
            "mterrain-browser-toolchain-receipt-v2"
        ):
            raise SystemExit("Unexpected browser toolchain receipt schema")
        receipt_browser = "chromium" if args.browser == "chrome" else args.browser
        if receipt_browser not in browser_toolchain_receipt["playwright"]["browsers"]:
            raise SystemExit("Browser toolchain receipt omitted the requested engine")
    report = {
        "schema": "mterrain-web-performance-evidence-v1",
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
        "profile": build_receipt["target"]["profile"],
        "environment": {
            "kind": args.environment_kind,
            "device_label": args.device_label,
            "physical_device": args.physical_device,
            "host": platform.platform(),
            "headed": args.headed,
            "browser_requested": args.browser,
            "browser_product": browser_product(args.browser),
            "browser_version": run["browser_version"],
            "viewport": {"width": 1280, "height": 720},
            "renderer": probe.get("renderer"),
            "vendor": probe.get("vendor"),
            "user_agent": probe.get("user_agent"),
        },
        "budget": {
            "path": (
                str(budgets_path.relative_to(ROOT))
                if budgets_path.is_relative_to(ROOT)
                else budgets_path.name
            ),
            "sha256": sha256(budgets_path),
            "threshold_contract_sha256": threshold_contract_sha256(budgets),
            "profile": args.budget_profile,
            "results": budget_results,
        },
        "build_receipt": build_receipt,
        "template_receipt": template_receipt,
        "browser_toolchain_receipt": browser_toolchain_receipt,
        "measurements": measurements,
        "frame_time_ms": frame,
        "fixture": fixture,
        "performance_context": performance_context,
        "browser_probe": probe,
        "resource_timings": probe.get("resources", []),
        "console": run["console"],
        "console_errors": run["console_errors"],
        "page_errors": run["page_errors"],
        "request_failures": run["request_failures"],
        "http_errors": run["http_errors"],
        "screenshot": run["screenshot"],
        "passed": passed,
    }
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.evidence_dir / f"web-performance-{args.browser}.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(report_path)
    if not passed:
        raise SystemExit("Web performance evidence did not pass its provisional budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
