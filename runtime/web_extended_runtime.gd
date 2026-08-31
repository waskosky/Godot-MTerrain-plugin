class_name MTerrainWebExtendedRuntime
extends Node3D

## Bounded, data-first Web projections for optional MTerrain consumers.
##
## This runtime deliberately accepts already validated project resources. It
## does not expose editor controls, bake curves, generate navigation meshes, or
## use threads. Replacements remain invisible until their staged projection is
## complete, and every installed node has one deterministic release owner.

const API_VERSION := 1
const CAPABILITIES := [&"foliage", &"navigation", &"paths", &"mesh_hlod"]
const MAX_PENDING_LIMIT := 128
const MAX_FOLIAGE_LIMIT := 8192
const MAX_MESH_VERTICES := 65536
const MAX_MESH_INDICES := 262144
const MAX_NAVIGATION_VERTICES := 8192
const MAX_NAVIGATION_POLYGONS := 8192
const MAX_NAVIGATION_INDICES := 65536
const MAX_HLOD_LEVELS := 4
const MAX_HLOD_CROSS_FADE_STEPS := 16
const MAX_PATH_COLLISION_PROJECTIONS := 64
const MAX_PATH_COLLISION_VERTICES := 65536
const MAX_PATH_COLLISION_EXTENT_M := 10000
const MAX_PATH_COLLISION_SHAPES_PER_PROJECTION := 1
const MAX_FOLIAGE_PROJECTION_AREA_M2 := 16777216
const MAX_NAVIGATION_AGENT_RADIUS_M := 1000
const MAX_NAVIGATION_AGENT_HEIGHT_M := 1000
const MAX_NAVIGATION_AGENT_SLOPE_DEGREES := 90
const MAX_ALLOWED_RESOURCE_PATHS := 256
const MAX_RESULT_RECEIPTS := 256
const FOLIAGE_QUALITY_TIERS := {
	&"low": {
		"maximum_instances": 256,
		"maximum_density_per_square_m": 0.25,
	},
	&"medium": {
		"maximum_instances": 1024,
		"maximum_density_per_square_m": 1.0,
	},
	&"high": {
		"maximum_instances": 2048,
		"maximum_density_per_square_m": 2.0,
	},
}

var _limits := {
	"max_pending_work": 32,
	"max_foliage_instances": 2048,
	"max_installed_per_capability": 32,
	"max_mesh_vertices": MAX_MESH_VERTICES,
	"max_mesh_indices": 196608,
	"max_navigation_vertices": 4096,
	"max_navigation_polygons": 4096,
	"max_navigation_indices": 32768,
	"hlod_hysteresis_m": 2.0,
	"hlod_cross_fade_steps": 0,
	"allow_path_collision": false,
	"max_path_collision_projections": 8,
	"max_path_collision_vertices": 8192,
	"max_path_collision_extent_m": 4096.0,
	"path_collision_layer": 1,
	"path_collision_mask": 1,
	"allow_in_memory_resources": false,
	"allowed_resource_paths": PackedStringArray(),
}
var _pending: Array[Dictionary] = []
var _installed := {
	&"foliage": {},
	&"navigation": {},
	&"paths": {},
	&"mesh_hlod": {},
}
var _results: Array[Dictionary] = []
var _sequence := 0
var _metrics := {
	"queued": 0,
	"completed": 0,
	"cancelled": 0,
	"coalesced": 0,
	"released": 0,
	"foliage_instance_writes": 0,
	"hlod_swaps": 0,
	"hlod_transition_starts": 0,
	"hlod_transition_steps": 0,
	"hlod_transition_cancellations": 0,
	"path_collision_installs": 0,
	"steps": 0,
	"longest_step_usec": 0,
}


func get_runtime_capabilities() -> Dictionary:
	return {
		"api_version": API_VERSION,
		"api_stability": "experimental",
		"single_threaded": true,
		"foliage": true,
		"navigation": true,
		"paths": true,
		"mesh_hlod": true,
		"foliage_collision": false,
		"runtime_navigation_baking": false,
		"runtime_curve_deformation": false,
		"path_collision": true,
		"prebaked_path_collision": true,
		"runtime_path_collision_generation": false,
		"maximum_path_collision_shapes_per_projection": (
			MAX_PATH_COLLISION_SHAPES_PER_PROJECTION
		),
		"runtime_mesh_generation": false,
		"bounded_foliage_quality_tiers": true,
		"foliage_quality_tiers": _public_foliage_quality_tiers(),
		"navigation_agent_profiles": true,
		"hlod_cross_fade": true,
		"maximum_hlod_cross_fade_steps": MAX_HLOD_CROSS_FADE_STEPS,
		"maximum_hlod_levels": MAX_HLOD_LEVELS,
		"limits": _public_limits(),
	}


