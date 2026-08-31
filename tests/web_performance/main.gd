extends Node3D


@onready var status: Label = $Overlay/Panel/Status
@onready var camera: Camera3D = $Camera3D

const ROUTE_REPETITIONS := 4
const ROUTE_REGION_SIDE := 8
const TILE_SIDE := 17
const SAMPLE_BUDGET := 512
const REGION_BUDGET := 1
const EXTENDED_INSTANCE_BUDGET := 64
const EXTENDED_APPLY_BUDGET := 4
const EXTENDED_HLOD_FADE_STEPS := 4
const EXTENDED_QUERY_INTERVAL := ROUTE_REGION_SIDE * ROUTE_REGION_SIDE

var _terrain: Node3D
var _route: Array[Vector2i] = []
var _route_index := -1
var _current_key := ""
var _current_revision := 0
var _collision_revision := 0
var _started_usec := 0
var _first_tile_usec := -1
var _first_collision_usec := -1
var _release_started_usec := -1
var _stage := "traverse"
var _max_resident_tiles := 0
var _max_loaded_regions := 0
var _max_collision_regions := 0
var _max_estimated_region_bytes := 0
var _max_lod_neighbor_delta := 0
var _max_visible_lod_points := 0
var _runtime_profile := ""
var _awaiting_collision := false
var _extended_runtime: Node3D
var _extended_resources := {}
var _extended_revision := 0
var _extended_ground_y := 0.0
var _extended_quality_tier := &"low"
var _awaiting_extended_query := false
var _extended_query_attempts := 0
var _extended_navigation_queries := 0
var _extended_path_collision_queries := 0
var _max_extended_pending_work := 0
var _max_extended_instance_ops := 0
var _max_extended_apply_ops := 0
var _max_extended_foliage_instances := 0
var _max_extended_path_collision_shapes := 0
var _max_extended_installed_counts := {
	&"foliage": 0,
	&"navigation": 0,
	&"paths": 0,
	&"mesh_hlod": 0,
}
var _max_extended_quality_tier_instances := {
	&"low": 0,
	&"medium": 0,
	&"high": 0,
}


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.025, 0.045, 0.075))
	if not ClassDB.class_exists(&"MTerrain"):
		_fail("MTerrain did not register")
		return
	_terrain = ClassDB.instantiate(&"MTerrain") as Node3D
	if _terrain == null:
		_fail("MTerrain could not be instantiated")
		return
	add_child(_terrain)
	var capabilities: Dictionary = _terrain.call(&"get_runtime_capabilities")
	_runtime_profile = str(capabilities.get(&"build_profile", ""))
	if capabilities.get(&"api_version") != 2 \
	or _runtime_profile not in ["web_core", "web_extended"] \
	or capabilities.get(&"single_threaded") != true:
		_fail("performance runtime capability tuple did not match")
		return
	if _runtime_profile == "web_extended":
		var extended_error := _configure_extended_runtime()
		if not extended_error.is_empty():
			_fail(extended_error)
			return
	_terrain.call(&"set_custom_camera", camera)
	_terrain.call(&"set_terrain_size", Vector2i(32, 32))
	_terrain.call(&"set_region_size", 4)
	_terrain.call(&"set_lod_distance", PackedInt32Array([2, 4, 8, 12, 18]))
	_terrain.call(&"set_grid_create", true)
	if not bool(_terrain.call(&"is_grid_created")):
		_fail("performance terrain grid was not created")
		return
	var configured: Dictionary = _terrain.call(&"configure_runtime_limits", {
		"max_pending_work": 4,
		"max_resident_tiles": 8,
		"max_resident_regions": 8,
		"max_collision_regions": 2,
		"max_estimated_region_bytes": 32 * 1024 * 1024,
	})
	if not bool(configured.get("ok", false)):
		_fail("performance limits failed: %s" % JSON.stringify(configured))
		return
	var initial_state: Dictionary = _terrain.call(&"get_runtime_state")
	if int(initial_state.loaded_region_count) != 0 \
	or int(initial_state.resident_tile_count) != 0 \
	or int(initial_state.visual_lod.visible_points) != 0:
		_fail("performance grid bypassed scheduler-owned residency")
		return
	for repetition in ROUTE_REPETITIONS:
		for region_y in ROUTE_REGION_SIDE:
			if region_y % 2 == 0:
				for region_x in ROUTE_REGION_SIDE:
					_route.append(Vector2i(region_x, region_y))
			else:
				for region_x in range(ROUTE_REGION_SIDE - 1, -1, -1):
					_route.append(Vector2i(region_x, region_y))
	_started_usec = Time.get_ticks_usec()
	if OS.has_feature("web"):
		JavaScriptBridge.eval(
			"globalThis.__mterrainTraversalStart = performance.now();",
			true,
		)
	status.text = "MTerrain representative traversal\nPreparing %d stops" % _route.size()
	print("MTERRAIN_WEB_PERFORMANCE_STARTED route_stops=%d" % _route.size())
	_queue_next_stop()


