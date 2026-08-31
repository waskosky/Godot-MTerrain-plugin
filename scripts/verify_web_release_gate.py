#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from web_evidence_common import (
    browser_version_matches,
    evaluate_budgets,
    fixture_contract_passes,
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
DEFAULT_GATE = ROOT / "tools" / "web_release_gate.json"
DEFAULT_BUDGETS = ROOT / "tools" / "web_performance_budgets.json"
DEFAULT_CALIBRATION = ROOT / "tools" / "web_performance_calibration.json"
PERFORMANCE_FIXTURE_FILES = (
    "tests/web_performance/main.gd",
    "tests/web_performance/evidence_bridge.js",
    "tests/web_smoke/main.tscn",
    "tests/web_smoke/project.godot",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("web_core", "web_extended"), default="web_core")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "build" / "evidence")
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--budgets", type=Path, default=DEFAULT_BUDGETS)
    parser.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--candidate-version")
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--prior-dir", type=Path)
    parser.add_argument("--require-stable", action="store_true")
    parser.add_argument("--write-status", type=Path)
    return parser.parse_args()


def package_module() -> Any:
    path = ROOT / "scripts" / "package_web_release.py"
    specification = importlib.util.spec_from_file_location("mterrain_package", path)
    if specification is None or specification.loader is None:
        raise SystemExit("Could not load the release-package verifier")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_file_sha256(value: Any) -> str:
    return sha256_bytes(
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )


