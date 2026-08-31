extends Node3D


@onready var status: Label = $Overlay/Panel/Status
@onready var camera: Camera3D = $Camera3D

var _terrain: Node3D
var _expected_profile := "web_core"


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.025, 0.045, 0.075))
	_expected_profile = (
		"web_extended" if OS.has_feature("mterrain_web_extended") else "web_core"
	)
	camera.look_at(Vector3(128.0, 0.0, 128.0))
	var failure := _initialize_and_apply()
	if failure.is_empty() and _expected_profile == "web_extended":
		failure = _verify_extended_companion()
	if failure.is_empty():
		failure = _verify_bounded_seam()
	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().physics_frame
	await get_tree().physics_frame
	if failure.is_empty():
		failure = _verify_collision()
	if failure.is_empty():
		failure = _verify_eviction_and_release()
	if failure.is_empty():
		status.text = "MTerrain whole-bundle rollback baseline\nGodot 4.7 · WebGL2 · no threads"
		print(
			"MTERRAIN_WEB_ROLLBACK_OK initialized_tile_samples=4489 ",
			"rejected_non_finite=1 bounded_scheduler=1 bounded_collision=1 ",
			"eviction_recovery=1 extended_companion=%d profile=%s"
			% [int(_expected_profile == "web_extended"), _expected_profile],
		)
	else:
		status.text = "MTerrain rollback baseline failed\n" + failure
		push_error("MTERRAIN_WEB_ROLLBACK_FAILED " + failure)


func _initialize_and_apply() -> String:
	if not ClassDB.class_exists(&"MTerrain"):
		return "MTerrain did not register"
	_terrain = ClassDB.instantiate(&"MTerrain") as Node3D
	if _terrain == null:
		return "MTerrain could not be instantiated"
	var capabilities: Dictionary = _terrain.call(&"get_runtime_capabilities")
	if capabilities.get(&"api_version") != 2 \
	or capabilities.get(&"build_profile") != _expected_profile \
	or capabilities.get(&"single_threaded") != true \
	or capabilities.get(&"runtime_memory_only") != true:
		return "runtime capability tuple did not match the rollback baseline"
	for capability in [
		&"heightfield_terrain",
		&"visual_lod",
		&"heightfield_collision",
		&"compatibility_materials",
		&"height_tile_apply",
		&"height_tile_release",
		&"bounded_update_scheduler",
		&"bounded_collision",
	]:
		if capabilities.get(capability) != true:
			return "runtime omitted baseline capability %s" % capability
	var before_grid: Dictionary = _terrain.call(
		&"apply_height_tile",
		0,
		0,
		1,
		1,
		PackedFloat32Array([0.0]),
		false,
	)
	if before_grid.get("code") != "grid_not_created":
		return "uninitialized apply did not fail closed"
	add_child(_terrain)
	_terrain.call(&"set_custom_camera", camera)
	_terrain.call(&"set_terrain_size", Vector2i(8, 8))
	_terrain.call(&"set_region_size", 4)
	_terrain.call(&"set_grid_create", true)
	if not bool(_terrain.call(&"is_grid_created")):
		return "memory-only terrain grid was not created"
	var heights := _make_hill_tile()
	var applied: Dictionary = _terrain.call(
		&"apply_height_tile",
		97,
		97,
		67,
		67,
		heights,
		false,
	)
	if not bool(applied.get("ok", false)) \
	or int(applied.get("written_samples", 0)) != 4489 \
	or applied.get("normal_size") != Vector2i(69, 69):
		return "baseline height tile did not install"
	var before_rejection := float(_terrain.call(&"get_height_by_pixel", 128, 128))
	var invalid := heights.duplicate()
	invalid[0] = NAN
	var rejected: Dictionary = _terrain.call(
		&"apply_height_tile",
		97,
		97,
		67,
		67,
		invalid,
		false,
	)
	if rejected.get("code") != "non_finite_height":
		return "non-finite height input did not fail closed"
	if not is_equal_approx(
		float(_terrain.call(&"get_height_by_pixel", 128, 128)),
		before_rejection,
	):
		return "rejected height input partially mutated terrain"
	return ""


func _verify_extended_companion() -> String:
	var runtime_script := load("res://runtime/web_extended_runtime.gd")
	if runtime_script == null:
		return "web_extended rollback companion script did not load"
	var runtime = runtime_script.new()
	if runtime == null:
		return "web_extended rollback companion could not be instantiated"
	var capabilities: Dictionary = runtime.get_runtime_capabilities()
	runtime.free()
	if capabilities.get("api_version") != 1:
		return "web_extended rollback companion API version did not match"
	for capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
		if capabilities.get(capability) != true:
			return "web_extended rollback companion omitted %s" % capability
	return ""