func _process(_delta: float) -> void:
	if _stage == "done" or _stage == "failed":
		return
	var stepped: Dictionary = _terrain.call(
		&"step_runtime_work",
		SAMPLE_BUDGET,
		REGION_BUDGET,
	)
	if not bool(stepped.get("ok", false)) \
	or int(stepped.get("sample_ops", 0)) > SAMPLE_BUDGET \
	or int(stepped.get("region_ops", 0)) > REGION_BUDGET:
		_fail("runtime step exceeded its operation contract")
		return
	var extended_idle := true
	if _extended_runtime != null:
		var extended_step: Dictionary = _extended_runtime.call(
			&"step_runtime_work",
			EXTENDED_INSTANCE_BUDGET,
			EXTENDED_APPLY_BUDGET,
			camera.global_position,
		)
		if not bool(extended_step.get("ok", false)) \
		or int(extended_step.get("instance_ops", 0)) > EXTENDED_INSTANCE_BUDGET \
		or int(extended_step.get("apply_ops", 0)) > EXTENDED_APPLY_BUDGET:
			_fail("extended runtime step exceeded its operation contract")
			return
		_max_extended_instance_ops = max(
			_max_extended_instance_ops,
			int(extended_step.get("instance_ops", 0)),
		)
		_max_extended_apply_ops = max(
			_max_extended_apply_ops,
			int(extended_step.get("apply_ops", 0)),
		)
		extended_idle = extended_step.get("status") == "idle"
		_capture_extended_maxima(_extended_runtime.call(&"get_runtime_state"))
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	_capture_maxima(state)
	if _first_collision_usec < 0 \
	and bool(state.collision.ready) \
	and not state.collision.active_regions.is_empty():
		_first_collision_usec = Time.get_ticks_usec() - _started_usec
	if stepped.get("status") != "idle" or not extended_idle:
		return
	if _stage == "traverse":
		if _awaiting_extended_query:
			_advance_extended_query()
			return
		if _awaiting_collision:
			if not bool(state.collision.ready):
				_fail("route collision focus did not become ready")
				return
			_awaiting_collision = false
			if _extended_runtime != null:
				var extended_error := _validate_extended_stop()
				if not extended_error.is_empty():
					_fail(extended_error)
					return
				if (_route_index + 1) % EXTENDED_QUERY_INTERVAL == 0:
					_awaiting_extended_query = true
					_extended_query_attempts = 0
					_advance_extended_query()
					return
			_queue_next_stop()
			return
		var completed: Dictionary = _terrain.call(
			&"take_runtime_work_result",
			_current_key,
			_current_revision,
		)
		if not bool(completed.get("ok", false)):
			_fail("route tile did not complete: %s" % JSON.stringify(completed))
			return
		if _first_tile_usec < 0:
			_first_tile_usec = Time.get_ticks_usec() - _started_usec
		_terrain.call(&"update")
		_request_current_collision()
	elif _stage == "release":
		if int(state.loaded_region_count) != 0 \
		or int(state.resident_tile_count) != 0 \
		or not state.collision.active_regions.is_empty():
			_fail("traversal did not recover to zero residency")
			return
		_terrain.call(&"update")
		state = _terrain.call(&"get_runtime_state")
		if int(state.visual_lod.visible_points) != 0:
			_fail("traversal retained visible terrain after eviction")
			return
		_finish(state)