func configure_limits(configuration: Dictionary) -> Dictionary:
	if not _pending.is_empty():
		return _error("work_in_progress", "Limits cannot change while work is pending.")
	var candidate := _limits.duplicate(true)
	for key in configuration:
		if not candidate.has(key):
			return _error("unknown_limit", "Unknown extended runtime limit: %s" % key)
		candidate[key] = configuration[key]
	for integer_key in [
		"max_pending_work",
		"max_foliage_instances",
		"max_installed_per_capability",
		"max_mesh_vertices",
		"max_mesh_indices",
		"max_navigation_vertices",
		"max_navigation_polygons",
		"max_navigation_indices",
		"hlod_cross_fade_steps",
		"max_path_collision_projections",
		"max_path_collision_vertices",
		"path_collision_layer",
		"path_collision_mask",
	]:
		if not (candidate[integer_key] is int):
			return _error("invalid_limit_type", "%s must be an integer." % integer_key)
	if not (candidate.hlod_hysteresis_m is int or candidate.hlod_hysteresis_m is float) \
	or not is_finite(float(candidate.hlod_hysteresis_m)) \
	or float(candidate.hlod_hysteresis_m) < 0.0 \
	or float(candidate.hlod_hysteresis_m) > 10000.0:
		return _error("invalid_hlod_hysteresis", "hlod_hysteresis_m must be finite and between 0 and 10000.")
	if not (candidate.max_path_collision_extent_m is int \
	or candidate.max_path_collision_extent_m is float) \
	or not is_finite(float(candidate.max_path_collision_extent_m)) \
	or float(candidate.max_path_collision_extent_m) <= 0.0 \
	or float(candidate.max_path_collision_extent_m) > MAX_PATH_COLLISION_EXTENT_M:
		return _error(
			"invalid_path_collision_extent",
			"max_path_collision_extent_m must be finite and between 0 and 10000.",
		)
	if not (candidate.allow_path_collision is bool):
		return _error("invalid_path_collision_policy", "allow_path_collision must be a bool.")
	if int(candidate.max_pending_work) < 1 or int(candidate.max_pending_work) > MAX_PENDING_LIMIT:
		return _error("invalid_pending_limit", "max_pending_work must be between 1 and 128.")
	if int(candidate.max_foliage_instances) < 1 \
	or int(candidate.max_foliage_instances) > MAX_FOLIAGE_LIMIT:
		return _error("invalid_foliage_limit", "max_foliage_instances must be between 1 and 8192.")
	if int(candidate.max_installed_per_capability) < 1 \
	or int(candidate.max_installed_per_capability) > 128:
		return _error("invalid_install_limit", "max_installed_per_capability must be between 1 and 128.")
	if int(candidate.max_mesh_vertices) < 3 \
	or int(candidate.max_mesh_vertices) > MAX_MESH_VERTICES:
		return _error("invalid_mesh_limit", "max_mesh_vertices must be between 3 and 65536.")
	if int(candidate.max_mesh_indices) < 3 \
	or int(candidate.max_mesh_indices) > MAX_MESH_INDICES:
		return _error("invalid_mesh_index_limit", "max_mesh_indices must be between 3 and 262144.")
	if int(candidate.max_navigation_vertices) < 3 \
	or int(candidate.max_navigation_vertices) > MAX_NAVIGATION_VERTICES:
		return _error("invalid_navigation_vertex_limit", "Navigation vertex limit is out of range.")
	if int(candidate.max_navigation_polygons) < 1 \
	or int(candidate.max_navigation_polygons) > MAX_NAVIGATION_POLYGONS:
		return _error("invalid_navigation_polygon_limit", "Navigation polygon limit is out of range.")
	if int(candidate.max_navigation_indices) < 3 \
	or int(candidate.max_navigation_indices) > MAX_NAVIGATION_INDICES:
		return _error("invalid_navigation_index_limit", "Navigation index limit is out of range.")
	if int(candidate.hlod_cross_fade_steps) < 0 \
	or int(candidate.hlod_cross_fade_steps) > MAX_HLOD_CROSS_FADE_STEPS:
		return _error(
			"invalid_hlod_cross_fade_steps",
			"hlod_cross_fade_steps must be between 0 and 16.",
		)
	if int(candidate.max_path_collision_projections) < 1 \
	or int(candidate.max_path_collision_projections) > MAX_PATH_COLLISION_PROJECTIONS:
		return _error(
			"invalid_path_collision_projection_limit",
			"max_path_collision_projections must be between 1 and 64.",
		)
	if int(candidate.max_path_collision_vertices) < 8 \
	or int(candidate.max_path_collision_vertices) > MAX_PATH_COLLISION_VERTICES:
		return _error(
			"invalid_path_collision_vertex_limit",
			"max_path_collision_vertices must be between 8 and 65536.",
		)
	for collision_mask_key in [&"path_collision_layer", &"path_collision_mask"]:
		if int(candidate[collision_mask_key]) < 0 \
		or int(candidate[collision_mask_key]) > 0xffffffff:
			return _error(
				"invalid_path_collision_mask",
				"Path collision layers and masks must be unsigned 32-bit values.",
			)
	if not (candidate.allowed_resource_paths is PackedStringArray):
		return _error("invalid_resource_allowlist", "allowed_resource_paths must be a PackedStringArray.")
	if not (candidate.allow_in_memory_resources is bool):
		return _error("invalid_in_memory_policy", "allow_in_memory_resources must be a bool.")
	if candidate.allowed_resource_paths.size() > MAX_ALLOWED_RESOURCE_PATHS:
		return _error("resource_allowlist_limit", "At most 256 resource paths may be allowlisted.")
	var seen_paths := {}
	for path in candidate.allowed_resource_paths:
		var normalized := str(path)
		var relative := normalized.trim_prefix("res://")
		if not normalized.begins_with("res://") \
		or normalized.length() > 256 \
		or relative.is_empty() \
		or relative.contains("\\") \
		or relative.contains("//") \
		or "/../" in ("/" + relative + "/") \
		or "/./" in ("/" + relative + "/"):
			return _error("invalid_resource_allowlist", "Only res:// resources may be allowlisted.")
		if seen_paths.has(normalized):
			return _error("duplicate_resource_path", "Resource allowlist entries must be unique.")
		seen_paths[normalized] = true
	if _has_installed_projections() \
	and (candidate.allow_in_memory_resources != _limits.allow_in_memory_resources \
		or candidate.allowed_resource_paths != _limits.allowed_resource_paths):
		return _error(
			"resource_policy_in_use",
			"Release installed projections before changing the resource policy.",
		)
	var installed_check := _validate_installed_limits(candidate)
	if not installed_check.ok:
		return installed_check
	_limits = candidate
	return {"ok": true, "code": "ok", "limits": _public_limits()}


func queue_foliage(
	work_key: String,
	revision: int,
	priority: int,
	mesh: Mesh,
	transforms: Array,
	material: Material = null,
	quality_tier: StringName = &"custom",
	projection_area_m2: float = 0.0
) -> Dictionary:
	var common := _validate_common(&"foliage", work_key, revision, priority)
	if not common.ok or common.has("status"):
		return common
	var resource_check := _validate_resource(mesh, "foliage mesh")
	if not resource_check.ok:
		return resource_check
	if material != null:
		resource_check = _validate_resource(material, "foliage material")
		if not resource_check.ok:
			return resource_check
	var mesh_check := _validate_mesh(mesh)
	if not mesh_check.ok:
		return mesh_check
	if transforms.is_empty() or transforms.size() > int(_limits.max_foliage_instances):
		return _error("foliage_instance_limit", "Foliage transform count exceeds its configured bound.")
	var quality_check := _validate_foliage_quality(
		quality_tier,
		projection_area_m2,
		transforms.size(),
	)
	if not quality_check.ok:
		return quality_check
	for transform in transforms:
		if not (transform is Transform3D) or not _finite_transform(transform):
			return _error("invalid_foliage_transform", "Every foliage transform must be finite Transform3D data.")
	var multimesh := MultiMesh.new()
	multimesh.transform_format = MultiMesh.TRANSFORM_3D
	multimesh.mesh = mesh
	multimesh.instance_count = transforms.size()
	var projection := MultiMeshInstance3D.new()
	projection.name = _projection_name(&"foliage", work_key)
	projection.multimesh = multimesh
	projection.material_override = material
	return _enqueue({
		"capability": &"foliage",
		"work_key": work_key,
		"revision": revision,
		"priority": priority,
		"sequence": _next_sequence(),
		"cursor": 0,
		"transforms": transforms.duplicate(true),
		"projection": projection,
		"quality_tier": quality_tier,
		"projection_area_m2": projection_area_m2,
		"vertex_count": int(mesh_check.vertex_count),
		"index_count": int(mesh_check.index_count),
	})


