#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from web_evidence_common import (
    BROWSER_PRODUCTS,
    browser_version_matches,
    bounded_text,
    load_object,
    operating_system_matches,
    sha256,
    software_renderer,
    user_agent_matches,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE = ROOT / "tools" / "web_release_gate.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True, type=Path)
    parser.add_argument("--candidate-capture", required=True, type=Path)
    parser.add_argument("--prior-capture", required=True, type=Path)
    parser.add_argument("--lane", required=True)
    parser.add_argument(
        "--profile", choices=("web_core", "web_extended"), default="web_core"
    )
    parser.add_argument("--browser-product", choices=BROWSER_PRODUCTS, required=True)
    parser.add_argument("--browser-version", required=True)
    parser.add_argument("--operating-system", required=True)
    parser.add_argument("--device-label", required=True)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--physical-device", action="store_true")
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def lane_contract(gate: dict[str, Any], profile: str, lane: str) -> dict[str, Any]:
    selected = gate["stable_profiles"][profile]
    if "inherits_lane_shape_from" in selected:
        selected = gate["stable_profiles"][selected["inherits_lane_shape_from"]]
    lanes = selected["performance_lanes"]
    if lane not in lanes or lane not in selected["rollback"]["required_lanes"]:
        raise SystemExit(f"Lane is not a rollback release gate: {lane}")
    return lanes[lane]