func _queue_next_stop() -> void:
	_route_index += 1
	if _route_index >= _route.size():
		_begin_release()
		return
	var region := _route[_route_index]
	var repetition := floori(
		float(_route_index) / float(ROUTE_REGION_SIDE * ROUTE_REGION_SIDE)
	)
	_current_key = "route-%d-%d" % [region.x, region.y]
	_current_revision = repetition + 1
	var centre := Vector3(
		float(region.x * 128 + 64),
		96.0,
		float(region.y * 128 + 64),
	)
	camera.position = centre + Vector3(0.0, 0.0, 96.0)
	camera.look_at(Vector3(centre.x, 0.0, centre.z))
	_terrain.call(&"update")
	var start_x := region.x * 128 + 56
	var start_y := region.y * 128 + 56
	var queued: Dictionary = _terrain.call(
		&"queue_height_tile",
		_current_key,
		_current_revision,
		0,
		start_x,
		start_y,
		TILE_SIDE,
		TILE_SIDE,
		_make_route_tile(start_x, start_y, _current_revision),
		false,
	)
	if not bool(queued.get("ok", false)):
		_fail("route tile failed to queue: %s" % JSON.stringify(queued))
		return
	if _extended_runtime != null:
		var extended_error := _queue_extended_stop(centre, repetition)
		if not extended_error.is_empty():
			_fail(extended_error)
			return
	status.text = "MTerrain representative traversal\nStop %d / %d" % [
		_route_index + 1,
		_route.size(),
	]
	if (_route_index + 1) % EXTENDED_QUERY_INTERVAL == 0:
		print("MTERRAIN_WEB_PERFORMANCE_PROGRESS stops=%d" % (_route_index + 1))


func _request_current_collision() -> void:
	var region := _route[_route_index]
	_collision_revision += 1
	var collision: Dictionary = _terrain.call(
		&"request_runtime_collision_focus",
		region.x * 128 + 64,
		region.y * 128 + 64,
		0,
		1,
		_collision_revision,
	)
	if not bool(collision.get("ok", false)):
		_fail("route collision focus failed: %s" % JSON.stringify(collision))
		return
	_awaiting_collision = true


func _begin_release() -> void:
	_stage = "release"
	_release_started_usec = Time.get_ticks_usec()
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	for record in state.resident:
		var released: Dictionary = _terrain.call(
			&"release_runtime_tile",
			record.work_key,
			record.revision,
		)
		if not bool(released.get("ok", false)):
			_fail("route tile release failed: %s" % JSON.stringify(released))
			return
	_collision_revision += 1
	var collision_release: Dictionary = _terrain.call(
		&"request_runtime_collision_focus",
		0,
		0,
		0,
		0,
		_collision_revision,
	)
	if not bool(collision_release.get("ok", false)):
		_fail("route collision release failed: %s" % JSON.stringify(collision_release))
		return
	if _extended_runtime != null:
		for projection in [
			[&"foliage", "performance-foliage"],
			[&"navigation", "performance-navigation-left"],
			[&"navigation", "performance-navigation-right"],
			[&"paths", "performance-path"],
			[&"mesh_hlod", "performance-hlod"],
		]:
			var released: Dictionary = _extended_runtime.call(
				&"release_projection",
				projection[0],
				projection[1],
				_extended_revision,
			)
			if not bool(released.get("ok", false)):
				_fail("extended projection release failed: %s" % JSON.stringify(released))
				return
	status.text = "MTerrain representative traversal\nRecovering residency"


func _capture_maxima(state: Dictionary) -> void:
	_max_resident_tiles = max(_max_resident_tiles, int(state.resident_tile_count))
	_max_loaded_regions = max(_max_loaded_regions, int(state.loaded_region_count))
	_max_collision_regions = max(
		_max_collision_regions,
		state.collision.active_regions.size(),
	)
	_max_estimated_region_bytes = max(
		_max_estimated_region_bytes,
		int(state.estimated_loaded_region_bytes),
	)
	_max_lod_neighbor_delta = max(
		_max_lod_neighbor_delta,
		int(state.visual_lod.maximum_neighbor_delta),
	)
	_max_visible_lod_points = max(
		_max_visible_lod_points,
		int(state.visual_lod.visible_points),
	)


func _capture_extended_maxima(state: Dictionary) -> void:
	_max_extended_pending_work = max(
		_max_extended_pending_work,
		(state.pending as Array).size(),
	)
	for capability in _max_extended_installed_counts:
		_max_extended_installed_counts[capability] = max(
			int(_max_extended_installed_counts[capability]),
			int(state.installed_counts.get(capability, 0)),
		)
	_max_extended_foliage_instances = max(
		_max_extended_foliage_instances,
		int(state.installed_instances.get(&"foliage", 0)),
	)
	_max_extended_path_collision_shapes = max(
		_max_extended_path_collision_shapes,
		int(state.installed_collision_shapes.get(&"paths", 0)),
	)
	for quality_tier in _max_extended_quality_tier_instances:
		_max_extended_quality_tier_instances[quality_tier] = max(
			int(_max_extended_quality_tier_instances[quality_tier]),
			int(state.installed_foliage_quality_tiers.get(quality_tier, 0)),
		)