func queue_navigation(
	work_key: String,
	revision: int,
	priority: int,
	navigation_mesh: NavigationMesh,
	transform: Transform3D = Transform3D.IDENTITY
) -> Dictionary:
	var common := _validate_common(&"navigation", work_key, revision, priority)
	if not common.ok or common.has("status"):
		return common
	var resource_check := _validate_resource(navigation_mesh, "navigation mesh")
	if not resource_check.ok:
		return resource_check
	if not _finite_transform(transform):
		return _error("invalid_navigation_transform", "Navigation transform must be finite.")
	var navigation_check := _validate_navigation_mesh(navigation_mesh)
	if not navigation_check.ok:
		return navigation_check
	var projection := NavigationRegion3D.new()
	projection.name = _projection_name(&"navigation", work_key)
	projection.navigation_mesh = navigation_mesh
	projection.transform = transform
	return _enqueue({
		"capability": &"navigation",
		"work_key": work_key,
		"revision": revision,
		"priority": priority,
		"sequence": _next_sequence(),
		"cursor": 1,
		"projection": projection,
		"vertex_count": int(navigation_check.vertex_count),
		"polygon_count": int(navigation_check.polygon_count),
		"index_count": int(navigation_check.index_count),
		"navigation_agent_radius_m": float(navigation_check.agent_radius_m),
		"navigation_agent_height_m": float(navigation_check.agent_height_m),
		"navigation_agent_max_slope_degrees": float(
			navigation_check.agent_max_slope_degrees
		),
	})


func queue_path(
	work_key: String,
	revision: int,
	priority: int,
	baked_mesh: Mesh,
	transform: Transform3D = Transform3D.IDENTITY,
	material: Material = null,
	collision_shape: Shape3D = null
) -> Dictionary:
	var common := _validate_common(&"paths", work_key, revision, priority)
	if not common.ok or common.has("status"):
		return common
	var resource_check := _validate_resource(baked_mesh, "path mesh")
	if not resource_check.ok:
		return resource_check
	if material != null:
		resource_check = _validate_resource(material, "path material")
		if not resource_check.ok:
			return resource_check
	var mesh_check := _validate_mesh(baked_mesh)
	if not mesh_check.ok:
		return mesh_check
	if not _finite_transform(transform):
		return _error("invalid_path_transform", "Path transform must be finite.")
	var collision_check := {
		"ok": true,
		"code": "ok",
		"vertex_count": 0,
		"extent_m": 0.0,
	}
	if collision_shape != null:
		if not bool(_limits.allow_path_collision):
			return _error(
				"path_collision_disabled",
				"Pre-baked path collision requires explicit allow_path_collision opt-in.",
			)
		resource_check = _validate_resource(collision_shape, "path collision shape")
		if not resource_check.ok:
			return resource_check
		collision_check = _validate_path_collision_shape(collision_shape)
		if not collision_check.ok:
			return collision_check
		if _owned_path_collision_count(work_key) >= int(_limits.max_path_collision_projections):
			return _error(
				"path_collision_projection_limit",
				"Pre-baked path collision ownership exceeds its configured bound.",
			)
	var projection := Node3D.new()
	projection.name = _projection_name(&"paths", work_key)
	projection.transform = transform
	var mesh_projection := MeshInstance3D.new()
	mesh_projection.name = "Visual"
	mesh_projection.mesh = baked_mesh
	mesh_projection.material_override = material
	projection.add_child(mesh_projection)
	if collision_shape != null:
		var body := StaticBody3D.new()
		body.name = "PrebakedCollision"
		body.collision_layer = int(_limits.path_collision_layer)
		body.collision_mask = int(_limits.path_collision_mask)
		var collision := CollisionShape3D.new()
		collision.name = "Shape"
		collision.shape = collision_shape
		body.add_child(collision)
		projection.add_child(body)
	return _enqueue({
		"capability": &"paths",
		"work_key": work_key,
		"revision": revision,
		"priority": priority,
		"sequence": _next_sequence(),
		"cursor": 1,
		"projection": projection,
		"vertex_count": int(mesh_check.vertex_count),
		"index_count": int(mesh_check.index_count),
		"collision_shape_count": MAX_PATH_COLLISION_SHAPES_PER_PROJECTION \
			if collision_shape != null else 0,
		"collision_vertex_count": int(collision_check.vertex_count),
		"collision_extent_m": float(collision_check.extent_m),
	})


func queue_mesh_hlod(
	work_key: String,
	revision: int,
	priority: int,
	meshes: Array,
	distances: PackedFloat32Array,
	transform: Transform3D = Transform3D.IDENTITY,
	material: Material = null
) -> Dictionary:
	var common := _validate_common(&"mesh_hlod", work_key, revision, priority)
	if not common.ok or common.has("status"):
		return common
	if meshes.is_empty() or meshes.size() > MAX_HLOD_LEVELS or distances.size() != meshes.size():
		return _error("hlod_level_limit", "Mesh HLOD requires one to four meshes and one distance per mesh.")
	var previous_distance := -1.0
	var total_vertices := 0
	var total_indices := 0
	for index in meshes.size():
		if not (meshes[index] is Mesh):
			return _error("invalid_hlod_mesh", "Every HLOD level must contain a Mesh.")
		var resource_check := _validate_resource(meshes[index], "HLOD mesh")
		if not resource_check.ok:
			return resource_check
		var mesh_check := _validate_mesh(meshes[index])
		if not mesh_check.ok:
			return mesh_check
		total_vertices += int(mesh_check.vertex_count)
		total_indices += int(mesh_check.index_count)
		if total_vertices > int(_limits.max_mesh_vertices):
			return _error("hlod_total_vertex_limit", "Combined HLOD levels exceed max_mesh_vertices.")
		if total_indices > int(_limits.max_mesh_indices):
			return _error("hlod_total_index_limit", "Combined HLOD levels exceed max_mesh_indices.")
		var distance := float(distances[index])
		if not is_finite(distance) or distance < 0.0 or distance <= previous_distance:
			return _error("invalid_hlod_distances", "HLOD distances must be finite and strictly increasing.")
		previous_distance = distance
	if material != null:
		var material_check := _validate_resource(material, "HLOD material")
		if not material_check.ok:
			return material_check
	if not _finite_transform(transform):
		return _error("invalid_hlod_transform", "HLOD transform must be finite.")
	var projection := Node3D.new()
	projection.name = _projection_name(&"mesh_hlod", work_key)
	projection.transform = transform
	var active_projection := MeshInstance3D.new()
	active_projection.name = "Active"
	active_projection.mesh = meshes[0]
	active_projection.material_override = material
	projection.add_child(active_projection)
	var incoming_projection := MeshInstance3D.new()
	incoming_projection.name = "Incoming"
	incoming_projection.material_override = material
	incoming_projection.transparency = 1.0
	incoming_projection.visible = false
	projection.add_child(incoming_projection)
	return _enqueue({
		"capability": &"mesh_hlod",
		"work_key": work_key,
		"revision": revision,
		"priority": priority,
		"sequence": _next_sequence(),
		"cursor": 1,
		"projection": projection,
		"meshes": meshes.duplicate(),
		"distances": distances.duplicate(),
		"lod_index": 0,
		"target_lod_index": 0,
		"fade_step": 0,
		"fade_steps": int(_limits.hlod_cross_fade_steps),
		"transition_active": false,
		"active_projection": active_projection,
		"incoming_projection": incoming_projection,
		"vertex_count": total_vertices,
		"index_count": total_indices,
	})