def parse_time(value: Any, label: str) -> dt.datetime:
    if not isinstance(value, str):
        raise SystemExit(f"{label} capture omitted its timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SystemExit(f"{label} capture has an invalid timestamp") from error
    if parsed.tzinfo is None:
        raise SystemExit(f"{label} capture timestamp must include a timezone")
    return parsed


def validate_capture(
    capture: dict[str, Any],
    stage: str,
    manifest_stage: dict[str, Any],
    profile: str,
) -> None:
    if capture.get("schema") != "mterrain-browser-rollback-capture-v1":
        raise SystemExit(f"Unexpected {stage} rollback-capture schema")
    context = capture.get("context", {})
    for key in (
        "session_id",
        "stage",
        "profile",
        "version",
        "release_index_sha256",
        "bundle_sha256",
        "native_library_sha256",
        "template_sha256",
    ):
        if context.get(key) != manifest_stage.get(key):
            raise SystemExit(f"{stage} capture context mismatch: {key}")
    marker = capture.get("success_marker", "")
    for token in (
        "MTERRAIN_WEB_ROLLBACK_OK",
        "initialized_tile_samples=4489",
        "rejected_non_finite=1",
        "bounded_scheduler=1",
        "bounded_collision=1",
        "eviction_recovery=1",
        f"profile={profile}",
        f"extended_companion={int(profile == 'web_extended')}",
    ):
        if token not in marker:
            raise SystemExit(f"{stage} capture omitted rollback marker {token}")
    environment = capture.get("environment", {})
    if environment.get("ok") is not True:
        raise SystemExit(f"{stage} capture did not retain a healthy WebGL2 frame")
    if int(environment.get("color_bucket_count", 0)) < 2:
        raise SystemExit(f"{stage} capture framebuffer was blank")
    if capture.get("console_errors") or capture.get("page_errors"):
        raise SystemExit(f"{stage} capture recorded browser errors")
    renderer_value = environment.get("renderer")
    if (
        not isinstance(renderer_value, str)
        or not renderer_value.strip()
        or software_renderer(renderer_value)
    ):
        raise SystemExit(f"{stage} capture was not representative hardware rendering")
    vendor = environment.get("vendor")
    viewport = environment.get("viewport")
    if not isinstance(vendor, str) or not vendor.strip():
        raise SystemExit(f"{stage} capture omitted its renderer vendor")
    if not isinstance(viewport, dict) or any(
        not isinstance(viewport.get(axis), (int, float))
        or isinstance(viewport.get(axis), bool)
        or viewport.get(axis) <= 0
        for axis in ("width", "height")
    ):
        raise SystemExit(f"{stage} capture omitted a valid viewport")


def main() -> int:
    args = parse_args()
    gate = load_object(args.gate, "release gate")
    if gate.get("schema") != "mterrain-web-release-gate-v1":
        raise SystemExit("Unexpected Web release-gate schema")
    lane = lane_contract(gate, args.profile, args.lane)
    if args.browser_product not in lane["browser_products"]:
        raise SystemExit("Browser product does not satisfy the rollback lane")
    if args.headed is not lane["headed"] or args.physical_device is not lane["physical_device"]:
        raise SystemExit("Headed/physical state does not satisfy the rollback lane")

    session_path = args.session.expanduser().resolve()
    candidate_path = args.candidate_capture.expanduser().resolve()
    prior_path = args.prior_capture.expanduser().resolve()
    session = load_object(session_path, "rollback session")
    candidate_capture = load_object(candidate_path, "candidate rollback capture")
    prior_capture = load_object(prior_path, "prior rollback capture")
    if session.get("schema") != "mterrain-web-rollback-session-v1":
        raise SystemExit("Unexpected rollback-session schema")
    if session.get("profile") != args.profile or session.get("sequence") != [
        "candidate",
        "prior",
    ]:
        raise SystemExit("Rollback session does not contain the required profile sequence")
    validate_capture(
        candidate_capture,
        "candidate",
        session["stages"]["candidate"],
        args.profile,
    )
    validate_capture(
        prior_capture,
        "prior",
        session["stages"]["prior"],
        args.profile,
    )
    candidate_time = parse_time(candidate_capture.get("captured_at"), "candidate")
    prior_time = parse_time(prior_capture.get("captured_at"), "prior")
    if candidate_time >= prior_time:
        raise SystemExit("Rollback captures were not recorded candidate then prior")
    candidate_environment = candidate_capture["environment"]
    prior_environment = prior_capture["environment"]
    for key in ("user_agent", "renderer", "vendor"):
        if candidate_environment.get(key) != prior_environment.get(key):
            raise SystemExit(f"Rollback changed browser/device environment: {key}")
    user_agent = bounded_text(
        str(candidate_environment.get("user_agent", "")), "user agent", 512
    )
    if not user_agent_matches(args.browser_product, user_agent):
        raise SystemExit("Browser-product attestation conflicts with the captured user agent")
    browser_version = bounded_text(args.browser_version, "browser version")
    if not browser_version_matches(args.browser_product, browser_version, user_agent):
        raise SystemExit("Browser-version attestation conflicts with the captured user agent")
    operating_system = bounded_text(args.operating_system, "operating system")
    if not operating_system_matches(
        lane["environment_kind"], args.browser_product, operating_system
    ):
        raise SystemExit("Operating-system attestation conflicts with the rollback lane")

    candidate = session["stages"]["candidate"]
    prior = session["stages"]["prior"]
    report = {
        "schema": "mterrain-web-rollback-evidence-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "origin": "attested_physical_browser_rollback",
        "profile": args.profile,
        "lane": args.lane,
        "sequence": ["candidate", "prior"],
        "session": {
            "session_id": session["session_id"],
            "manifest_sha256": sha256(session_path),
        },
        "environment": {
            "kind": lane["environment_kind"],
            "device_label": bounded_text(args.device_label, "device label"),
            "physical_device": args.physical_device,
            "headed": args.headed,
            "browser_product": args.browser_product,
            "browser_version": browser_version,
            "operating_system": operating_system,
            "viewport": candidate_environment.get("viewport"),
            "renderer": candidate_environment.get("renderer"),
            "vendor": candidate_environment.get("vendor"),
            "user_agent": user_agent,
        },
        "attestation": {
            "operator": bounded_text(args.operator, "operator"),
            "statement": (
                "The complete candidate profile was loaded first and the complete prior "
                "profile was restored second on the same headed physical device, without "
                "file-level substitution or browser/hardware emulation."
            ),
        },
        "candidate": {
            "version": candidate["version"],
            "release_index_sha256": candidate["release_index_sha256"],
            "bundle_sha256": candidate["bundle_sha256"],
            "smoke_evidence_sha256": sha256(candidate_path),
            "captured_at": candidate_capture["captured_at"],
        },
        "prior": {
            "version": prior["version"],
            "release_index_sha256": prior["release_index_sha256"],
            "bundle_sha256": prior["bundle_sha256"],
            "smoke_evidence_sha256": sha256(prior_path),
            "captured_at": prior_capture["captured_at"],
        },
        "template": session["template_receipt"],
        "passed": True,
    }
    output = args.output
    if output is None:
        output = (
            ROOT
            / "build"
            / "evidence"
            / f"web-rollback-{args.profile}-{args.lane}.json"
        )
    output = output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(f"Rollback evidence output must be below {build_root}: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
