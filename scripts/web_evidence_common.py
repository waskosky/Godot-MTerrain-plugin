from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


MEASUREMENT_LIMITS = {
    "compressed_side_module_bytes": "maximum_compressed_side_module_bytes",
    "compressed_runtime_export_bytes": "maximum_compressed_runtime_export_bytes",
    "scheduler_longest_step_ms": "maximum_scheduler_step_ms",
    "startup_ms": "maximum_startup_ms",
    "first_tile_ms": "maximum_first_tile_ms",
    "first_collision_ms": "maximum_first_collision_ms",
    "p50_frame_ms": "maximum_p50_frame_ms",
    "p95_frame_ms": "maximum_p95_frame_ms",
    "p99_frame_ms": "maximum_p99_frame_ms",
    "longest_frame_ms": "maximum_longest_frame_ms",
    "javascript_heap_bytes": "maximum_javascript_heap_bytes",
    "estimated_region_bytes": "maximum_estimated_region_bytes",
    "resident_regions": "maximum_resident_regions",
    "collision_regions": "maximum_collision_regions",
    "extended_scheduler_longest_step_ms": "maximum_extended_scheduler_step_ms",
    "extended_foliage_instances": "maximum_extended_foliage_instances",
    "extended_resident_projections": "maximum_extended_resident_projections",
    "extended_path_collision_shapes": "maximum_extended_path_collision_shapes",
    "eviction_recovery_ms": "maximum_eviction_recovery_ms",
}

SOFTWARE_RENDERER_PATTERN = re.compile(
    r"swiftshader|llvmpipe|lavapipe|softpipe|software raster|software adapter|"
    r"microsoft basic render|\bwarp\b|virtualbox|vmware|virgl|parallels",
    re.IGNORECASE,
)

BROWSER_PRODUCTS = (
    "google_chrome",
    "chromium",
    "mozilla_firefox",
    "apple_safari",
    "google_chrome_android",
    "apple_mobile_safari",
)

RUNTIME_EXPORT_REQUIRED_FILES = {
    "index.html",
    "index.js",
    "index.pck",
    "index.side.wasm",
    "index.wasm",
    "libMTerrain.web.template_debug.wasm32.nothreads.wasm",
}

SCHEDULER_PHASES = {
    "preflight",
    "write_heights",
    "generate_normals",
    "texture_apply",
    "collision",
    "region_load",
    "eviction",
    "rollback_heights",
    "rollback_normals",
    "rollback_apply",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Cannot read {label} {resolved}: {error}") from error
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must contain a JSON object: {resolved}")
    return value


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def threshold_contract_sha256(budgets: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "schema": budgets.get("schema"),
            "fixture": budgets.get("fixture"),
            "profiles": budgets.get("profiles"),
        }
    )


def software_renderer(value: Any) -> bool:
    return bool(SOFTWARE_RENDERER_PATTERN.search(str(value)))


def runtime_export_payload_valid(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    files = payload.get("files")
    if (
        payload.get("schema") != "mterrain-web-runtime-export-payload-v1"
        or payload.get("compression") != "gzip-9-mtime-0-per-file"
        or payload.get("instrumentation_excluded") is not True
        or not isinstance(files, list)
        or not files
        or payload.get("file_count") != len(files)
    ):
        return False
    names: set[str] = set()
    raw_total = 0
    gzip_total = 0
    for record in files:
        if not isinstance(record, dict):
            return False
        name = record.get("name")
        digest = record.get("sha256")
        raw_bytes = record.get("raw_bytes")
        gzip_bytes = record.get("gzip_bytes")
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or name in names
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or not isinstance(raw_bytes, int)
            or isinstance(raw_bytes, bool)
            or raw_bytes <= 0
            or not isinstance(gzip_bytes, int)
            or isinstance(gzip_bytes, bool)
            or gzip_bytes <= 0
        ):
            return False
        names.add(name)
        raw_total += raw_bytes
        gzip_total += gzip_bytes
    return (
        RUNTIME_EXPORT_REQUIRED_FILES.issubset(names)
        and payload.get("raw_bytes") == raw_total
        and payload.get("gzip_bytes") == gzip_total
    )