func step_runtime_work(
	max_instance_ops: int,
	max_apply_ops: int,
	focus_position: Vector3 = Vector3.ZERO
) -> Dictionary:
	if max_instance_ops < 1 or max_instance_ops > MAX_FOLIAGE_LIMIT:
		return _error("invalid_instance_budget", "max_instance_ops must be between 1 and 8192.")
	if max_apply_ops < 1 or max_apply_ops > 64:
		return _error("invalid_apply_budget", "max_apply_ops must be between 1 and 64.")
	if not _finite_vector3(focus_position):
		return _error("invalid_focus_position", "HLOD focus position must be finite.")
	var started_usec := Time.get_ticks_usec()
	_metrics.steps += 1
	var instance_ops := 0
	var apply_ops := 0
	var completed: Array[Dictionary] = []
	while apply_ops < max_apply_ops and not _pending.is_empty():
		var index := _choose_pending()
		var work := _pending[index]
		if bool(work.get("cancelled", false)):
			_dispose_projection(work.projection)
			_pending.remove_at(index)
			apply_ops += 1
			_metrics.cancelled += 1
			var cancelled := _error("cancelled", "Extended runtime work was cancelled before installation.")
			cancelled.merge({"work_key": work.work_key, "revision": work.revision, "status": "cancelled"})
			_push_result(cancelled)
			completed.append(cancelled)
			continue
		if work.capability == &"foliage":
			var transforms: Array = work.transforms
			var multimesh: MultiMesh = work.projection.multimesh
			while int(work.cursor) < transforms.size() and instance_ops < max_instance_ops:
				multimesh.set_instance_transform(int(work.cursor), transforms[int(work.cursor)])
				work.cursor = int(work.cursor) + 1
				instance_ops += 1
				_metrics.foliage_instance_writes += 1
			_pending[index] = work
		if int(work.cursor) < _work_size(work) or apply_ops >= max_apply_ops:
			break
		_install(work)
		_pending.remove_at(index)
		apply_ops += 1
		_metrics.completed += 1
		var receipt := {
			"ok": true,
			"code": "ok",
			"status": "completed",
			"capability": work.capability,
			"work_key": work.work_key,
			"revision": work.revision,
		}
		if work.capability == &"foliage":
			receipt.instance_count = work.transforms.size()
		_push_result(receipt)
		completed.append(receipt)
	while apply_ops < max_apply_ops:
		var swapped := _step_one_hlod(focus_position)
		if not swapped:
			break
		apply_ops += 1
	var hlod_pending := _hlod_needs_swap(focus_position)
	var elapsed_usec := Time.get_ticks_usec() - started_usec
	_metrics.longest_step_usec = max(int(_metrics.longest_step_usec), elapsed_usec)
	return {
		"ok": true,
		"code": "ok",
		"status": "idle" if _pending.is_empty() and not hlod_pending else "pending",
		"instance_ops": instance_ops,
		"apply_ops": apply_ops,
		"elapsed_usec": elapsed_usec,
		"completed": completed,
		"pending_work": _pending.size(),
	}


func cancel_runtime_work(work_key: String, revision := -1) -> Dictionary:
	var index := _find_pending(work_key)
	if index < 0:
		return {"ok": true, "code": "ok", "status": "not_pending"}
	if revision >= 0 and int(_pending[index].revision) != revision:
		return _error("revision_mismatch", "Pending revision does not match cancellation request.")
	_pending[index].cancelled = true
	return {"ok": true, "code": "ok", "status": "cancellation_queued"}


func release_projection(capability: StringName, work_key: String, revision := -1) -> Dictionary:
	if capability not in CAPABILITIES:
		return _error("unsupported_capability", "Unknown extended runtime capability.")
	var pending_index := _find_pending(work_key, capability)
	var installed_for_capability: Dictionary = _installed[capability]
	var has_installed := installed_for_capability.has(work_key)
	var pending_matches := pending_index >= 0 \
	and (revision < 0 or int(_pending[pending_index].revision) == revision)
	var installed_matches := has_installed \
	and (revision < 0 or int(installed_for_capability[work_key].revision) == revision)
	if revision >= 0 and not pending_matches and not installed_matches:
		return _error("revision_mismatch", "No pending or installed projection matches the release revision.")
	if pending_matches:
		var pending_work: Dictionary = _pending[pending_index]
		_dispose_projection(pending_work.projection)
		_pending.remove_at(pending_index)
		_metrics.cancelled += 1
		var cancelled := _error("cancelled", "Extended runtime work was released before installation.")
		cancelled.merge({
			"capability": capability,
			"work_key": work_key,
			"revision": pending_work.revision,
			"status": "cancelled",
		})
		_push_result(cancelled)
	if installed_matches:
		var record: Dictionary = installed_for_capability[work_key]
		_dispose_projection(record.projection)
		installed_for_capability.erase(work_key)
		_metrics.released += 1
	return {
		"ok": true,
		"code": "ok",
		"status": "released" if installed_matches else (
			"pending_released" if pending_matches else "already_released"
		),
	}


func take_runtime_work_result(work_key: String, revision: int) -> Dictionary:
	for index in _results.size():
		if str(_results[index].get("work_key", "")) == work_key \
		and int(_results[index].get("revision", -1)) == revision:
			var result := _results[index]
			_results.remove_at(index)
			return result
	return _error("result_not_found", "No completed result matches this work key and revision.")