func _make_route_tile(
	start_x: int,
	start_y: int,
	revision: int
) -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(TILE_SIDE * TILE_SIDE)
	for local_y in TILE_SIDE:
		for local_x in TILE_SIDE:
			var global_x := start_x + local_x
			var global_y := start_y + local_y
			heights[local_y * TILE_SIDE + local_x] = (
				float(global_x) * 0.00390625
				+ float(global_y) * 0.001953125
				+ float(revision) * 0.125
			)
	return heights


func _finish(state: Dictionary) -> void:
	_stage = "done"
	set_process(false)
	if OS.has_feature("web"):
		JavaScriptBridge.eval(
			"globalThis.__mterrainTraversalEnd = performance.now();",
			true,
		)
	var extended_payload := {"enabled": false}
	if _extended_runtime != null:
		var extended_state: Dictionary = _extended_runtime.call(&"get_runtime_state")
		for capability in _max_extended_installed_counts:
			if int(extended_state.installed_counts.get(capability, -1)) != 0:
				_fail("extended traversal retained %s residency" % capability)
				return
		if not (extended_state.pending as Array).is_empty():
			_fail("extended traversal retained pending work")
			return
		extended_payload = {
			"enabled": true,
			"schema": "mterrain-web-extended-performance/v1",
			"api_version": 1,
			"instance_ops_per_step": EXTENDED_INSTANCE_BUDGET,
			"apply_ops_per_step": EXTENDED_APPLY_BUDGET,
			"hlod_cross_fade_steps": EXTENDED_HLOD_FADE_STEPS,
			"query_interval_stops": EXTENDED_QUERY_INTERVAL,
			"navigation_queries": _extended_navigation_queries,
			"path_collision_queries": _extended_path_collision_queries,
			"max_pending_work": _max_extended_pending_work,
			"max_instance_ops": _max_extended_instance_ops,
			"max_apply_ops": _max_extended_apply_ops,
			"max_installed_counts": _max_extended_installed_counts,
			"max_foliage_instances": _max_extended_foliage_instances,
			"max_quality_tier_instances": _max_extended_quality_tier_instances,
			"max_path_collision_shapes": _max_extended_path_collision_shapes,
			"final_pending_work": (extended_state.pending as Array).size(),
			"final_installed_counts": extended_state.installed_counts,
			"metrics": extended_state.metrics,
		}
	var payload := {
		"schema": "mterrain-web-performance-fixture/v1",
		"runtime_profile": _runtime_profile,
		"route_stops": _route.size(),
		"route_repetitions": ROUTE_REPETITIONS,
		"route_region_side": ROUTE_REGION_SIDE,
		"sample_ops_per_step": SAMPLE_BUDGET,
		"region_ops_per_step": REGION_BUDGET,
		"elapsed_usec": Time.get_ticks_usec() - _started_usec,
		"first_tile_usec": _first_tile_usec,
		"first_collision_usec": _first_collision_usec,
		"eviction_recovery_usec": Time.get_ticks_usec() - _release_started_usec,
		"max_resident_tiles": _max_resident_tiles,
		"max_loaded_regions": _max_loaded_regions,
		"max_collision_regions": _max_collision_regions,
		"max_estimated_region_bytes": _max_estimated_region_bytes,
		"max_lod_neighbor_delta": _max_lod_neighbor_delta,
		"max_visible_lod_points": _max_visible_lod_points,
		"final_loaded_regions": int(state.loaded_region_count),
		"final_resident_tiles": int(state.resident_tile_count),
		"final_visible_points": int(state.visual_lod.visible_points),
		"scheduler_metrics": state.metrics,
		"extended_runtime": extended_payload,
	}
	status.text = "MTerrain representative traversal\n%d stops complete" % _route.size()
	print("MTERRAIN_WEB_PERFORMANCE_OK ", JSON.stringify(payload))


func _fail(message: String) -> void:
	_stage = "failed"
	set_process(false)
	status.text = "MTerrain performance fixture failed\n" + message
	push_error("MTERRAIN_WEB_PERFORMANCE_FAILED " + message)