def scheduler_metrics_valid(metrics: Any, expected_completed: int) -> bool:
    if not isinstance(metrics, dict):
        return False
    timings = metrics.get("phase_timings")
    if (
        metrics.get("phase_timing_contract")
        != "mterrain-runtime-phase-timings/v1"
        or not isinstance(timings, dict)
        or set(timings) != SCHEDULER_PHASES
    ):
        return False
    for timing in timings.values():
        if not isinstance(timing, dict):
            return False
        values = [timing.get(key) for key in ("invocations", "longest_usec", "total_usec")]
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in values
        ):
            return False
        invocations, longest, total = values
        if (invocations == 0 and (longest != 0 or total != 0)) or total < longest:
            return False
    integer_metrics = (
        "queued",
        "completed",
        "evicted_tiles",
        "region_loads",
        "region_unloads",
        "longest_step_usec",
    )
    if any(
        not isinstance(metrics.get(name), int)
        or isinstance(metrics.get(name), bool)
        or metrics.get(name) < 0
        for name in integer_metrics
    ):
        return False
    return (
        metrics["queued"] == expected_completed
        and metrics["completed"] == expected_completed
        and metrics["evicted_tiles"] == expected_completed
        and metrics["region_loads"] == expected_completed
        and metrics["region_unloads"] == expected_completed
        and metrics["longest_step_usec"] > 0
    )


def bounded_text(value: str, label: str, maximum: int = 160) -> str:
    clean = value.strip()
    if (
        not clean
        or len(clean) > maximum
        or any(ord(character) < 32 for character in clean)
    ):
        raise SystemExit(f"{label} must be 1..{maximum} printable characters")
    return clean


def user_agent_matches(product: str, user_agent: str) -> bool:
    checks = {
        "google_chrome": "Chrome/" in user_agent and "Android" not in user_agent,
        "chromium": "Chrome/" in user_agent and "Android" not in user_agent,
        "mozilla_firefox": "Firefox/" in user_agent,
        "apple_safari": (
            "Safari/" in user_agent
            and "Chrome/" not in user_agent
            and "Chromium/" not in user_agent
            and "Firefox/" not in user_agent
        ),
        "google_chrome_android": "Android" in user_agent and "Chrome/" in user_agent,
        "apple_mobile_safari": (
            ("iPhone" in user_agent or "iPad" in user_agent)
            and "Safari/" in user_agent
            and "CriOS/" not in user_agent
            and "FxiOS/" not in user_agent
        ),
    }
    return product in checks and checks[product]


def operating_system_matches(environment_kind: str, product: str, value: str) -> bool:
    lowered = value.casefold()
    if environment_kind == "physical_android":
        return "android" in lowered
    if environment_kind == "physical_ios":
        return "ios" in lowered or "ipados" in lowered
    if product == "apple_safari":
        return "macos" in lowered or "mac os" in lowered
    return bool(lowered)


def browser_version_matches(product: str, reported: str, user_agent: str) -> bool:
    patterns = {
        "google_chrome": r"Chrome/([0-9]+(?:\.[0-9]+)*)",
        "chromium": r"Chrome/([0-9]+(?:\.[0-9]+)*)",
        "mozilla_firefox": r"Firefox/([0-9]+(?:\.[0-9]+)*)",
        "apple_safari": r"Version/([0-9]+(?:\.[0-9]+)*)",
        "google_chrome_android": r"Chrome/([0-9]+(?:\.[0-9]+)*)",
        "apple_mobile_safari": r"Version/([0-9]+(?:\.[0-9]+)*)",
    }
    if product not in patterns:
        return False
    match = re.search(patterns[product], user_agent)
    return match is not None and reported.split(".", 1)[0] == match.group(1).split(
        ".", 1
    )[0]


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile without frame samples")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def frame_summary(values: list[float]) -> dict[str, float | int]:
    finite = [float(value) for value in values]
    if len(finite) < 120 or any(
        not math.isfinite(value) or value <= 0.0 for value in finite
    ):
        raise ValueError("Traversal requires at least 120 positive finite frame samples")
    return {
        "samples": len(finite),
        "p50": nearest_rank(finite, 0.50),
        "p95": nearest_rank(finite, 0.95),
        "p99": nearest_rank(finite, 0.99),
        "longest": max(finite),
    }