func get_runtime_state() -> Dictionary:
	var installed_counts := {}
	var installed_vertices := {}
	var installed_indices := {}
	var installed_instances := {}
	var installed_polygons := {}
	var installed_collision_shapes := {}
	var installed_collision_vertices := {}
	var installed_foliage_quality_tiers := {
		&"low": 0,
		&"medium": 0,
		&"high": 0,
		&"custom": 0,
	}
	var installed_records := {}
	for capability in CAPABILITIES:
		var installed_for_capability: Dictionary = _installed[capability]
		installed_counts[capability] = installed_for_capability.size()
		var vertex_count := 0
		var index_count := 0
		var instance_count := 0
		var polygon_count := 0
		var collision_shape_count := 0
		var collision_vertex_count := 0
		var records: Array[Dictionary] = []
		for record in installed_for_capability.values():
			vertex_count += int(record.get("vertex_count", 0))
			index_count += int(record.get("index_count", 0))
			polygon_count += int(record.get("polygon_count", 0))
			collision_shape_count += int(record.get("collision_shape_count", 0))
			collision_vertex_count += int(record.get("collision_vertex_count", 0))
			if capability == &"foliage":
				instance_count += (record.transforms as Array).size()
				var quality_tier := StringName(record.get("quality_tier", &"custom"))
				installed_foliage_quality_tiers[quality_tier] = (
					int(installed_foliage_quality_tiers.get(quality_tier, 0))
					+ (record.transforms as Array).size()
				)
			records.append({
				"work_key": record.work_key,
				"revision": record.revision,
				"vertex_count": int(record.get("vertex_count", 0)),
				"index_count": int(record.get("index_count", 0)),
				"polygon_count": int(record.get("polygon_count", 0)),
				"instance_count": (record.transforms as Array).size() \
					if capability == &"foliage" else 0,
				"quality_tier": str(record.get("quality_tier", "")),
				"projection_area_m2": float(record.get("projection_area_m2", 0.0)),
				"collision_shape_count": int(record.get("collision_shape_count", 0)),
				"collision_vertex_count": int(record.get("collision_vertex_count", 0)),
				"lod_index": int(record.get("lod_index", -1)),
				"target_lod_index": int(record.get("target_lod_index", -1)),
				"hlod_transition_active": bool(record.get("transition_active", false)),
				"hlod_fade_step": int(record.get("fade_step", 0)),
				"hlod_fade_steps": int(record.get("fade_steps", 0)),
				"navigation_agent_radius_m": float(
					record.get("navigation_agent_radius_m", 0.0)
				),
				"navigation_agent_height_m": float(
					record.get("navigation_agent_height_m", 0.0)
				),
				"navigation_agent_max_slope_degrees": float(
					record.get("navigation_agent_max_slope_degrees", 0.0)
				),
			})
		records.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return str(a.work_key) < str(b.work_key))
		installed_vertices[capability] = vertex_count
		installed_indices[capability] = index_count
		installed_instances[capability] = instance_count
		installed_polygons[capability] = polygon_count
		installed_collision_shapes[capability] = collision_shape_count
		installed_collision_vertices[capability] = collision_vertex_count
		installed_records[capability] = records
	var pending_state: Array[Dictionary] = []
	for work in _pending:
		pending_state.append({
			"capability": work.capability,
			"work_key": work.work_key,
			"revision": work.revision,
			"priority": work.priority,
			"cursor": work.cursor,
			"work_size": _work_size(work),
			"cancelled": bool(work.get("cancelled", false)),
		})
	return {
		"kind": "mterrain-web-extended-runtime-state/v1",
		"pending": pending_state,
		"installed_counts": installed_counts,
		"installed_vertices": installed_vertices,
		"installed_indices": installed_indices,
		"installed_instances": installed_instances,
		"installed_polygons": installed_polygons,
		"installed_collision_shapes": installed_collision_shapes,
		"installed_collision_vertices": installed_collision_vertices,
		"installed_foliage_quality_tiers": installed_foliage_quality_tiers,
		"installed": installed_records,
		"limits": _public_limits(),
		"metrics": _metrics.duplicate(true),
	}


func _validate_common(
	capability: StringName,
	work_key: String,
	revision: int,
	priority: int
) -> Dictionary:
	if capability not in CAPABILITIES:
		return _error("unsupported_capability", "Unsupported extended runtime capability.")
	if work_key.is_empty() or work_key.length() > 128:
		return _error("invalid_work_key", "work_key must contain between 1 and 128 characters.")
	if revision < 0:
		return _error("invalid_revision", "revision must be non-negative.")
	if priority < -1000 or priority > 1000:
		return _error("invalid_priority", "priority must be between -1000 and 1000.")
	var pending_index := _find_pending(work_key)
	if pending_index >= 0:
		if _pending[pending_index].capability != capability:
			return _error("work_key_conflict", "work_key is already owned by another capability.")
		var pending_revision := int(_pending[pending_index].revision)
		if pending_revision > revision:
			return _error("stale_revision", "A newer revision is already pending.")
		if pending_revision == revision:
			if bool(_pending[pending_index].get("cancelled", false)):
				return _error("revision_cancelling", "The matching revision is queued for cancellation.")
			return {
				"ok": true,
				"code": "ok",
				"status": "already_queued",
				"capability": capability,
				"work_key": work_key,
				"revision": revision,
			}
	for installed_capability in CAPABILITIES:
		var installed_for_capability: Dictionary = _installed[installed_capability]
		if not installed_for_capability.has(work_key):
			continue
		if installed_capability != capability:
			return _error("work_key_conflict", "work_key is already owned by another capability.")
		var installed_revision := int(installed_for_capability[work_key].revision)
		if installed_revision > revision:
			return _error("stale_revision", "A newer revision is already installed.")
		if installed_revision == revision:
			return {
				"ok": true,
				"code": "ok",
				"status": "already_installed",
				"capability": capability,
				"work_key": work_key,
				"revision": revision,
			}
	if pending_index < 0 and _pending.size() >= int(_limits.max_pending_work):
		return _error("pending_work_limit", "The extended runtime work queue is full.")
	if not _capability_owns_key(capability, work_key) \
	and _capability_owned_key_count(capability) >= int(_limits.max_installed_per_capability):
		return _error(
			"installed_projection_limit",
			"The capability already owns its maximum number of projection keys.",
		)
	return {"ok": true, "code": "ok"}


func _enqueue(work: Dictionary) -> Dictionary:
	var pending_index := _find_pending(work.work_key, work.capability)
	if pending_index >= 0:
		var displaced: Dictionary = _pending[pending_index]
		_dispose_projection(displaced.projection)
		_pending.remove_at(pending_index)
		_metrics.coalesced += 1
		var coalesced := _error("coalesced", "Extended runtime work was superseded before installation.")
		coalesced.merge({
			"capability": displaced.capability,
			"work_key": displaced.work_key,
			"revision": displaced.revision,
			"status": "coalesced",
		})
		_push_result(coalesced)
	if _pending.size() >= int(_limits.max_pending_work):
		_dispose_projection(work.projection)
		return _error("pending_work_limit", "The extended runtime work queue is full.")
	_pending.append(work)
	_metrics.queued += 1
	return {
		"ok": true,
		"code": "ok",
		"status": "queued",
		"capability": work.capability,
		"work_key": work.work_key,
		"revision": work.revision,
		"work_size": _work_size(work),
	}