func _configure_extended_runtime() -> String:
	var runtime_script := load("res://runtime/web_extended_runtime.gd")
	if runtime_script == null:
		return "performance extended companion script did not load"
	_extended_runtime = runtime_script.new() as Node3D
	if _extended_runtime == null:
		return "performance extended companion could not be instantiated"
	add_child(_extended_runtime)
	var capabilities: Dictionary = _extended_runtime.call(&"get_runtime_capabilities")
	if capabilities.get("api_version") != 1 \
	or capabilities.get("prebaked_path_collision") != true \
	or capabilities.get("runtime_path_collision_generation") != false \
	or capabilities.get("hlod_cross_fade") != true:
		return "performance extended capability contract did not match"
	var allowed_paths := PackedStringArray([
		"res://fixtures/grass_cluster.obj",
		"res://fixtures/grass_material.tres",
		"res://fixtures/road_strip.obj",
		"res://fixtures/road_material.tres",
		"res://fixtures/road_collision.tres",
		"res://fixtures/rock_near.obj",
		"res://fixtures/rock_far.obj",
		"res://fixtures/walkable_nav.tres",
	])
	var configured: Dictionary = _extended_runtime.call(&"configure_limits", {
		"max_pending_work": 8,
		"max_foliage_instances": 256,
		"max_installed_per_capability": 4,
		"hlod_cross_fade_steps": EXTENDED_HLOD_FADE_STEPS,
		"allow_path_collision": true,
		"max_path_collision_projections": 1,
		"path_collision_layer": 2,
		"path_collision_mask": 2,
		"allowed_resource_paths": allowed_paths,
	})
	if not bool(configured.get("ok", false)):
		return "performance extended limits failed: %s" % JSON.stringify(configured)
	_extended_resources = {
		"foliage_mesh": load("res://fixtures/grass_cluster.obj") as Mesh,
		"foliage_material": load("res://fixtures/grass_material.tres") as Material,
		"path_mesh": load("res://fixtures/road_strip.obj") as Mesh,
		"path_material": load("res://fixtures/road_material.tres") as Material,
		"path_collision": load("res://fixtures/road_collision.tres") as Shape3D,
		"hlod_near": load("res://fixtures/rock_near.obj") as Mesh,
		"hlod_far": load("res://fixtures/rock_far.obj") as Mesh,
		"navigation": load("res://fixtures/walkable_nav.tres") as NavigationMesh,
	}
	for resource_name in _extended_resources:
		if _extended_resources[resource_name] == null:
			return "performance extended resource failed to load: %s" % resource_name
	return ""


func _queue_extended_stop(centre: Vector3, repetition: int) -> String:
	_extended_revision = _route_index + 1
	_extended_quality_tier = _quality_tier(repetition)
	var foliage_count := _quality_instance_count(_extended_quality_tier)
	_extended_ground_y = _route_height(centre.x, centre.z, _current_revision)
	var transforms := _make_foliage_transforms(centre, foliage_count)
	var navigation_mesh: NavigationMesh = _extended_resources.navigation
	var results := [
		_extended_runtime.call(
			&"queue_foliage",
			"performance-foliage",
			_extended_revision,
			4,
			_extended_resources.foliage_mesh,
			transforms,
			_extended_resources.foliage_material,
			_extended_quality_tier,
			1024.0,
		),
		_extended_runtime.call(
			&"queue_navigation",
			"performance-navigation-left",
			_extended_revision,
			3,
			navigation_mesh,
			Transform3D(
				Basis.IDENTITY,
				Vector3(centre.x - 8.0, _extended_ground_y, centre.z),
			),
		),
		_extended_runtime.call(
			&"queue_navigation",
			"performance-navigation-right",
			_extended_revision,
			3,
			navigation_mesh,
			Transform3D(
				Basis.IDENTITY,
				Vector3(centre.x + 8.0, _extended_ground_y, centre.z),
			),
		),
		_extended_runtime.call(
			&"queue_path",
			"performance-path",
			_extended_revision,
			2,
			_extended_resources.path_mesh,
			Transform3D(
				Basis.IDENTITY,
				Vector3(centre.x, _extended_ground_y + 0.25, centre.z),
			),
			_extended_resources.path_material,
			_extended_resources.path_collision,
		),
		_extended_runtime.call(
			&"queue_mesh_hlod",
			"performance-hlod",
			_extended_revision,
			1,
			[_extended_resources.hlod_near, _extended_resources.hlod_far],
			PackedFloat32Array([32.0, 96.0]),
			Transform3D(
				Basis.IDENTITY.scaled(Vector3(3.0, 3.0, 3.0)),
				Vector3(centre.x, _extended_ground_y + 0.5, centre.z),
			),
			_extended_resources.path_material,
		),
	]
	for result in results:
		if not bool(result.get("ok", false)):
			return "performance extended projection failed to queue: %s" % JSON.stringify(result)
	return ""


