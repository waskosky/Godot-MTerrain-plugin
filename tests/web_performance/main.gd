extends Node3D


@onready var status: Label = $Overlay/Panel/Status
@onready var camera: Camera3D = $Camera3D

const ROUTE_REPETITIONS := 4
const ROUTE_REGION_SIDE := 8
const TILE_SIDE := 17
const SAMPLE_BUDGET := 512
const REGION_BUDGET := 1

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
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	_capture_maxima(state)
	if _first_collision_usec < 0 \
	and bool(state.collision.ready) \
	and not state.collision.active_regions.is_empty():
		_first_collision_usec = Time.get_ticks_usec() - _started_usec
	if stepped.get("status") != "idle":
		return
	if _stage == "traverse":
		if _awaiting_collision:
			if not bool(state.collision.ready):
				_fail("route collision focus did not become ready")
				return
			_awaiting_collision = false
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
	status.text = "MTerrain representative traversal\nStop %d / %d" % [
		_route_index + 1,
		_route.size(),
	]


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
	}
	status.text = "MTerrain representative traversal\n%d stops complete" % _route.size()
	print("MTERRAIN_WEB_PERFORMANCE_OK ", JSON.stringify(payload))


func _fail(message: String) -> void:
	_stage = "failed"
	set_process(false)
	status.text = "MTerrain performance fixture failed\n" + message
	push_error("MTERRAIN_WEB_PERFORMANCE_FAILED " + message)