func _install(work: Dictionary) -> void:
	var installed_for_capability: Dictionary = _installed[work.capability]
	if installed_for_capability.has(work.work_key):
		_dispose_projection(installed_for_capability[work.work_key].projection)
	add_child(work.projection)
	installed_for_capability[work.work_key] = work
	if work.capability == &"paths" and int(work.get("collision_shape_count", 0)) > 0:
		_metrics.path_collision_installs += 1


func _step_one_hlod(focus_position: Vector3) -> bool:
	var installed_hlod: Dictionary = _installed[&"mesh_hlod"]
	var keys := installed_hlod.keys()
	keys.sort()
	for key in keys:
		var record: Dictionary = installed_hlod[key]
		var active_projection: MeshInstance3D = record.active_projection
		var incoming_projection: MeshInstance3D = record.incoming_projection
		var next_index := _desired_hlod_index(record, focus_position)
		if bool(record.transition_active):
			if next_index != int(record.target_lod_index):
				active_projection.transparency = 0.0
				incoming_projection.visible = false
				incoming_projection.mesh = null
				incoming_projection.transparency = 1.0
				record.transition_active = false
				record.target_lod_index = record.lod_index
				record.fade_step = 0
				installed_hlod[key] = record
				_metrics.hlod_transition_cancellations += 1
				return true
			var fade_steps: int = max(1, int(record.fade_steps))
			var fade_step: int = min(fade_steps, int(record.fade_step) + 1)
			var progress := float(fade_step) / float(fade_steps)
			active_projection.transparency = progress
			incoming_projection.transparency = 1.0 - progress
			record.fade_step = fade_step
			_metrics.hlod_transition_steps += 1
			if fade_step >= fade_steps:
				active_projection.mesh = incoming_projection.mesh
				active_projection.transparency = 0.0
				incoming_projection.visible = false
				incoming_projection.mesh = null
				incoming_projection.transparency = 1.0
				record.lod_index = record.target_lod_index
				record.transition_active = false
				record.fade_step = 0
				_metrics.hlod_swaps += 1
			installed_hlod[key] = record
			return true
		if next_index == int(record.lod_index):
			continue
		if int(record.fade_steps) <= 0:
			active_projection.mesh = record.meshes[next_index]
			record.lod_index = next_index
			record.target_lod_index = next_index
			installed_hlod[key] = record
			_metrics.hlod_swaps += 1
			return true
		incoming_projection.mesh = record.meshes[next_index]
		incoming_projection.transparency = 1.0
		incoming_projection.visible = true
		record.target_lod_index = next_index
		record.transition_active = true
		record.fade_step = 0
		installed_hlod[key] = record
		_metrics.hlod_transition_starts += 1
		return true
	return false


func _hlod_needs_swap(focus_position: Vector3) -> bool:
	var installed_hlod: Dictionary = _installed[&"mesh_hlod"]
	for record in installed_hlod.values():
		if bool(record.get("transition_active", false)) \
		or _desired_hlod_index(record, focus_position) != int(record.lod_index):
			return true
	return false


func _desired_hlod_index(record: Dictionary, focus_position: Vector3) -> int:
	var projection: Node3D = record.projection
	var distance := projection.global_position.distance_to(focus_position)
	var distances: PackedFloat32Array = record.distances
	var next_index := int(record.lod_index)
	var hysteresis := float(_limits.hlod_hysteresis_m)
	while next_index < distances.size() - 1 \
	and distance > float(distances[next_index]) + hysteresis:
		next_index += 1
	while next_index > 0 \
	and distance <= float(distances[next_index - 1]) - hysteresis:
		next_index -= 1
	return next_index


func _validate_mesh(mesh: Mesh) -> Dictionary:
	if mesh == null or mesh.get_surface_count() < 1 or mesh.get_surface_count() > 16:
		return _error("invalid_mesh", "Mesh must contain between 1 and 16 surfaces.")
	var vertices := 0
	var indices := 0
	for surface in mesh.get_surface_count():
		vertices += mesh.surface_get_array_len(surface)
		indices += mesh.surface_get_array_index_len(surface)
	if vertices < 3 or vertices > int(_limits.max_mesh_vertices):
		return _error("mesh_vertex_limit", "Mesh vertex count exceeds configured bounds.")
	if indices > int(_limits.max_mesh_indices):
		return _error("mesh_index_limit", "Mesh index count exceeds configured bounds.")
	return {
		"ok": true,
		"code": "ok",
		"vertex_count": vertices,
		"index_count": indices,
	}


func _validate_navigation_mesh(navigation_mesh: NavigationMesh) -> Dictionary:
	var vertices := navigation_mesh.get_vertices()
	var polygon_count := navigation_mesh.get_polygon_count()
	if vertices.size() < 3 \
	or vertices.size() > int(_limits.max_navigation_vertices) \
	or polygon_count < 1 \
	or polygon_count > int(_limits.max_navigation_polygons):
		return _error("navigation_data_limit", "Precomputed navigation data exceeds configured bounds.")
	for vertex in vertices:
		if not _finite_vector3(vertex):
			return _error("invalid_navigation_vertex", "Navigation vertices must be finite.")
	var index_count := 0
	for polygon_index in polygon_count:
		var polygon := navigation_mesh.get_polygon(polygon_index)
		if polygon.size() < 3:
			return _error("invalid_navigation_polygon", "Navigation polygons require at least three indices.")
		index_count += polygon.size()
		if index_count > int(_limits.max_navigation_indices):
			return _error("navigation_index_limit", "Navigation polygon indices exceed configured bounds.")
		for vertex_index in polygon:
			if vertex_index < 0 or vertex_index >= vertices.size():
				return _error("navigation_index_out_of_bounds", "Navigation polygon index is out of bounds.")
	var agent_radius_m := float(navigation_mesh.agent_radius)
	var agent_height_m := float(navigation_mesh.agent_height)
	var agent_max_slope_degrees := float(navigation_mesh.agent_max_slope)
	if not is_finite(agent_radius_m) \
	or agent_radius_m < 0.0 \
	or agent_radius_m > MAX_NAVIGATION_AGENT_RADIUS_M:
		return _error(
			"invalid_navigation_agent_radius",
			"Navigation agent radius must be finite and between 0 and 1000 metres.",
		)
	if not is_finite(agent_height_m) \
	or agent_height_m <= 0.0 \
	or agent_height_m > MAX_NAVIGATION_AGENT_HEIGHT_M:
		return _error(
			"invalid_navigation_agent_height",
			"Navigation agent height must be finite and between 0 and 1000 metres.",
		)
	if not is_finite(agent_max_slope_degrees) \
	or agent_max_slope_degrees < 0.0 \
	or agent_max_slope_degrees > MAX_NAVIGATION_AGENT_SLOPE_DEGREES:
		return _error(
			"invalid_navigation_agent_slope",
			"Navigation agent maximum slope must be finite and between 0 and 90 degrees.",
		)
	return {
		"ok": true,
		"code": "ok",
		"vertex_count": vertices.size(),
		"polygon_count": polygon_count,
		"index_count": index_count,
		"agent_radius_m": agent_radius_m,
		"agent_height_m": agent_height_m,
		"agent_max_slope_degrees": agent_max_slope_degrees,
	}