func _validate_extended_stop() -> String:
	var state: Dictionary = _extended_runtime.call(&"get_runtime_state")
	var expected_counts := {
		&"foliage": 1,
		&"navigation": 2,
		&"paths": 1,
		&"mesh_hlod": 1,
	}
	for capability in expected_counts:
		if int(state.installed_counts.get(capability, 0)) != int(expected_counts[capability]):
			return "performance extended residency count drifted for %s" % capability
		for record in state.installed[capability]:
			if int(record.revision) != _extended_revision:
				return "performance extended revision drifted for %s" % capability
	if str(state.installed.foliage[0].quality_tier) != str(_extended_quality_tier) \
	or int(state.installed_instances.foliage) != _quality_instance_count(_extended_quality_tier):
		return "performance foliage tier accounting drifted"
	if int(state.installed_collision_shapes.paths) != 1:
		return "performance pre-baked path collision ownership drifted"
	if int(state.installed.mesh_hlod[0].lod_index) != 1 \
	or bool(state.installed.mesh_hlod[0].hlod_transition_active):
		return "performance HLOD cross-fade did not settle"
	if not is_equal_approx(
		float(state.installed.navigation[0].navigation_agent_radius_m),
		0.4,
	) \
	or not is_equal_approx(
		float(state.installed.navigation[0].navigation_agent_max_slope_degrees),
		35.0,
	):
		return "performance navigation agent profile drifted"
	return ""


func _advance_extended_query() -> void:
	_extended_query_attempts += 1
	var region := _route[_route_index]
	var centre := Vector3(
		float(region.x * 128 + 64),
		_extended_ground_y,
		float(region.y * 128 + 64),
	)
	var navigation_map := _extended_runtime.get_world_3d().navigation_map
	NavigationServer3D.map_force_update(navigation_map)
	var navigation_path := NavigationServer3D.map_get_path(
		navigation_map,
		centre + Vector3(-12.0, 0.0, 0.0),
		centre + Vector3(12.0, 0.0, 0.0),
		true,
	)
	var query := PhysicsRayQueryParameters3D.create(
		centre + Vector3(0.0, 3.0, 0.0),
		centre + Vector3(0.0, -3.0, 0.0),
	)
	query.collision_mask = 2
	var collision_hit := _extended_runtime.get_world_3d().direct_space_state.intersect_ray(query)
	if navigation_path.size() < 2 or collision_hit.is_empty():
		if _extended_query_attempts >= 60:
			_fail("extended navigation join or path collision did not answer during traversal")
		return
	_extended_navigation_queries += 1
	_extended_path_collision_queries += 1
	_awaiting_extended_query = false
	_queue_next_stop()


func _quality_tier(repetition: int) -> StringName:
	match repetition % 3:
		0:
			return &"low"
		1:
			return &"medium"
		_:
			return &"high"


func _quality_instance_count(quality_tier: StringName) -> int:
	return {
		&"low": 64,
		&"medium": 128,
		&"high": 256,
	}[quality_tier]


func _make_foliage_transforms(centre: Vector3, count: int) -> Array:
	var transforms: Array = []
	var side := ceili(sqrt(float(count)))
	var spacing := 30.0 / float(max(1, side - 1))
	var basis := Basis.IDENTITY.scaled(Vector3(1.5, 2.0, 1.5))
	for index in count:
		var x := centre.x - 15.0 + float(index % side) * spacing
		var z := centre.z - 15.0 + float(index / side) * spacing
		transforms.append(Transform3D(
			basis,
			Vector3(x, _route_height(x, z, _current_revision) + 0.2, z),
		))
	return transforms


func _route_height(x: float, z: float, revision: int) -> float:
	return x * 0.00390625 + z * 0.001953125 + float(revision) * 0.125