def digest_string(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def timestamp_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def timestamp_before(first: Any, second: Any) -> bool:
    if not timestamp_string(first) or not timestamp_string(second):
        return False
    first_time = dt.datetime.fromisoformat(str(first).replace("Z", "+00:00"))
    second_time = dt.datetime.fromisoformat(str(second).replace("Z", "+00:00"))
    return first_time < second_time


def load_candidate(
    directory: Path,
    *,
    profile: str,
    budgets_sha256: str,
    gate_sha256: str,
) -> dict[str, Any]:
    resolved = directory.expanduser().resolve()
    if not resolved.is_dir():
        raise SystemExit(f"Candidate release directory is missing: {resolved}")
    module = package_module()
    module.verify(resolved)
    indices = sorted(resolved.glob("Godot-MTerrain-*-release-index.json"))
    if len(indices) != 1:
        raise SystemExit("Candidate release directory must contain one release index")
    index_path = indices[0]
    index = load_object(index_path, "candidate release index")
    profile_index = index.get("profiles", {}).get(profile)
    if not isinstance(profile_index, dict):
        raise SystemExit(f"Candidate release omitted profile {profile}")
    bundle_record = profile_index.get("bundle", {})
    bundle_path = resolved / str(bundle_record.get("name", ""))
    members = module.safe_archive_members(bundle_path, index["source_date_epoch"])
    debug = profile_index.get("artifacts", {}).get("template_debug", {})
    archive_root = profile_index.get("archive_root")
    receipt_name = f"{archive_root}/{debug.get('receipt', '')}"
    if receipt_name not in members:
        raise SystemExit("Candidate bundle omitted its debug build receipt")
    build_receipt = json.loads(members[receipt_name].decode("utf-8"))
    fixture_sources: dict[str, str] = {}
    for relative in PERFORMANCE_FIXTURE_FILES:
        member_name = f"{archive_root}/{relative}"
        if member_name not in members:
            raise SystemExit(f"Candidate bundle omitted performance fixture {relative}")
        fixture_sources[relative] = sha256_bytes(members[member_name])
    return {
        "version": index.get("version"),
        "index_sha256": sha256(index_path),
        "bundle_sha256": sha256(bundle_path),
        "source": {
            "commit": index.get("source", {}).get("mterrain_commit"),
            "tree": index.get("source", {}).get("mterrain_tree"),
            "dirty": False,
        },
        "build_receipt_sha256": sha256_bytes(members[receipt_name]),
        "build_receipt": build_receipt,
        "side_module_sha256": debug.get("sha256"),
        "performance_fixture_sources": fixture_sources,
        "budget_contract_matches": index.get("performance_budgets", {}).get(
            "sha256"
        )
        == budgets_sha256,
        "bundled_calibration_sha256": index.get(
            "performance_calibration", {}
        ).get("sha256"),
        "release_gate_contract_matches": index.get("release_gate", {}).get(
            "sha256"
        )
        == gate_sha256,
    }


def load_prior(
    directory: Path,
    *,
    profile: str,
    expected_version: str,
) -> dict[str, Any]:
    resolved = directory.expanduser().resolve()
    if not resolved.is_dir():
        raise SystemExit(f"Prior release directory is missing: {resolved}")
    module = package_module()
    module.verify(resolved)
    indices = sorted(resolved.glob("Godot-MTerrain-*-release-index.json"))
    if len(indices) != 1:
        raise SystemExit("Prior release directory must contain one release index")
    index_path = indices[0]
    index = load_object(index_path, "prior release index")
    if index.get("version") != expected_version:
        raise SystemExit("Verified prior release has the wrong version")
    profile_index = index.get("profiles", {}).get(profile)
    if not isinstance(profile_index, dict):
        raise SystemExit(f"Prior release omitted profile {profile}")
    bundle_path = resolved / str(profile_index.get("bundle", {}).get("name", ""))
    if not bundle_path.is_file():
        raise SystemExit(f"Prior release omitted its {profile} bundle")
    return {
        "version": expected_version,
        "index_sha256": sha256(index_path),
        "bundle_sha256": sha256(bundle_path),
    }


def profile_contract(gate: dict[str, Any], profile: str) -> dict[str, Any]:
    selected = gate["stable_profiles"].get(profile)
    if not isinstance(selected, dict):
        raise SystemExit(f"Release gate omitted {profile}")
    if "inherits_lane_shape_from" in selected:
        inherited = gate["stable_profiles"].get(selected["inherits_lane_shape_from"])
        if not isinstance(inherited, dict):
            raise SystemExit(f"Release gate has an invalid inherited profile for {profile}")
        return inherited
    return selected


def environment_matches(
    evidence: dict[str, Any], lane_name: str, lane: dict[str, Any]
) -> bool:
    environment = evidence.get("environment", {})
    product = environment.get("browser_product")
    browser_version = environment.get("browser_version")
    operating_system = environment.get("operating_system")
    user_agent = environment.get("user_agent")
    renderer = environment.get("renderer")
    vendor = environment.get("vendor")
    device_label = environment.get("device_label")
    viewport = environment.get("viewport")
    viewport_valid = (
        isinstance(viewport, dict)
        and all(
            isinstance(viewport.get(axis), (int, float))
            and not isinstance(viewport.get(axis), bool)
            and viewport.get(axis) > 0
            for axis in ("width", "height")
        )
    )
    return (
        evidence.get("lane") == lane_name
        and environment.get("kind") == lane["environment_kind"]
        and environment.get("headed") is lane["headed"]
        and environment.get("physical_device") is lane["physical_device"]
        and product in lane["browser_products"]
        and all(
            isinstance(value, str) and bool(value.strip())
            for value in (
                browser_version,
                operating_system,
                user_agent,
                renderer,
                vendor,
                device_label,
            )
        )
        and len(user_agent) <= 512
        and viewport_valid
        and user_agent_matches(product, user_agent)
        and browser_version_matches(product, browser_version, user_agent)
        and operating_system_matches(lane["environment_kind"], product, operating_system)
        and not software_renderer(renderer)
    )


def evidence_record(path: Path, evidence_dir: Path) -> dict[str, str]:
    resolved = path.resolve()
    if evidence_dir != resolved and evidence_dir not in resolved.parents:
        raise SystemExit(f"Selected evidence escaped its input directory: {resolved}")
    return {
        "relative_path": resolved.relative_to(evidence_dir).as_posix(),
        "sha256": sha256(resolved),
    }


def valid_performance_evidence(
    evidence: dict[str, Any],
    *,
    profile: str,
    lane_name: str,
    lane: dict[str, Any],
    threshold_digest: str,
    budgets_sha256: str,
    fixture_contract: dict[str, Any],
    budget_limits: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> bool:
    build_record = evidence.get("build_receipt", {})
    build_receipt = build_record.get("value", {})
    template_record = evidence.get("template_receipt", {})
    template_receipt = template_record.get("value", {})
    capture_context = evidence.get("capture", {}).get("context", {})
    capture_health = evidence.get("capture", {}).get("health", {})
    fixture_source = capture_context.get("fixture_source", {})
    runtime_payload = capture_context.get("runtime_export_payload")
    color_buckets = capture_health.get("color_bucket_count")
    budget_results = evidence.get("budget", {}).get("results", {})
    measurements = evidence.get("measurements", {})
    resource_timings = evidence.get("resource_timings")
    normalized_build_source = {
        "commit": build_receipt.get("source", {}).get("mterrain_commit"),
        "tree": build_receipt.get("source", {}).get("mterrain_tree"),
        "dirty": build_receipt.get("source", {}).get("mterrain_dirty"),
    }
    valid = (
        evidence.get("schema") == "mterrain-web-performance-evidence-v1"
        and evidence.get("profile") == profile
        and evidence.get("passed") is True
        and evidence.get("origin") == "attested_physical_browser_capture"
        and evidence.get("source", {}).get("dirty") is False
        and evidence.get("source") == normalized_build_source
        and environment_matches(evidence, lane_name, lane)
        and bool(evidence.get("attestation", {}).get("operator"))
        and bool(evidence.get("attestation", {}).get("statement"))
        and digest_string(evidence.get("capture", {}).get("sha256"))
        and timestamp_string(evidence.get("capture", {}).get("captured_at"))
        and capture_health.get("webgl_ok") is True
        and capture_health.get("webgl_error") == 0
        and isinstance(color_buckets, int)
        and not isinstance(color_buckets, bool)
        and color_buckets >= 2
        and capture_health.get("console_error_count") == 0
        and capture_health.get("page_error_count") == 0
        and isinstance(resource_timings, list)
        and bool(resource_timings)
        and all(
            isinstance(record, dict)
            and isinstance(record.get("response_status"), (int, float))
            and not isinstance(record.get("response_status"), bool)
            and record.get("response_status") < 400
            for record in resource_timings
        )
        and not software_renderer(evidence.get("environment", {}).get("renderer", ""))
        and build_receipt.get("schema") == "mterrain-web-build-receipt-v2"
        and build_record.get("sha256") == json_file_sha256(build_receipt)
        and build_receipt.get("target", {}).get("profile") == profile
        and build_receipt.get("target", {}).get("target") == "template_debug"
        and build_receipt.get("source", {}).get("mterrain_dirty") is False
        and template_receipt.get("schema") == "mterrain-web-template-receipt-v1"
        and template_record.get("sha256") == json_file_sha256(template_receipt)
        and template_receipt.get("source", {}).get("tracked_dirty") is False
        and digest_string(template_record.get("sha256"))
        and template_receipt.get("target", {}).get("godot")
        == build_receipt.get("toolchain", {}).get("pins", {}).get("godot", {}).get(
            "version"
        )
        and capture_context.get("schema") == "mterrain-web-performance-context-v1"
        and capture_context.get("profile") == profile
        and fixture_source.get("source") == evidence.get("source")
        and isinstance(fixture_source.get("files"), dict)
        and runtime_export_payload_valid(runtime_payload)
        and measurements.get("compressed_runtime_export_bytes")
        == runtime_payload.get("gzip_bytes")
        and capture_context.get("build_receipt", {}).get("sha256")
        == build_record.get("sha256")
        and capture_context.get("build_receipt", {}).get("artifact_sha256")
        == build_receipt.get("artifact", {}).get("sha256")
        and capture_context.get("template_receipt", {}).get("sha256")
        == template_record.get("sha256")
        and capture_context.get("template_receipt", {}).get("artifact_sha256")
        == template_receipt.get("artifact", {}).get("sha256")
        and capture_context.get("performance_budget", {}).get("sha256")
        == budgets_sha256
        and capture_context.get("performance_budget", {}).get(
            "threshold_contract_sha256"
        )
        == threshold_digest
        and evidence.get("budget", {}).get("profile") == lane["budget_profile"]
        and evidence.get("budget", {}).get("sha256_at_capture") == budgets_sha256
        and evidence.get("budget", {}).get("threshold_contract_sha256")
        == threshold_digest
        and isinstance(measurements, dict)
        and measurements.get("compressed_side_module_bytes")
        == build_receipt.get("artifact", {}).get("brotli", {}).get("size")
        and budget_results == evaluate_budgets(measurements, budget_limits)
        and required_budget_results_pass(budget_results)
        and fixture_contract_passes(
            evidence.get("fixture", {}),
            fixture_contract,
            expected_profile=profile,
        )
    )
    if not valid:
        return False
    if candidate is None:
        return True
    return (
        evidence.get("source") == candidate["source"]
        and build_record.get("sha256") == candidate["build_receipt_sha256"]
        and build_receipt == candidate["build_receipt"]
        and build_receipt.get("artifact", {}).get("sha256")
        == candidate["side_module_sha256"]
        and fixture_source.get("files")
        == candidate["performance_fixture_sources"]
    )


def valid_hosted_evidence(
    evidence: dict[str, Any],
    *,
    profile: str,
    required_browsers: set[str],
    expected_schema: str,
    candidate: dict[str, Any] | None,
) -> bool:
    profile_record = evidence.get("profiles", {}).get(profile, {})
    browsers = profile_record.get("browsers", {})
    template = evidence.get("template_receipt", {})
    browser_toolchain = evidence.get("browser_toolchain_receipt", {})
    valid = (
        evidence.get("schema") == expected_schema
        and evidence.get("passed") is True
        and evidence.get("source", {}).get("dirty") is False
        and evidence.get("environment", {}).get("kind") == "github_hosted_linux"
        and evidence.get("environment", {}).get("performance_eligible") is False
        and digest_string(template.get("sha256"))
        and digest_string(template.get("artifact_sha256"))
        and digest_string(browser_toolchain.get("sha256"))
        and bool(str(browser_toolchain.get("playwright_version", "")).strip())
        and profile_record.get("passed") is True
        and digest_string(profile_record.get("build_receipt_sha256"))
        and digest_string(profile_record.get("side_module_sha256"))
        and set(browsers) == required_browsers
        and all(
            record.get("passed") is True
            and digest_string(record.get("evidence_sha256"))
            and bool(str(record.get("browser_version", "")).strip())
            and bool(str(record.get("renderer", "")).strip())
            for record in browsers.values()
        )
    )
    if not valid:
        return False
    if candidate is None:
        return True
    return (
        evidence.get("source") == candidate["source"]
        and profile_record.get("build_receipt_sha256")
        == candidate["build_receipt_sha256"]
        and profile_record.get("side_module_sha256")
        == candidate["side_module_sha256"]
    )


def valid_rollback_evidence(
    evidence: dict[str, Any],
    *,
    profile: str,
    lane_name: str,
    lane: dict[str, Any],
    prior_version: str,
    candidate_version: str | None,
    candidate_contract: dict[str, Any] | None,
    prior_contract: dict[str, Any] | None,
) -> bool:
    candidate = evidence.get("candidate", {})
    prior = evidence.get("prior", {})
    session = evidence.get("session", {})
    template = evidence.get("template", {})
    environment = evidence.get("environment", {})
    attestation = evidence.get("attestation", {})
    renderer = str(environment.get("renderer", ""))
    return (
        evidence.get("schema") == "mterrain-web-rollback-evidence-v1"
        and evidence.get("origin") == "attested_physical_browser_rollback"
        and evidence.get("profile") == profile
        and evidence.get("passed") is True
        and evidence.get("sequence") == ["candidate", "prior"]
        and environment_matches(evidence, lane_name, lane)
        and bool(str(attestation.get("operator", "")).strip())
        and bool(str(attestation.get("statement", "")).strip())
        and bool(str(session.get("session_id", "")).strip())
        and digest_string(session.get("manifest_sha256"))
        and digest_string(template.get("sha256"))
        and digest_string(template.get("artifact_sha256"))
        and bool(renderer)
        and not software_renderer(renderer)
        and timestamp_before(candidate.get("captured_at"), prior.get("captured_at"))
        and prior.get("version") == prior_version
        and (candidate_version is None or candidate.get("version") == candidate_version)
        and all(
            digest_string(record.get("bundle_sha256"))
            and digest_string(record.get("release_index_sha256"))
            and digest_string(record.get("smoke_evidence_sha256"))
            for record in (candidate, prior)
        )
        and (
            candidate_contract is None
            or (
                candidate.get("release_index_sha256")
                == candidate_contract["index_sha256"]
                and candidate.get("bundle_sha256")
                == candidate_contract["bundle_sha256"]
            )
        )
        and (
            prior_contract is None
            or (
                prior.get("release_index_sha256")
                == prior_contract["index_sha256"]
                and prior.get("bundle_sha256")
                == prior_contract["bundle_sha256"]
            )
        )
    )


def main() -> int:
    args = parse_args()
    gate_path = args.gate.expanduser().resolve()
    budgets_path = args.budgets.expanduser().resolve()
    calibration_path = args.calibration.expanduser().resolve()
    gate = load_object(gate_path, "release gate")
    budgets = load_object(budgets_path, "performance budgets")
    calibration = load_object(calibration_path, "performance calibration")
    if gate.get("schema") != "mterrain-web-release-gate-v1":
        raise SystemExit("Unexpected Web release-gate schema")
    if budgets.get("schema") != "mterrain-web-performance-budgets-v1":
        raise SystemExit("Unexpected Web performance-budget schema")
    if calibration.get("schema") != "mterrain-web-performance-calibration-v1":
        raise SystemExit("Unexpected Web performance-calibration schema")
    threshold_digest = threshold_contract_sha256(budgets)
    if calibration.get("threshold_contract_sha256") != threshold_digest:
        raise SystemExit("Performance calibration targets a different threshold contract")
    approved_digests = calibration.get("approved_evidence_sha256", [])
    approved_digest_set = (
        set(approved_digests)
        if isinstance(approved_digests, list)
        and all(digest_string(value) for value in approved_digests)
        else set()
    )
    contract = profile_contract(gate, args.profile)
    lanes = contract.get("performance_lanes")
    rollback = contract.get("rollback")
    if not isinstance(lanes, dict) or not lanes:
        raise SystemExit("Stable profile must declare performance lanes")
    if not isinstance(rollback, dict):
        raise SystemExit("Stable profile must declare rollback lanes")
    if set(rollback.get("required_lanes", [])) - set(lanes):
        raise SystemExit("Rollback gate references an unknown performance lane")
    for lane_name, lane in lanes.items():
        if lane.get("budget_profile") not in budgets.get("profiles", {}):
            raise SystemExit(f"Lane {lane_name} references an unknown budget profile")
        if not lane.get("browser_products"):
            raise SystemExit(f"Lane {lane_name} has no accepted browser product")

    candidate: dict[str, Any] | None = None
    if args.candidate_dir is not None:
        candidate = load_candidate(
            args.candidate_dir,
            profile=args.profile,
            budgets_sha256=sha256(budgets_path),
            gate_sha256=sha256(gate_path),
        )
        if (
            args.candidate_version is not None
            and args.candidate_version != candidate["version"]
        ):
            raise SystemExit("Candidate version does not match its verified release index")
    candidate_version = (
        candidate["version"] if candidate is not None else args.candidate_version
    )
    prior_contract: dict[str, Any] | None = None
    if args.prior_dir is not None:
        if (
            args.candidate_dir is not None
            and args.prior_dir.expanduser().resolve()
            == args.candidate_dir.expanduser().resolve()
        ):
            raise SystemExit("Candidate and prior release directories must differ")
        prior_contract = load_prior(
            args.prior_dir,
            profile=args.profile,
            expected_version=rollback["prior_version"],
        )

    evidence_dir = args.evidence_dir.expanduser().resolve()
    performance: list[tuple[Path, dict[str, Any]]] = []
    rollbacks: list[tuple[Path, dict[str, Any]]] = []
    hosted: list[tuple[Path, dict[str, Any]]] = []
    if evidence_dir.is_dir():
        for path in sorted(evidence_dir.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if value.get("schema") == "mterrain-web-performance-evidence-v1":
                performance.append((path, value))
            elif value.get("schema") == "mterrain-web-rollback-evidence-v1":
                rollbacks.append((path, value))
            elif value.get("schema") == (
                "mterrain-web-hosted-correctness-evidence-v1"
            ):
                hosted.append((path, value))

    selected_performance: dict[str, Path] = {}
    selected_rollback: dict[str, Path] = {}
    selected_hosted: Path | None = None
    reasons: list[str] = []
    if candidate is None:
        reasons.append("verified candidate release directory was not provided")
    else:
        if not candidate["budget_contract_matches"]:
            reasons.append("candidate release uses a different performance-budget contract")
        if not candidate["release_gate_contract_matches"]:
            reasons.append("candidate release uses a different stable-lane contract")
    if prior_contract is None:
        reasons.append("verified prior release directory was not provided")

    hosted_contract = gate.get("hosted_correctness", {})
    if hosted_contract.get("required") is True:
        if (
            hosted_contract.get("aggregate_required") is not True
            or args.profile not in hosted_contract.get("profiles", [])
            or hosted_contract.get("schema")
            != "mterrain-web-hosted-correctness-evidence-v1"
        ):
            raise SystemExit("Hosted correctness release contract is incomplete")
        required_hosted = set(hosted_contract.get("browsers", []))
        hosted_matches = [
            path
            for path, evidence in hosted
            if valid_hosted_evidence(
                evidence,
                profile=args.profile,
                required_browsers=required_hosted,
                expected_schema=hosted_contract.get("schema", ""),
                candidate=candidate,
            )
        ]
        if hosted_matches:
            selected_hosted = hosted_matches[-1]
        else:
            reasons.append("missing passing pinned hosted-browser correctness evidence")
    for lane_name, lane in lanes.items():
        matches = [
            path
            for path, evidence in performance
            if valid_performance_evidence(
                evidence,
                profile=args.profile,
                lane_name=lane_name,
                lane=lane,
                threshold_digest=threshold_digest,
                budgets_sha256=sha256(budgets_path),
                fixture_contract=budgets["fixture"],
                budget_limits=budgets["profiles"][lane["budget_profile"]],
                candidate=candidate,
            )
        ]
        if matches:
            approved_matches = [
                path for path in matches if sha256(path) in approved_digest_set
            ]
            selected_performance[lane_name] = (
                approved_matches[-1] if approved_matches else matches[-1]
            )
        else:
            reasons.append(f"missing passing performance evidence: {lane_name}")

    for lane_name in rollback["required_lanes"]:
        lane = lanes[lane_name]
        matches = [
            path
            for path, evidence in rollbacks
            if valid_rollback_evidence(
                evidence,
                profile=args.profile,
                lane_name=lane_name,
                lane=lane,
                prior_version=rollback["prior_version"],
                candidate_version=candidate_version,
                candidate_contract=candidate,
                prior_contract=prior_contract,
            )
        ]
        if matches:
            selected_rollback[lane_name] = matches[-1]
        else:
            reasons.append(f"missing passing whole-bundle rollback evidence: {lane_name}")

    calibration_candidate_bound = False
    if calibration.get("release_gate_eligible") is not True:
        reasons.append("performance budgets remain provisional")
    else:
        candidate_approval = calibration.get("candidate_release", {})
        review = calibration.get("review", {})
        approval_records = calibration.get("approved_evidence", [])
        valid_digests = (
            isinstance(approved_digests, list)
            and bool(approved_digests)
            and all(digest_string(value) for value in approved_digests)
            and len(set(approved_digests)) == len(approved_digests)
        )
        valid_records = (
            valid_digests
            and isinstance(approval_records, list)
            and len(approval_records) == len(approved_digests)
            and all(
                isinstance(record, dict) and digest_string(record.get("sha256"))
                for record in approval_records
            )
            and {
                record.get("sha256")
                for record in approval_records
            }
            == set(approved_digests)
        )
        valid_review = (
            isinstance(review, dict)
            and bool(str(review.get("operator", "")).strip())
            and timestamp_string(review.get("approved_at"))
        )
        if not valid_digests or not valid_records:
            reasons.append("performance calibration has invalid evidence records")
        if not valid_review:
            reasons.append("performance calibration lacks a valid review attestation")
        if candidate is None:
            reasons.append("performance calibration is not bound to a verified candidate")
        elif (
            not isinstance(candidate_approval, dict)
            or candidate_approval.get("version") != candidate["version"]
            or candidate_approval.get("release_index_sha256")
            != candidate["index_sha256"]
        ):
            reasons.append("performance calibration targets a different candidate release")
        else:
            calibration_candidate_bound = True
        if valid_digests:
            unapproved = [
                lane_name
                for lane_name, path in selected_performance.items()
                if sha256(path) not in approved_digests
            ]
            if unapproved:
                reasons.append(
                    "performance evidence is not approved by calibration: "
                    + ", ".join(sorted(unapproved))
                )

    status = {
        "schema": "mterrain-web-release-gate-status-v1",
        "profile": args.profile,
        "candidate_version": candidate_version,
        "candidate_release_bound": candidate is not None,
        "prior_release_bound": prior_contract is not None,
        "threshold_contract_sha256": threshold_digest,
        "calibration_contract_sha256": sha256(calibration_path),
        "calibration_candidate_bound": calibration_candidate_bound,
        "hosted_correctness": (
            evidence_record(selected_hosted, evidence_dir)
            if selected_hosted
            else None
        ),
        "performance": {
            lane: evidence_record(path, evidence_dir)
            for lane, path in selected_performance.items()
        },
        "rollback": {
            lane: evidence_record(path, evidence_dir)
            for lane, path in selected_rollback.items()
        },
        "stable_ready": not reasons,
        "open_reasons": reasons,
    }
    if args.write_status is not None:
        output = args.write_status.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(status, indent=2, sort_keys=True))
    if args.require_stable and reasons:
        raise SystemExit("MTerrain Web stable-release gate remains open")
    print(
        "MTERRAIN_WEB_RELEASE_GATE_OK"
        if not reasons
        else "MTERRAIN_WEB_RELEASE_GATE_OPEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