func _verify_bounded_seam() -> String:
	var configured: Dictionary = _terrain.call(&"configure_runtime_limits", {
		"max_pending_work": 8,
		"max_resident_tiles": 4,
		"max_resident_regions": 4,
		"max_collision_regions": 2,
		"max_estimated_region_bytes": 8 * 1024 * 1024,
	})
	if not bool(configured.get("ok", false)):
		return "bounded runtime limits were rejected"
	var material: Dictionary = _terrain.call(&"configure_runtime_material", {
		"low_color": Color(0.10, 0.25, 0.16),
		"high_color": Color(0.60, 0.48, 0.28),
		"steep_color": Color(0.30, 0.29, 0.27),
		"readable_emission": 0.42,
	})
	if not bool(material.get("ok", false)):
		return "Compatibility material configuration failed"
	var collision: Dictionary = _terrain.call(
		&"request_runtime_collision_focus",
		128,
		64,
		1,
		2,
		1,
	)
	if not bool(collision.get("ok", false)):
		return "bounded collision focus was rejected"
	for request in [
		["rollback-seam-left", 62],
		["rollback-seam-right", 128],
	]:
		var queued: Dictionary = _terrain.call(
			&"queue_height_tile",
			request[0],
			1,
			20,
			request[1],
			30,
			67,
			67,
			_make_plane_tile(request[1], 30, 67, 67),
			true,
		)
		if not bool(queued.get("ok", false)):
			return "adjacent rollback seam tile failed to queue"
		if _drain_runtime(128, 1) < 1:
			return "adjacent rollback seam tile exceeded its budget"
	var seam := float(_terrain.call(&"get_height_by_pixel", 128, 64))
	if not is_equal_approx(seam, 128.0 * 0.0625 + 64.0 * 0.03125):
		return "adjacent rollback tiles did not retain their shared border"
	var left_normal: Vector3 = _terrain.call(&"get_normal_by_pixel", 127, 64)
	var right_normal: Vector3 = _terrain.call(&"get_normal_by_pixel", 129, 64)
	if left_normal.distance_to(right_normal) > 0.015:
		return "rollback seam normals were discontinuous"
	return ""


func _verify_collision() -> String:
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready):
		return "rollback collision did not become ready"
	var space_state := _terrain.get_world_3d().direct_space_state
	for x in [127.25, 127.75, 128.25, 128.75]:
		var query := PhysicsRayQueryParameters3D.create(
			Vector3(x, 200.0, 64.0),
			Vector3(x, -200.0, 64.0),
		)
		var hit := space_state.intersect_ray(query)
		if hit.is_empty():
			return "rollback collision ray missed the shared seam"
		var expected := float(_terrain.call(&"get_height", Vector3(x, 0.0, 64.0)))
		if abs(float(hit.position.y) - expected) > 0.2:
			return "rollback visual and collision heightfields diverged"
	return ""


func _verify_eviction_and_release() -> String:
	for release in [
		_terrain.call(&"release_runtime_tile", "rollback-seam-left", 1),
		_terrain.call(&"release_runtime_tile", "rollback-seam-right", 1),
		_terrain.call(&"release_height_tile", 97, 97, 67, 67),
	]:
		if not bool(release.get("ok", false)):
			return "rollback baseline could not release an installed tile"
	var collision_release: Dictionary = _terrain.call(
		&"request_runtime_collision_focus",
		0,
		0,
		0,
		0,
		2,
	)
	if not bool(collision_release.get("ok", false)) or _drain_runtime(128, 1) < 1:
		return "rollback baseline could not release collision ownership"
	var limited: Dictionary = _terrain.call(&"configure_runtime_limits", {
		"max_resident_tiles": 2,
		"max_resident_regions": 2,
		"max_collision_regions": 0,
	})
	if not bool(limited.get("ok", false)):
		return "rollback eviction limits were rejected"
	for request in [
		["rollback-a", 20, 20, 1.0],
		["rollback-b", 148, 20, 2.0],
		["rollback-c", 148, 148, 3.0],
	]:
		var queued: Dictionary = _terrain.call(
			&"queue_height_tile",
			request[0],
			1,
			0,
			request[1],
			request[2],
			1,
			1,
			PackedFloat32Array([request[3]]),
			false,
		)
		if not bool(queued.get("ok", false)) or _drain_runtime(128, 1) < 1:
			return "rollback eviction fixture failed"
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	if int(state.resident_tile_count) != 2 \
	or int(state.loaded_region_count) > 2 \
	or int(state.metrics.evicted_tiles) < 1:
		return "rollback traversal did not enforce deterministic eviction"
	for record in state.resident:
		_terrain.call(&"release_runtime_tile", record.work_key, record.revision)
	if _drain_runtime(128, 1) < 1:
		return "rollback eviction fixture did not drain"
	state = _terrain.call(&"get_runtime_state")
	if int(state.resident_tile_count) != 0 or int(state.loaded_region_count) != 0:
		return "rollback fixture did not recover to zero residency"
	return ""


func _drain_runtime(sample_budget: int, region_budget: int) -> int:
	for step_index in 256:
		var stepped: Dictionary = _terrain.call(
			&"step_runtime_work",
			sample_budget,
			region_budget,
		)
		if not bool(stepped.get("ok", false)) \
		or int(stepped.get("sample_ops", 0)) > sample_budget \
		or int(stepped.get("region_ops", 0)) > region_budget:
			return -1
		if stepped.get("status") == "idle":
			return step_index + 1
	return 256


func _make_hill_tile() -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(67 * 67)
	for local_y in 67:
		for local_x in 67:
			var dx := float(local_x - 33)
			var dz := float(local_y - 33)
			heights[local_y * 67 + local_x] = 72.0 * exp(
				-(dx * dx + dz * dz) / 520.0
			)
	return heights


func _make_plane_tile(
	start_x: int,
	start_y: int,
	width: int,
	height: int
) -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(width * height)
	for local_y in height:
		for local_x in width:
			heights[local_y * width + local_x] = (
				float(start_x + local_x) * 0.0625
				+ float(start_y + local_y) * 0.03125
			)
	return heights