def evaluate_budgets(
    measurements: dict[str, float | int | None], limits: dict[str, Any]
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for measurement, limit_name in MEASUREMENT_LIMITS.items():
        value = measurements.get(measurement)
        limit = limits.get(limit_name)
        measured = (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0.0
        )
        results[measurement] = {
            "measured": measured,
            "value": value,
            "maximum": limit,
            "passed": bool(
                measured
                and isinstance(limit, (int, float))
                and not isinstance(limit, bool)
                and float(value) <= float(limit)
            ),
        }
    return results


def required_budget_results_pass(results: dict[str, Any]) -> bool:
    required = set(MEASUREMENT_LIMITS) - {"javascript_heap_bytes"}
    return required.issubset(results) and all(
        bool(results[name].get("passed")) for name in required
    )


def fixture_contract_passes(
    fixture: dict[str, Any],
    fixture_contract: dict[str, Any],
    *,
    expected_profile: str,
) -> bool:
    accepted_profiles = fixture_contract.get("runtime_profiles", [])
    try:
        core_passes = (
            fixture.get("schema") == "mterrain-web-performance-fixture/v1"
            and fixture.get("runtime_profile") == expected_profile
            and expected_profile in accepted_profiles
            and int(fixture.get("route_stops", 0))
            == fixture_contract.get("route_stops")
            and int(fixture.get("route_repetitions", 0))
            == fixture_contract.get("route_repetitions")
            and int(fixture.get("route_region_side", 0))
            == fixture_contract.get("route_region_side")
            and int(fixture.get("sample_ops_per_step", 0))
            == fixture_contract.get("sample_ops_per_step")
            and int(fixture.get("region_ops_per_step", 0))
            == fixture_contract.get("region_ops_per_step")
            and int(fixture.get("first_tile_usec", -1)) >= 0
            and int(fixture.get("first_collision_usec", -1)) >= 0
            and int(fixture.get("max_loaded_regions", 0)) > 0
            and int(fixture.get("max_resident_tiles", 0)) > 0
            and int(fixture.get("final_loaded_regions", -1)) == 0
            and int(fixture.get("final_resident_tiles", -1)) == 0
            and int(fixture.get("final_visible_points", -1)) == 0
            and int(fixture.get("max_visible_lod_points", 0)) > 0
            and int(fixture.get("max_lod_neighbor_delta", 99)) <= 1
            and scheduler_metrics_valid(
                fixture.get("scheduler_metrics"),
                int(fixture.get("route_stops", 0)),
            )
        )
        if not core_passes:
            return False
        extended = fixture.get("extended_runtime")
        if expected_profile == "web_core":
            return extended == {"enabled": False}
        contract = fixture_contract.get("extended_runtime")
        if not isinstance(extended, dict) or not isinstance(contract, dict):
            return False
        expected_counts = contract.get("maximum_installed_counts")
        expected_quality = contract.get("maximum_quality_tier_instances")
        final_counts = extended.get("final_installed_counts")
        metrics = extended.get("metrics")
        if not all(
            isinstance(value, dict)
            for value in (expected_counts, expected_quality, final_counts, metrics)
        ):
            return False
        integer_metrics = (
            "queued",
            "completed",
            "cancelled",
            "coalesced",
            "released",
            "foliage_instance_writes",
            "hlod_swaps",
            "hlod_transition_starts",
            "hlod_transition_steps",
            "hlod_transition_cancellations",
            "path_collision_installs",
            "steps",
            "longest_step_usec",
        )
        if any(
            not isinstance(metrics.get(name), int)
            or isinstance(metrics.get(name), bool)
            or metrics.get(name) < 0
            for name in integer_metrics
        ):
            return False
        return (
            extended.get("enabled") is True
            and extended.get("schema") == "mterrain-web-extended-performance/v1"
            and extended.get("api_version") == 1
            and extended.get("instance_ops_per_step")
            == contract.get("instance_ops_per_step")
            and extended.get("apply_ops_per_step")
            == contract.get("apply_ops_per_step")
            and extended.get("hlod_cross_fade_steps")
            == contract.get("hlod_cross_fade_steps")
            and extended.get("query_interval_stops")
            == contract.get("query_interval_stops")
            and extended.get("navigation_queries")
            == contract.get("expected_navigation_queries")
            and extended.get("path_collision_queries")
            == contract.get("expected_path_collision_queries")
            and 0 < int(extended.get("max_pending_work", 0))
            <= int(contract.get("maximum_pending_work", -1))
            and int(extended.get("max_instance_ops", -1))
            == int(contract.get("instance_ops_per_step", -2))
            and int(extended.get("max_apply_ops", -1))
            == int(contract.get("apply_ops_per_step", -2))
            and extended.get("max_installed_counts") == expected_counts
            and extended.get("max_foliage_instances")
            == contract.get("maximum_foliage_instances")
            and extended.get("max_quality_tier_instances") == expected_quality
            and extended.get("max_path_collision_shapes")
            == contract.get("maximum_path_collision_shapes")
            and extended.get("final_pending_work") == 0
            and final_counts == {name: 0 for name in expected_counts}
            and metrics["queued"] == contract.get("expected_completed_projections")
            and metrics["completed"] == contract.get("expected_completed_projections")
            and metrics["cancelled"] == 0
            and metrics["coalesced"] == 0
            and metrics["released"] == contract.get("expected_released_projections")
            and metrics["foliage_instance_writes"]
            == contract.get("expected_foliage_instance_writes")
            and metrics["hlod_swaps"] == contract.get("expected_hlod_swaps")
            and metrics["hlod_transition_starts"]
            == contract.get("expected_hlod_swaps")
            and metrics["hlod_transition_steps"]
            == contract.get("expected_hlod_transition_steps")
            and metrics["hlod_transition_cancellations"] == 0
            and metrics["path_collision_installs"]
            == contract.get("expected_path_collision_installs")
            and metrics["steps"] >= int(fixture.get("route_stops", 0))
            and metrics["longest_step_usec"] > 0
        )
    except (TypeError, ValueError):
        return False


def extended_runtime_measurements(
    fixture: dict[str, Any],
) -> dict[str, float | int]:
    extended = fixture.get("extended_runtime")
    if not isinstance(extended, dict) or extended.get("enabled") is not True:
        return {
            "extended_scheduler_longest_step_ms": 0.0,
            "extended_foliage_instances": 0,
            "extended_resident_projections": 0,
            "extended_path_collision_shapes": 0,
        }
    metrics = extended.get("metrics", {})
    counts = extended.get("max_installed_counts", {})
    longest_usec = metrics.get("longest_step_usec", -1000)
    resident = sum(
        value
        for value in counts.values()
        if isinstance(value, int) and not isinstance(value, bool)
    ) if isinstance(counts, dict) else -1
    return {
        "extended_scheduler_longest_step_ms": float(longest_usec) / 1000.0,
        "extended_foliage_instances": extended.get("max_foliage_instances", -1),
        "extended_resident_projections": resident,
        "extended_path_collision_shapes": extended.get(
            "max_path_collision_shapes", -1
        ),
    }
