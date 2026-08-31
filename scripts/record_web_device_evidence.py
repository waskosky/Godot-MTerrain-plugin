#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from web_evidence_common import (
    BROWSER_PRODUCTS,
    bounded_text,
    browser_version_matches,
    evaluate_budgets,
    extended_runtime_measurements,
    fixture_contract_passes,
    frame_summary,
    load_object,
    operating_system_matches,
    required_budget_results_pass,
    runtime_export_payload_valid,
    sha256,
    software_renderer,
    threshold_contract_sha256,
    user_agent_matches,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUDGETS = ROOT / "tools" / "web_performance_budgets.json"
DEFAULT_GATE = ROOT / "tools" / "web_release_gate.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--build-receipt", required=True, type=Path)
    parser.add_argument("--template-receipt", required=True, type=Path)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--profile", choices=("web_core", "web_extended"), default="web_core")
    parser.add_argument("--browser-product", choices=BROWSER_PRODUCTS, required=True)
    parser.add_argument("--browser-version", required=True)
    parser.add_argument("--operating-system", required=True)
    parser.add_argument("--device-label", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--physical-device", action="store_true")
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def lane_contract(gate: dict[str, Any], profile: str, lane: str) -> dict[str, Any]:
    profile_contract = gate["stable_profiles"].get(profile)
    if not isinstance(profile_contract, dict):
        raise SystemExit(f"Release gate omitted profile {profile}")
    if "inherits_lane_shape_from" in profile_contract:
        profile_contract = gate["stable_profiles"][
            profile_contract["inherits_lane_shape_from"]
        ]
    lanes = profile_contract.get("performance_lanes", {})
    if lane not in lanes:
        raise SystemExit(f"Unknown stable performance lane: {lane}")
    return lanes[lane]


def main() -> int:
    args = parse_args()
    gate_path = args.gate.expanduser().resolve()
    budgets_path = args.budgets.expanduser().resolve()
    gate = load_object(gate_path, "release gate")
    budgets = load_object(budgets_path, "performance budgets")
    if gate.get("schema") != "mterrain-web-release-gate-v1":
        raise SystemExit("Unexpected Web release-gate schema")
    if budgets.get("schema") != "mterrain-web-performance-budgets-v1":
        raise SystemExit("Unexpected Web performance-budget schema")
    lane = lane_contract(gate, args.profile, args.lane)
    if args.browser_product not in lane["browser_products"]:
        raise SystemExit("Browser product does not satisfy the selected release lane")
    if args.headed is not lane["headed"]:
        raise SystemExit("Headed state does not satisfy the selected release lane")
    if args.physical_device is not lane["physical_device"]:
        raise SystemExit("Physical-device state does not satisfy the selected release lane")

    capture_path = args.capture.expanduser().resolve()
    capture = load_object(capture_path, "browser capture")
    if capture.get("schema") != "mterrain-browser-capture-v1":
        raise SystemExit("Unexpected browser-capture schema")
    fixture = capture.get("fixture")
    environment = capture.get("environment")
    timing = capture.get("timing")
    context = capture.get("context")
    if not all(
        isinstance(value, dict) for value in (fixture, environment, timing, context)
    ):
        raise SystemExit(
            "Browser capture omitted context, fixture, timing, or environment data"
        )
    if environment.get("ok") is not True or environment.get("webgl_error") != 0:
        raise SystemExit("Browser capture did not retain a healthy WebGL2 context")
    color_buckets = environment.get("color_bucket_count")
    if (
        not isinstance(color_buckets, int)
        or isinstance(color_buckets, bool)
        or color_buckets < 2
    ):
        raise SystemExit("Browser capture framebuffer was blank")
    if capture.get("console_errors") or capture.get("page_errors"):
        raise SystemExit("Browser capture recorded console or page errors")
    resources = capture.get("resources")
    if (
        not isinstance(resources, list)
        or not resources
        or any(
            not isinstance(record, dict)
            or not isinstance(record.get("response_status"), (int, float))
            or isinstance(record.get("response_status"), bool)
            or record.get("response_status") >= 400
            for record in resources
        )
    ):
        raise SystemExit("Browser capture omitted resource timing or recorded HTTP errors")
    renderer_value = environment.get("renderer")
    vendor_value = environment.get("vendor")
    if not isinstance(renderer_value, str) or not isinstance(vendor_value, str):
        raise SystemExit("Browser capture omitted its renderer identity")
    renderer = bounded_text(renderer_value, "renderer")
    if software_renderer(renderer):
        raise SystemExit("Software rendering is not representative hardware evidence")
    vendor = bounded_text(vendor_value, "renderer vendor")
    viewport = environment.get("viewport")
    if not isinstance(viewport, dict) or any(
        not isinstance(viewport.get(axis), (int, float))
        or isinstance(viewport.get(axis), bool)
        or viewport.get(axis) <= 0
        for axis in ("width", "height")
    ):
        raise SystemExit("Browser capture omitted a valid viewport")
    user_agent = bounded_text(str(environment.get("user_agent", "")), "user agent", 512)
    if not user_agent_matches(args.browser_product, user_agent):
        raise SystemExit("Browser-product attestation conflicts with the captured user agent")
    browser_version = bounded_text(args.browser_version, "browser version")
    if not browser_version_matches(args.browser_product, browser_version, user_agent):
        raise SystemExit("Browser-version attestation conflicts with the captured user agent")
    operating_system = bounded_text(args.operating_system, "operating system")
    if not operating_system_matches(
        lane["environment_kind"], args.browser_product, operating_system
    ):
        raise SystemExit("Operating-system attestation conflicts with the release lane")
    frames = timing.get("frame_samples_ms")
    if not isinstance(frames, list):
        raise SystemExit("Browser capture omitted frame samples")
    frame = frame_summary(frames)

    build_receipt_path = args.build_receipt.expanduser().resolve()
    template_receipt_path = args.template_receipt.expanduser().resolve()
    build_receipt = load_object(build_receipt_path, "Web build receipt")
    template_receipt = load_object(template_receipt_path, "Web template receipt")
    if build_receipt.get("schema") != "mterrain-web-build-receipt-v2":
        raise SystemExit("Unexpected Web build-receipt schema")
    if template_receipt.get("schema") != "mterrain-web-template-receipt-v1":
        raise SystemExit("Unexpected Web template-receipt schema")
    if build_receipt.get("target", {}).get("profile") != args.profile:
        raise SystemExit("Build receipt does not match the requested runtime profile")
    if build_receipt.get("source", {}).get("mterrain_dirty") is not False:
        raise SystemExit("Stable evidence requires a clean MTerrain build receipt")
    if template_receipt.get("source", {}).get("tracked_dirty") is not False:
        raise SystemExit("Stable evidence requires a clean Godot template receipt")
    expected_godot = build_receipt["toolchain"]["pins"]["godot"]["version"]
    if template_receipt.get("target", {}).get("godot") != expected_godot:
        raise SystemExit("Side module and export template use different Godot versions")
    if context.get("schema") != "mterrain-web-performance-context-v1":
        raise SystemExit("Unexpected Web performance-context schema")
    if context.get("profile") != args.profile:
        raise SystemExit("Browser capture used a different runtime profile")
    if context.get("source") != build_receipt.get("source"):
        raise SystemExit("Browser capture source differs from its build receipt")
    fixture_source = context.get("fixture_source", {})
    expected_fixture_source = {
        "commit": build_receipt["source"]["mterrain_commit"],
        "tree": build_receipt["source"]["mterrain_tree"],
        "dirty": False,
    }
    fixture_files = fixture_source.get("files", {})
    if (
        fixture_source.get("source") != expected_fixture_source
        or not isinstance(fixture_files, dict)
        or set(fixture_files)
        != {
            "tests/web_performance/main.gd",
            "tests/web_performance/evidence_bridge.js",
            "tests/web_smoke/main.tscn",
            "tests/web_smoke/main.gd.uid",
            "tests/web_smoke/project.godot",
            "tests/web_smoke/fixtures/grass_cluster.obj",
            "tests/web_smoke/fixtures/grass_cluster.obj.import",
            "tests/web_smoke/fixtures/grass_material.tres",
            "tests/web_smoke/fixtures/road_strip.obj",
            "tests/web_smoke/fixtures/road_strip.obj.import",
            "tests/web_smoke/fixtures/road_material.tres",
            "tests/web_smoke/fixtures/road_collision.tres",
            "tests/web_smoke/fixtures/rock_near.obj",
            "tests/web_smoke/fixtures/rock_near.obj.import",
            "tests/web_smoke/fixtures/rock_far.obj",
            "tests/web_smoke/fixtures/rock_far.obj.import",
            "tests/web_smoke/fixtures/walkable_nav.tres",
        }
        or not all(
            isinstance(value, str) and len(value) == 64
            for value in fixture_files.values()
        )
    ):
        raise SystemExit("Browser capture used an unbound or dirty traversal fixture")
    captured_build = context.get("build_receipt", {})
    if (
        captured_build.get("sha256") != sha256(build_receipt_path)
        or captured_build.get("artifact_sha256")
        != build_receipt.get("artifact", {}).get("sha256")
    ):
        raise SystemExit("Browser capture used a different Web side module or receipt")
    captured_template = context.get("template_receipt", {})
    if (
        captured_template.get("sha256") != sha256(template_receipt_path)
        or captured_template.get("artifact_sha256")
        != template_receipt.get("artifact", {}).get("sha256")
    ):
        raise SystemExit("Browser capture used a different Web export template")
    captured_budget = context.get("performance_budget", {})
    if (
        captured_budget.get("sha256") != sha256(budgets_path)
        or captured_budget.get("threshold_contract_sha256")
        != threshold_contract_sha256(budgets)
    ):
        raise SystemExit("Browser capture used a different performance-budget contract")
    runtime_payload = context.get("runtime_export_payload")
    if not runtime_export_payload_valid(runtime_payload):
        raise SystemExit("Browser capture omitted its bounded runtime export payload")

    budget_profile = lane["budget_profile"]
    limits = budgets.get("profiles", {}).get(budget_profile)
    if not isinstance(limits, dict):
        raise SystemExit(f"Budget profile is missing: {budget_profile}")
    measurements: dict[str, float | int | None] = {
        "compressed_side_module_bytes": build_receipt["artifact"]["brotli"]["size"],
        "compressed_runtime_export_bytes": runtime_payload["gzip_bytes"],
        "scheduler_longest_step_ms": float(
            fixture.get("scheduler_metrics", {}).get("longest_step_usec", -1000)
        )
        / 1000.0,
        "startup_ms": timing.get("startup_ms"),
        "first_tile_ms": float(fixture.get("first_tile_usec", -1000)) / 1000.0,
        "first_collision_ms": float(fixture.get("first_collision_usec", -1000)) / 1000.0,
        "p50_frame_ms": frame["p50"],
        "p95_frame_ms": frame["p95"],
        "p99_frame_ms": frame["p99"],
        "longest_frame_ms": frame["longest"],
        "javascript_heap_bytes": environment.get("javascript_heap_bytes"),
        "estimated_region_bytes": fixture.get("max_estimated_region_bytes"),
        "resident_regions": fixture.get("max_loaded_regions"),
        "collision_regions": fixture.get("max_collision_regions"),
        "eviction_recovery_ms": float(
            fixture.get("eviction_recovery_usec", -1000)
        )
        / 1000.0,
    }
    measurements.update(extended_runtime_measurements(fixture))
    budget_results = evaluate_budgets(measurements, limits)
    passed = (
        required_budget_results_pass(budget_results)
        and fixture_contract_passes(
            fixture,
            budgets["fixture"],
            expected_profile=args.profile,
        )
    )

    created_at = dt.datetime.now(dt.timezone.utc).isoformat()
    report = {
        "schema": "mterrain-web-performance-evidence-v1",
        "created_at": created_at,
        "origin": "attested_physical_browser_capture",
        "profile": args.profile,
        "lane": args.lane,
        "source": {
            "commit": build_receipt["source"]["mterrain_commit"],
            "tree": build_receipt["source"]["mterrain_tree"],
            "dirty": False,
        },
        "environment": {
            "kind": lane["environment_kind"],
            "device_label": bounded_text(args.device_label, "device label"),
            "physical_device": args.physical_device,
            "headed": args.headed,
            "browser_product": args.browser_product,
            "browser_version": browser_version,
            "operating_system": operating_system,
            "viewport": viewport,
            "renderer": renderer,
            "vendor": vendor,
            "user_agent": user_agent,
        },
        "attestation": {
            "operator": bounded_text(args.operator, "operator"),
            "statement": (
                "The capture was downloaded from the named headed physical device "
                "without browser or hardware emulation."
            ),
        },
        "capture": {
            "sha256": sha256(capture_path),
            "captured_at": capture.get("captured_at"),
            "context": context,
            "health": {
                "webgl_ok": environment.get("ok") is True,
                "webgl_error": environment.get("webgl_error"),
                "color_bucket_count": environment.get("color_bucket_count"),
                "console_error_count": len(capture.get("console_errors", [])),
                "page_error_count": len(capture.get("page_errors", [])),
            },
        },
        "budget": {
            "path": (
                str(budgets_path.relative_to(ROOT))
                if budgets_path.is_relative_to(ROOT)
                else budgets_path.name
            ),
            "sha256_at_capture": sha256(budgets_path),
            "threshold_contract_sha256": threshold_contract_sha256(budgets),
            "profile": budget_profile,
            "results": budget_results,
        },
        "build_receipt": {
            "name": build_receipt_path.name,
            "sha256": sha256(build_receipt_path),
            "value": build_receipt,
        },
        "template_receipt": {
            "name": template_receipt_path.name,
            "sha256": sha256(template_receipt_path),
            "value": template_receipt,
        },
        "measurements": measurements,
        "frame_time_ms": frame,
        "fixture": fixture,
        "resource_timings": resources,
        "passed": passed,
    }
    output = args.output
    if output is None:
        output = (
            ROOT
            / "build"
            / "evidence"
            / f"web-performance-{args.profile}-{args.lane}.json"
        )
    output = output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(f"Evidence output must be below {build_root}: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    if not passed:
        raise SystemExit("Physical browser evidence did not pass its configured budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
