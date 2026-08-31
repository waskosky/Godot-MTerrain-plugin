#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "runtime" / "web_runtime_contract.json"


def fail(message: str) -> None:
    raise SystemExit(f"Web runtime contract error: {message}")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read {path.relative_to(ROOT)}: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain an object")
    return value


def require_sorted_unique_strings(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
        or value != sorted(set(value))
    ):
        fail(f"{label} must be a sorted, unique, non-empty string list")
    return value


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        fail(f"{label} must be a non-empty object")
    return value


def require_cpp_capability(source: str, key: str, value: Any) -> None:
    if isinstance(value, bool):
        marker = f'capabilities["{key}"] = {str(value).lower()};'
    elif isinstance(value, int):
        marker = f'capabilities["{key}"] = {value};'
    elif isinstance(value, str):
        marker = f'capabilities["{key}"] = "{value}";'
    else:
        fail(f"unsupported native capability value for {key}")
    if marker not in source:
        fail(f"native capability drift for {key}")


def require_gdscript_capability(source: str, key: str, value: Any) -> None:
    if isinstance(value, bool):
        literal = str(value).lower()
    elif isinstance(value, int):
        literal = str(value)
    elif isinstance(value, str):
        literal = f'"{value}"'
    else:
        fail(f"unsupported companion capability value for {key}")
    if f'"{key}": {literal}' not in source:
        fail(f"extended companion capability drift for {key}")


