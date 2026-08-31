#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from web_evidence_common import load_object, sha256


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("web_core", "web_extended")
BROWSERS = {
    "chromium": "playwright_chromium",
    "firefox": "playwright_firefox",
}
BUILD_RECEIPTS = {
    "web_core": "web-template_debug.json",
    "web_extended": "web-extended-template_debug.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--build-receipts-dir", required=True, type=Path)
    parser.add_argument("--template-receipt", required=True, type=Path)
    parser.add_argument("--browser-toolchain-receipt", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build" / "evidence" / "hosted-correctness.json",
    )
    return parser.parse_args()


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments], text=True
    ).strip()


def require_clean_source() -> dict[str, Any]:
    dirty = bool(
        git(
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=dirty",
        )
    )
    if dirty:
        raise SystemExit("Hosted correctness aggregation requires a clean checkout")
    return {
        "commit": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "dirty": False,
    }


def validate_smoke(
    evidence: dict[str, Any],
    *,
    profile: str,
    browser: str,
    source: dict[str, Any],
    side_module_sha256: str,
    template_receipt_sha256: str,
    browser_receipt_sha256: str,
) -> None:
    expected_extended = int(profile == "web_extended")
    marker = str(evidence.get("success_marker", ""))
    for token in (
        "MTERRAIN_WEB_SMOKE_OK",
        "initialized_tile_samples=4489",
        "rejected_non_finite=1",
        "rejected_border=1",
        "lod_transitions=1",
        "recreate=1",
        "phase_timings=1",
        f"extended={expected_extended}",
        f"profile={profile}",
    ):
        if token not in marker:
            raise SystemExit(f"{profile}/{browser} omitted smoke token {token}")
    if evidence.get("schema") != "mterrain-web-smoke-v1":
        raise SystemExit(f"Unexpected hosted smoke schema for {profile}/{browser}")
    if evidence.get("passed") is not True:
        raise SystemExit(f"Hosted smoke did not pass for {profile}/{browser}")
    if evidence.get("mode") != "smoke" or evidence.get("browser") != browser:
        raise SystemExit(f"Hosted smoke identity mismatch for {profile}/{browser}")
    if evidence.get("headless") is not False:
        raise SystemExit(
            f"Hosted correctness must retain its virtual-display headed label: {browser}"
        )
    if evidence.get("source") != source:
        raise SystemExit(f"Hosted smoke source mismatch for {profile}/{browser}")
    frame = evidence.get("frame_probe", {})
    if frame.get("ok") is not True or int(frame.get("color_bucket_count", 0)) < 2:
        raise SystemExit(f"Hosted smoke frame was blank for {profile}/{browser}")
    if (
        evidence.get("console_errors")
        or evidence.get("page_errors")
        or evidence.get("request_failures")
        or evidence.get("http_errors")
        or not evidence.get("canvas_box")
    ):
        raise SystemExit(f"Hosted smoke recorded browser errors for {profile}/{browser}")
    if evidence.get("web_side_module", {}).get("sha256") != side_module_sha256:
        raise SystemExit(f"Hosted smoke used the wrong side module for {profile}/{browser}")
    if evidence.get("template_receipt", {}).get("receipt_sha256") != (
        template_receipt_sha256
    ):
        raise SystemExit(f"Hosted smoke used the wrong template for {profile}/{browser}")
    if evidence.get("browser_toolchain_receipt", {}).get("receipt_sha256") != (
        browser_receipt_sha256
    ):
        raise SystemExit(f"Hosted smoke used the wrong browser toolchain for {browser}")


def main() -> int:
    args = parse_args()
    evidence_root = args.evidence_dir.expanduser().resolve()
    receipts_root = args.build_receipts_dir.expanduser().resolve()
    if not evidence_root.is_dir() or not receipts_root.is_dir():
        raise SystemExit("Hosted evidence and build-receipt directories must exist")
    source = require_clean_source()
    template_path = args.template_receipt.expanduser().resolve()
    browser_path = args.browser_toolchain_receipt.expanduser().resolve()
    template = load_object(template_path, "Web template receipt")
    browser_toolchain = load_object(browser_path, "browser toolchain receipt")
    if template.get("schema") != "mterrain-web-template-receipt-v1":
        raise SystemExit("Unexpected Web template-receipt schema")
    if browser_toolchain.get("schema") != "mterrain-browser-toolchain-receipt-v2":
        raise SystemExit("Unexpected browser toolchain-receipt schema")
    if template.get("source", {}).get("tracked_dirty") is not False:
        raise SystemExit("Hosted correctness requires a clean Godot template receipt")
    if not set(BROWSERS).issubset(
        browser_toolchain.get("playwright", {}).get("browsers", {})
    ):
        raise SystemExit("Browser toolchain receipt omitted a hosted engine")
    template_sha = sha256(template_path)
    browser_sha = sha256(browser_path)

    profile_records: dict[str, Any] = {}
    for profile in PROFILES:
        receipt_path = receipts_root / BUILD_RECEIPTS[profile]
        receipt = load_object(receipt_path, f"{profile} debug build receipt")
        if receipt.get("schema") != "mterrain-web-build-receipt-v2":
            raise SystemExit(f"Unexpected build-receipt schema for {profile}")
        receipt_source = receipt.get("source", {})
        if (
            receipt_source.get("mterrain_commit") != source["commit"]
            or receipt_source.get("mterrain_tree") != source["tree"]
            or receipt_source.get("mterrain_dirty") is not False
            or receipt.get("target", {}).get("profile") != profile
            or receipt.get("target", {}).get("target") != "template_debug"
        ):
            raise SystemExit(f"Hosted build receipt source/target mismatch for {profile}")
        browser_records: dict[str, Any] = {}
        for browser, product in BROWSERS.items():
            evidence_path = evidence_root / profile / browser / f"web-smoke-{browser}.json"
            evidence = load_object(evidence_path, f"{profile}/{browser} smoke evidence")
            validate_smoke(
                evidence,
                profile=profile,
                browser=browser,
                source=source,
                side_module_sha256=receipt["artifact"]["sha256"],
                template_receipt_sha256=template_sha,
                browser_receipt_sha256=browser_sha,
            )
            browser_records[product] = {
                "passed": True,
                "evidence_name": evidence_path.name,
                "evidence_sha256": sha256(evidence_path),
                "browser_version": evidence.get("browser_version"),
                "renderer": evidence.get("frame_probe", {}).get("renderer"),
            }
        profile_records[profile] = {
            "build_receipt_name": receipt_path.name,
            "build_receipt_sha256": sha256(receipt_path),
            "side_module_sha256": receipt["artifact"]["sha256"],
            "browsers": browser_records,
            "passed": True,
        }

    report = {
        "schema": "mterrain-web-hosted-correctness-evidence-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": source,
        "environment": {
            "kind": "github_hosted_linux",
            "performance_eligible": False,
        },
        "template_receipt": {
            "name": template_path.name,
            "sha256": template_sha,
            "artifact_sha256": template["artifact"]["sha256"],
        },
        "browser_toolchain_receipt": {
            "name": browser_path.name,
            "sha256": browser_sha,
            "playwright_version": browser_toolchain["playwright"]["version"],
        },
        "profiles": profile_records,
        "passed": True,
    }
    output = args.output.expanduser().resolve()
    build_root = (ROOT / "build").resolve()
    if output == build_root or build_root not in output.parents:
        raise SystemExit(f"Hosted correctness output must be below {build_root}: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)
    print("MTERRAIN_WEB_HOSTED_CORRECTNESS_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