func _validate_foliage_quality(
	quality_tier: StringName,
	projection_area_m2: float,
	instance_count: int
) -> Dictionary:
	if quality_tier == &"custom":
		if projection_area_m2 != 0.0 \
		and (not is_finite(projection_area_m2) \
			or projection_area_m2 <= 0.0 \
			or projection_area_m2 > MAX_FOLIAGE_PROJECTION_AREA_M2):
			return _error(
				"invalid_foliage_projection_area",
				"Custom foliage projection area must be zero or a finite positive bounded value.",
			)
		return {"ok": true, "code": "ok"}
	if not FOLIAGE_QUALITY_TIERS.has(quality_tier):
		return _error(
			"invalid_foliage_quality_tier",
			"Foliage quality tier must be low, medium, high, or custom.",
		)
	if not is_finite(projection_area_m2) \
	or projection_area_m2 <= 0.0 \
	or projection_area_m2 > MAX_FOLIAGE_PROJECTION_AREA_M2:
		return _error(
			"invalid_foliage_projection_area",
			"Named foliage quality tiers require a finite positive bounded projection area.",
		)
	var tier: Dictionary = FOLIAGE_QUALITY_TIERS[quality_tier]
	var density_limit := floori(
		projection_area_m2 * float(tier.maximum_density_per_square_m)
	)
	var effective_limit: int = min(int(tier.maximum_instances), density_limit)
	if instance_count > effective_limit:
		return _error(
			"foliage_quality_limit",
			"Foliage transforms exceed the selected quality tier's instance or density ceiling.",
		)
	return {"ok": true, "code": "ok", "effective_instance_limit": effective_limit}


func _validate_path_collision_shape(shape: Shape3D) -> Dictionary:
	var vertex_count := 0
	var extent_m := 0.0
	if shape is BoxShape3D:
		var size := (shape as BoxShape3D).size
		if not _finite_vector3(size) or size.x <= 0.0 or size.y <= 0.0 or size.z <= 0.0:
			return _error("invalid_path_collision_shape", "Box collision size must be finite and positive.")
		vertex_count = 8
		extent_m = max(size.x, max(size.y, size.z))
	elif shape is CapsuleShape3D:
		var capsule := shape as CapsuleShape3D
		if not is_finite(capsule.radius) or not is_finite(capsule.height) \
		or capsule.radius <= 0.0 or capsule.height <= 0.0:
			return _error("invalid_path_collision_shape", "Capsule collision dimensions must be finite and positive.")
		vertex_count = 16
		extent_m = max(capsule.radius * 2.0, capsule.height)
	elif shape is CylinderShape3D:
		var cylinder := shape as CylinderShape3D
		if not is_finite(cylinder.radius) or not is_finite(cylinder.height) \
		or cylinder.radius <= 0.0 or cylinder.height <= 0.0:
			return _error("invalid_path_collision_shape", "Cylinder collision dimensions must be finite and positive.")
		vertex_count = 16
		extent_m = max(cylinder.radius * 2.0, cylinder.height)
	elif shape is ConvexPolygonShape3D:
		var points := (shape as ConvexPolygonShape3D).points
		var point_check := _validate_collision_points(points, 4)
		if not point_check.ok:
			return point_check
		vertex_count = points.size()
		extent_m = float(point_check.extent_m)
	elif shape is ConcavePolygonShape3D:
		var faces := (shape as ConcavePolygonShape3D).get_faces()
		if faces.size() % 3 != 0:
			return _error(
				"invalid_path_collision_shape",
				"Concave collision faces must contain complete triangles.",
			)
		var face_check := _validate_collision_points(faces, 3)
		if not face_check.ok:
			return face_check
		vertex_count = faces.size()
		extent_m = float(face_check.extent_m)
	else:
		return _error(
			"unsupported_path_collision_shape",
			"Pre-baked path collision supports box, capsule, cylinder, convex, or concave shapes.",
		)
	if vertex_count > int(_limits.max_path_collision_vertices):
		return _error(
			"path_collision_vertex_limit",
			"Pre-baked path collision exceeds max_path_collision_vertices.",
		)
	if extent_m > float(_limits.max_path_collision_extent_m):
		return _error(
			"path_collision_extent_limit",
			"Pre-baked path collision exceeds max_path_collision_extent_m.",
		)
	return {
		"ok": true,
		"code": "ok",
		"vertex_count": vertex_count,
		"extent_m": extent_m,
	}


func _validate_collision_points(points: PackedVector3Array, minimum: int) -> Dictionary:
	if points.size() < minimum or points.size() > int(_limits.max_path_collision_vertices):
		return _error(
			"path_collision_vertex_limit",
			"Pre-baked path collision point count exceeds configured bounds.",
		)
	var extent_m := 0.0
	for point in points:
		if not _finite_vector3(point):
			return _error("invalid_path_collision_shape", "Path collision points must be finite.")
		extent_m = max(
			extent_m,
			max(abs(point.x) * 2.0, max(abs(point.y) * 2.0, abs(point.z) * 2.0)),
		)
	return {"ok": true, "code": "ok", "extent_m": extent_m}


func _validate_resource(resource: Resource, label: String) -> Dictionary:
	if resource == null:
		return _error("resource_missing", "%s is required." % label)
	var path := resource.resource_path
	if path.is_empty():
		return {"ok": true, "code": "ok"} if bool(_limits.allow_in_memory_resources) \
		else _error("in_memory_resource_rejected", "%s must be an exported allowlisted resource." % label)
	var relative := path.trim_prefix("res://")
	if not path.begins_with("res://") \
	or relative.is_empty() \
	or relative.contains("\\") \
	or relative.contains("//") \
	or "/../" in ("/" + relative + "/") \
	or "/./" in ("/" + relative + "/"):
		return _error("external_resource_rejected", "%s must use a res:// resource." % label)
	var allowlist: PackedStringArray = _limits.allowed_resource_paths
	if allowlist.is_empty() or path not in allowlist:
		return _error("resource_not_allowlisted", "%s is not in allowed_resource_paths." % label)
	return {"ok": true, "code": "ok"}