def verify() -> str:
    contract = load_object(CONTRACT_PATH)
    if contract.get("schema") != "mterrain-web-runtime-contract-v1":
        fail("unexpected schema")
    if contract.get("contract_version") != 1:
        fail("unexpected contract version")
    if contract.get("status") != "experimental":
        fail("the current runtime must remain explicitly experimental")

    expected_target = {
        "architecture": "wasm32",
        "dynamic_linking": True,
        "godot": "4.7.stable.official.5b4e0cb0f",
        "platform": "web",
        "precision": "single",
        "renderer": "Compatibility",
        "threads": False,
        "web_api": "WebGL2",
    }
    if contract.get("target") != expected_target:
        fail("target tuple drift")
    for name, filename in (
        ("web_core", "web_toolchain.json"),
        ("web_extended", "web_extended_toolchain.json"),
    ):
        toolchain = load_object(ROOT / "tools" / filename)
        for field in ("architecture", "godot", "platform", "precision", "threads"):
            toolchain_value = (
                toolchain.get("godot", {}).get("version")
                if field == "godot"
                else toolchain.get(field)
            )
            if toolchain_value != expected_target[field]:
                fail(f"{name} toolchain disagrees on {field}")

    profiles = contract.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != {"web_core", "web_extended"}:
        fail("exactly web_core and web_extended profiles are required")
    core = require_mapping(profiles["web_core"], "profiles.web_core")
    extended = require_mapping(profiles["web_extended"], "profiles.web_extended")
    if core.get("native_class") != "MTerrain" or core.get("api_version") != 2:
        fail("native class/API version drift")
    if core.get("capability_contract") != "runtime-api-v2":
        fail("web_core capability contract drift")
    if core.get("expected_build_profile") != "web_core":
        fail("web_core build-profile contract drift")
    if extended.get("inherits") != "web_core":
        fail("web_extended must inherit web_core")
    if extended.get("capability_contract") != "runtime-api-v2+extended-api-v1":
        fail("web_extended capability contract drift")
    if extended.get("expected_build_profile") != "web_extended":
        fail("web_extended build-profile contract drift")

    implementation = (ROOT / "gdextension" / "src" / "mterrain.cpp").read_text(
        encoding="utf-8"
    )
    header = (ROOT / "gdextension" / "src" / "mterrain.h").read_text(
        encoding="utf-8"
    )
    scheduler = (
        ROOT / "gdextension" / "src" / "mruntime_scheduler.cpp"
    ).read_text(encoding="utf-8")
    material = (
        ROOT / "gdextension" / "src" / "mterrain_runtime_api.cpp"
    ).read_text(encoding="utf-8")
    sconstruct = (ROOT / "gdextension" / "SConstruct").read_text(encoding="utf-8")
    for profile in ("web_core", "web_extended"):
        if f'capabilities["build_profile"] = "{profile}";' not in implementation:
            fail(f"native build-profile capability drift for {profile}")
    for required_define in (
        "MTERRAIN_BOUNDED_RUNTIME",
        "MTERRAIN_MEMORY_ONLY_DEFAULT",
        "MTERRAIN_SINGLE_THREADED",
    ):
        if required_define not in sconstruct:
            fail(f"Web build profile no longer declares {required_define}")
    bound_methods = dict(
        re.findall(
            r'D_METHOD\("([A-Za-z0-9_]+)"[^;]*?&MTerrain::([A-Za-z0-9_]+)',
            implementation,
            re.DOTALL,
        )
    )
    for method in require_sorted_unique_strings(
        core.get("required_methods"), "profiles.web_core.required_methods"
    ):
        native_method = bound_methods.get(method)
        if native_method is None:
            fail(f"native method is not bound: {method}")
        if re.search(rf"\b{re.escape(native_method)}\s*\(", header) is None:
            fail(f"bound native method is not declared: {method} -> {native_method}")
    if "return 2;" not in implementation[
        implementation.index("int MTerrain::get_runtime_bridge_api_version") :
    ]:
        fail("native API version implementation drift")
    if 'height_formats.push_back("r32f_metres")' not in implementation:
        fail("native height format drift")
    if core.get("height_formats") != ["r32f_metres"]:
        fail("contract height format drift")
    if core.get("state_contract") != "mterrain-runtime-state/v2":
        fail("native state contract drift")
    if 'result["kind"] = "mterrain-runtime-state/v2"' not in scheduler:
        fail("native state implementation drift")
    if core.get("phase_timing_contract") != "mterrain-runtime-phase-timings/v1":
        fail("native phase-timing contract drift")
    for marker in (
        'metrics["phase_timing_contract"] = "mterrain-runtime-phase-timings/v1"',
        'result["phase_usec"] = phase_usec',
        'metrics["phase_timings"] = phase_timing_snapshot()',
    ):
        if marker not in scheduler:
            fail("native phase-timing implementation drift")
    if core.get("visual_lod_contract") != "mterrain-runtime-visual-lod/v1":
        fail("native visual-LOD contract drift")
    grid = (ROOT / "gdextension" / "src" / "mgrid.cpp").read_text(
        encoding="utf-8"
    )
    if 'result["kind"] = "mterrain-runtime-visual-lod/v1"' not in grid:
        fail("native visual-LOD implementation drift")

    native_capabilities = require_mapping(
        core.get("required_capabilities"),
        "profiles.web_core.required_capabilities",
    )
    for key, value in native_capabilities.items():
        if key == "runtime_memory_only":
            if 'capabilities["runtime_memory_only"] = runtime_memory_only;' not in implementation:
                fail("runtime_memory_only capability drift")
        elif key == "single_threaded":
            if "#ifdef MTERRAIN_SINGLE_THREADED" not in implementation:
                fail("single-threaded capability guard drift")
        else:
            require_cpp_capability(implementation, key, value)

    unsupported = require_mapping(
        core.get("unsupported_capabilities"),
        "profiles.web_core.unsupported_capabilities",
    )
    core_branch_start = implementation.index("#elif defined(MTERRAIN_CORE_ONLY)")
    core_branch_end = implementation.index("#else", core_branch_start)
    core_branch = implementation[core_branch_start:core_branch_end]
    for key, value in unsupported.items():
        if value is not False:
            fail(f"web_core unsupported capability must be false: {key}")
        require_cpp_capability(core_branch, key, value)

    hard_limits = require_mapping(core.get("hard_limits"), "profiles.web_core.hard_limits")
    scheduler_markers = {
        "maximum_height_tile_width": f"MAX_TILE_SIDE = {hard_limits.get('maximum_height_tile_width')}",
        "maximum_height_tile_height": f"MAX_TILE_SIDE = {hard_limits.get('maximum_height_tile_height')}",
        "maximum_height_tile_samples": f"MAX_TILE_SAMPLES = {hard_limits.get('maximum_height_tile_samples')}",
        "maximum_regions_per_tile": f"MAX_TILE_REGIONS = {hard_limits.get('maximum_regions_per_tile')}",
        "maximum_completed_results": f"MAX_COMPLETED_RESULTS = {hard_limits.get('maximum_completed_results')}",
        "maximum_pending_work": f"between 1 and {hard_limits.get('maximum_pending_work')}",
        "maximum_resident_tiles": f"between 1 and {hard_limits.get('maximum_resident_tiles')}",
        "maximum_resident_regions": f"between 1 and {hard_limits.get('maximum_resident_regions')}",
        "maximum_collision_regions": f"between 0 and {hard_limits.get('maximum_collision_regions')}",
    }
    for key, marker in scheduler_markers.items():
        if marker not in scheduler:
            fail(f"native scheduler limit drift for {key}")
    if hard_limits.get("maximum_estimated_region_bytes") != 1024**3 or "1 GiB" not in scheduler:
        fail("native estimated-region byte limit drift")
    for key in (
        "minimum_sample_ops_per_step",
        "maximum_sample_ops_per_step",
        "maximum_region_ops_per_step",
        "maximum_collision_focus_radius_regions",
    ):
        if f'scheduler_limits["{key}"] = {hard_limits.get(key)};' not in implementation:
            fail(f"native published scheduler limit drift for {key}")
    for key in (
        "maximum_texture_array_layers",
        "maximum_fragment_samples",
        "maximum_texture_dimension",
    ):
        if f'material_limits["{key}"] = {hard_limits.get(key)};' not in implementation:
            fail(f"native material limit drift for {key}")
    topology_markers = {
        "maximum_terrain_quads_per_axis": "WEB_MAX_TERRAIN_QUADS_PER_AXIS",
        "maximum_terrain_topology_points": "WEB_MAX_TERRAIN_TOPOLOGY_POINTS",
        "maximum_terrain_regions": "WEB_MAX_TERRAIN_REGIONS",
        "maximum_visual_range_quads": "WEB_MAX_VISUAL_RANGE_QUADS",
    }
    for key, constant in topology_markers.items():
        if f"{constant} = {hard_limits.get(key)}" not in implementation:
            fail(f"native topology limit drift for {key}")
        if f'topology_limits["{key}"]' not in implementation:
            fail(f"native published topology limit drift for {key}")
    if "surface_layer_count > 4" not in material:
        fail("native material enforcement drift")

    companion = require_mapping(extended.get("companion"), "profiles.web_extended.companion")
    companion_path = companion.get("path")
    if companion_path != "runtime/web_extended_runtime.gd":
        fail("extended companion path drift")
    companion_source = (ROOT / str(companion_path)).read_text(encoding="utf-8")
    if companion.get("class") != "MTerrainWebExtendedRuntime":
        fail("extended companion class drift")
    if "class_name MTerrainWebExtendedRuntime" not in companion_source:
        fail("extended companion class is not declared")
    if companion.get("api_version") != 1 or "const API_VERSION := 1" not in companion_source:
        fail("extended companion API version drift")
    companion_methods = set(
        re.findall(r"(?m)^func ([A-Za-z0-9_]+)\s*\(", companion_source)
    )
    for method in require_sorted_unique_strings(
        companion.get("required_methods"),
        "profiles.web_extended.companion.required_methods",
    ):
        if method not in companion_methods:
            fail(f"extended companion method is missing: {method}")
    for key, value in require_mapping(
        companion.get("required_capabilities"),
        "profiles.web_extended.companion.required_capabilities",
    ).items():
        require_gdscript_capability(companion_source, key, value)
    for key, value in require_mapping(
        companion.get("unsupported_capabilities"),
        "profiles.web_extended.companion.unsupported_capabilities",
    ).items():
        if value is not False:
            fail(f"extended unsupported capability must be false: {key}")
        require_gdscript_capability(companion_source, key, value)
    if companion.get("state_contract") != "mterrain-web-extended-runtime-state/v1":
        fail("extended state contract drift")
    if '"kind": "mterrain-web-extended-runtime-state/v1"' not in companion_source:
        fail("extended state implementation drift")

    extended_hard_limits = require_mapping(
        companion.get("hard_limits"),
        "profiles.web_extended.companion.hard_limits",
    )
    extended_limit_markers = {
        "maximum_pending_work": "MAX_PENDING_LIMIT",
        "maximum_foliage_instances": "MAX_FOLIAGE_LIMIT",
        "maximum_mesh_vertices": "MAX_MESH_VERTICES",
        "maximum_mesh_indices": "MAX_MESH_INDICES",
        "maximum_navigation_vertices": "MAX_NAVIGATION_VERTICES",
        "maximum_navigation_polygons": "MAX_NAVIGATION_POLYGONS",
        "maximum_navigation_indices": "MAX_NAVIGATION_INDICES",
        "maximum_hlod_levels": "MAX_HLOD_LEVELS",
        "maximum_hlod_cross_fade_steps": "MAX_HLOD_CROSS_FADE_STEPS",
        "maximum_path_collision_projections": "MAX_PATH_COLLISION_PROJECTIONS",
        "maximum_path_collision_vertices": "MAX_PATH_COLLISION_VERTICES",
        "maximum_path_collision_extent_m": "MAX_PATH_COLLISION_EXTENT_M",
        "maximum_path_collision_shapes_per_projection": (
            "MAX_PATH_COLLISION_SHAPES_PER_PROJECTION"
        ),
        "maximum_foliage_projection_area_m2": (
            "MAX_FOLIAGE_PROJECTION_AREA_M2"
        ),
        "maximum_navigation_agent_radius_m": "MAX_NAVIGATION_AGENT_RADIUS_M",
        "maximum_navigation_agent_height_m": "MAX_NAVIGATION_AGENT_HEIGHT_M",
        "maximum_navigation_agent_slope_degrees": (
            "MAX_NAVIGATION_AGENT_SLOPE_DEGREES"
        ),
        "maximum_allowed_resource_paths": "MAX_ALLOWED_RESOURCE_PATHS",
        "maximum_result_receipts": "MAX_RESULT_RECEIPTS",
    }
    for key, constant in extended_limit_markers.items():
        value = extended_hard_limits.get(key)
        if not isinstance(value, int) or f"const {constant} := {value}" not in companion_source:
            fail(f"extended companion limit drift for {key}")
    if extended_hard_limits.get("maximum_installed_per_capability") != 128:
        fail("extended installed-projection limit drift")
    if "max_installed_per_capability) > 128" not in companion_source:
        fail("extended installed-projection enforcement drift")

    expected_quality_tiers = {
        "high": {
            "maximum_density_per_square_m": 2.0,
            "maximum_instances": 2048,
        },
        "low": {
            "maximum_density_per_square_m": 0.25,
            "maximum_instances": 256,
        },
        "medium": {
            "maximum_density_per_square_m": 1.0,
            "maximum_instances": 1024,
        },
    }
    if companion.get("foliage_quality_tiers") != expected_quality_tiers:
        fail("extended foliage quality-tier contract drift")
    for name, tier in expected_quality_tiers.items():
        if (
            f'&"{name}": {{' not in companion_source
            or f'"maximum_instances": {tier["maximum_instances"]}'
            not in companion_source
            or f'"maximum_density_per_square_m": '
            f'{tier["maximum_density_per_square_m"]}' not in companion_source
        ):
            fail(f"extended foliage quality-tier implementation drift for {name}")
    expected_collision_shapes = [
        "box",
        "capsule",
        "concave_polygon",
        "convex_polygon",
        "cylinder",
    ]
    if companion.get("path_collision_shapes") != expected_collision_shapes:
        fail("extended path-collision shape contract drift")
    shape_markers = {
        "box": "shape is BoxShape3D",
        "capsule": "shape is CapsuleShape3D",
        "concave_polygon": "shape is ConcavePolygonShape3D",
        "convex_polygon": "shape is ConvexPolygonShape3D",
        "cylinder": "shape is CylinderShape3D",
    }
    for shape_name in expected_collision_shapes:
        if shape_markers[shape_name] not in companion_source:
            fail(f"extended path-collision implementation drift for {shape_name}")

    for key, value in require_mapping(
        extended.get("native_required_capabilities"),
        "profiles.web_extended.native_required_capabilities",
    ).items():
        require_cpp_capability(implementation, key, value)

    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def main() -> int:
    digest = verify()
    print(f"MTERRAIN_WEB_RUNTIME_CONTRACT_OK {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