func _has_installed_projections() -> bool:
	for capability in CAPABILITIES:
		if not (_installed[capability] as Dictionary).is_empty():
			return true
	return false


func _validate_installed_limits(candidate: Dictionary) -> Dictionary:
	var installed_path_collision := 0
	for capability in CAPABILITIES:
		var records: Dictionary = _installed[capability]
		if records.size() > int(candidate.max_installed_per_capability):
			return _error(
				"installed_projection_limit_in_use",
				"max_installed_per_capability is below current ownership.",
			)
		for record in records.values():
			if capability == &"mesh_hlod" \
			and int(candidate.hlod_cross_fade_steps) \
			!= int(_limits.hlod_cross_fade_steps):
				return _error(
					"hlod_transition_policy_in_use",
					"Release installed HLOD projections before changing fade steps.",
				)
			if capability == &"foliage" \
			and (record.transforms as Array).size() > int(candidate.max_foliage_instances):
				return _error("foliage_limit_in_use", "Foliage limit is below an installed projection.")
			if capability == &"navigation":
				if int(record.vertex_count) > int(candidate.max_navigation_vertices) \
				or int(record.polygon_count) > int(candidate.max_navigation_polygons) \
				or int(record.index_count) > int(candidate.max_navigation_indices):
					return _error("navigation_limit_in_use", "Navigation limits are below installed data.")
			elif int(record.vertex_count) > int(candidate.max_mesh_vertices) \
			or int(record.index_count) > int(candidate.max_mesh_indices):
				return _error("mesh_limit_in_use", "Mesh limits are below an installed projection.")
			if capability == &"paths" and int(record.get("collision_shape_count", 0)) > 0:
				installed_path_collision += 1
				if not bool(candidate.allow_path_collision):
					return _error(
						"path_collision_policy_in_use",
						"Release pre-baked path collision before disabling it.",
					)
				if int(record.get("collision_vertex_count", 0)) \
				> int(candidate.max_path_collision_vertices) \
				or float(record.get("collision_extent_m", 0.0)) \
				> float(candidate.max_path_collision_extent_m):
					return _error(
						"path_collision_limit_in_use",
						"Path collision limits are below installed data.",
					)
				if int(candidate.path_collision_layer) != int(_limits.path_collision_layer) \
				or int(candidate.path_collision_mask) != int(_limits.path_collision_mask):
					return _error(
						"path_collision_policy_in_use",
						"Release pre-baked path collision before changing layers or masks.",
					)
	if installed_path_collision > int(candidate.max_path_collision_projections):
		return _error(
			"path_collision_projection_limit_in_use",
			"Path collision projection limit is below current ownership.",
		)
	return {"ok": true, "code": "ok"}


func _capability_owns_key(capability: StringName, work_key: String) -> bool:
	if (_installed[capability] as Dictionary).has(work_key):
		return true
	return _find_pending(work_key, capability) >= 0


func _capability_owned_key_count(capability: StringName) -> int:
	var keys := {}
	for key in (_installed[capability] as Dictionary).keys():
		keys[str(key)] = true
	for work in _pending:
		if work.capability == capability:
			keys[str(work.work_key)] = true
	return keys.size()


func _owned_path_collision_count(excluding_work_key := "") -> int:
	var count := 0
	for key in (_installed[&"paths"] as Dictionary):
		if str(key) != excluding_work_key \
		and int(_installed[&"paths"][key].get("collision_shape_count", 0)) > 0:
			count += 1
	for work in _pending:
		if work.capability == &"paths" \
		and str(work.work_key) != excluding_work_key \
		and int(work.get("collision_shape_count", 0)) > 0:
			count += 1
	return count


func _find_pending(work_key: String, capability: StringName = &"") -> int:
	for index in _pending.size():
		if str(_pending[index].work_key) == work_key \
		and (capability.is_empty() or _pending[index].capability == capability):
			return index
	return -1


func _choose_pending() -> int:
	for index in _pending.size():
		if bool(_pending[index].get("cancelled", false)):
			return index
	var best := 0
	for index in range(1, _pending.size()):
		if int(_pending[index].priority) > int(_pending[best].priority) \
		or (int(_pending[index].priority) == int(_pending[best].priority) \
		and int(_pending[index].sequence) < int(_pending[best].sequence)):
			best = index
	return best


func _work_size(work: Dictionary) -> int:
	return work.transforms.size() if work.capability == &"foliage" else 1


func _finite_transform(transform: Transform3D) -> bool:
	for value in [
		transform.basis.x.x, transform.basis.x.y, transform.basis.x.z,
		transform.basis.y.x, transform.basis.y.y, transform.basis.y.z,
		transform.basis.z.x, transform.basis.z.y, transform.basis.z.z,
		transform.origin.x, transform.origin.y, transform.origin.z,
	]:
		if not is_finite(float(value)):
			return false
	return true


func _finite_vector3(value: Vector3) -> bool:
	return is_finite(value.x) and is_finite(value.y) and is_finite(value.z)


func _projection_name(capability: StringName, work_key: String) -> String:
	return "MTerrainRuntime_%s_%d" % [capability, work_key.hash()]


func _next_sequence() -> int:
	_sequence += 1
	return _sequence


func _push_result(result: Dictionary) -> void:
	_results.append(result.duplicate(true))
	while _results.size() > MAX_RESULT_RECEIPTS:
		_results.pop_front()


func _dispose_projection(projection: Node) -> void:
	if projection == null or not is_instance_valid(projection):
		return
	if projection.is_inside_tree():
		var parent := projection.get_parent()
		if parent != null:
			parent.remove_child(projection)
		projection.queue_free()
	else:
		projection.free()


func _notification(what: int) -> void:
	if what != NOTIFICATION_PREDELETE:
		return
	for work in _pending:
		_dispose_projection(work.projection)
	_pending.clear()


func _public_limits() -> Dictionary:
	return _limits.duplicate(true)


func _public_foliage_quality_tiers() -> Dictionary:
	var result := {}
	for key in FOLIAGE_QUALITY_TIERS:
		result[str(key)] = (FOLIAGE_QUALITY_TIERS[key] as Dictionary).duplicate(true)
	return result


func _error(code: String, message: String) -> Dictionary:
	return {"ok": false, "code": code, "message": message, "api_version": API_VERSION}
