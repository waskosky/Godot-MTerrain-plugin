extends Node3D


@onready var status: Label = $Overlay/Panel/Status
@onready var camera: Camera3D = $Camera3D

var _terrain: Node3D


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.025, 0.045, 0.075))
	camera.look_at(Vector3(128.0, 0.0, 128.0))
	var failures: Array[String] = []
	var extended := OS.has_feature("mterrain_web_extended")
	var expected_profile := "web_extended" if extended else "web_core"
	if not ClassDB.class_exists(&"MTerrain"):
		failures.append("MTerrain did not register")
	for excluded_class in [&"MGrass", &"MNavigationRegion3D", &"MPath", &"MHlod"]:
		if ClassDB.class_exists(excluded_class):
			failures.append("%s unexpectedly registered %s" % [expected_profile, excluded_class])

	var capabilities: Dictionary = {}
	_terrain = ClassDB.instantiate(&"MTerrain") as Node3D
	if _terrain == null:
		failures.append("MTerrain could not be instantiated")
	else:
		capabilities = _terrain.call(&"get_runtime_capabilities")
		if capabilities.get(&"api_version") != 2:
			failures.append("runtime API version is not 2")
		if capabilities.get(&"api_stability") != "experimental":
			failures.append("runtime API stability is not experimental")
		if capabilities.get(&"build_profile") != expected_profile:
			failures.append("build profile is not %s" % expected_profile)
		if capabilities.get(&"single_threaded") != true:
			failures.append("%s did not report single_threaded" % expected_profile)
		if capabilities.get(&"runtime_memory_only") != true:
			failures.append("%s did not default to runtime_memory_only" % expected_profile)
		for core_capability in [
			&"heightfield_terrain",
			&"visual_lod",
			&"heightfield_collision",
			&"compatibility_materials",
			&"height_tile_apply",
			&"height_tile_release",
				&"bounded_update_scheduler",
			&"bounded_collision",
			&"phase_timing_metrics",
			&"scheduler_owned_visual_residency",
		]:
			if capabilities.get(core_capability) != true:
				failures.append("%s omitted %s" % [expected_profile, core_capability])
		for extended_capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
			if capabilities.get(extended_capability) != extended:
				failures.append(
					"%s reported the wrong %s capability" \
					% [expected_profile, extended_capability]
				)
		if extended and capabilities.get(&"extended_runtime_api_version") != 1:
			failures.append("web_extended companion API version is not 1")
		var topology_limits: Dictionary = capabilities.get(&"topology_limits", {})
		if topology_limits.get(&"maximum_terrain_quads_per_axis") != 256 \
		or topology_limits.get(&"maximum_terrain_topology_points") != 65536 \
		or topology_limits.get(&"maximum_terrain_regions") != 1024 \
		or topology_limits.get(&"maximum_visual_range_quads") != 128:
			failures.append("bounded topology capability contract was inconsistent")
		for unsupported_capability in [
			&"foliage_collision",
			&"runtime_navigation_baking",
			&"runtime_curve_deformation",
			&"path_collision",
			&"runtime_mesh_generation",
		]:
			if capabilities.get(unsupported_capability) != false:
				failures.append("Web profile over-reported %s" % unsupported_capability)
		var rejected: Dictionary = _terrain.call(
			&"apply_height_tile",
			0,
			0,
			1,
			1,
			PackedFloat32Array([0.0]),
			false,
		)
		if rejected.get(&"code") != "grid_not_created":
			failures.append("uninitialized tile apply did not fail closed")

		add_child(_terrain)
		_terrain.call(&"set_custom_camera", camera)
		# Four 128-metre regions. The 97..163 tile crosses both shared
		# region borders at pixel 128 while remaining bounded to 67x67.
		_terrain.call(&"set_terrain_size", Vector2i(8, 8))
		_terrain.call(&"set_region_size", 4)
		_terrain.call(&"set_lod_distance", PackedInt32Array([1, 2, 3, 4, 5]))
		_terrain.call(&"set_grid_create", true)
		if not bool(_terrain.call(&"is_grid_created")):
			failures.append("memory-only terrain grid was not created")
		else:
			var initial_state: Dictionary = _terrain.call(&"get_runtime_state")
			if int(initial_state.get("loaded_region_count", -1)) != 0 \
			or int(initial_state.get("resident_tile_count", -1)) != 0 \
			or int(initial_state.visual_lod.get("visible_points", -1)) != 0:
				failures.append("grid creation bypassed scheduler-owned visual residency")
			var heights := _make_height_tile()
			var applied: Dictionary = _terrain.call(
				&"apply_height_tile",
				97,
				97,
				67,
				67,
				heights,
				false,
			)
			if not bool(applied.get(&"ok", false)):
				failures.append("resident height tile failed: %s" % JSON.stringify(applied))
			elif int(applied.get(&"written_samples", 0)) != 4489:
				failures.append("resident height tile reported the wrong sample count")
			elif applied.get(&"normal_size") != Vector2i(69, 69):
				failures.append("resident height tile reported the wrong normal halo")
			elif not is_equal_approx(
				float(_terrain.call(&"get_height_by_pixel", 128, 128)),
				heights[31 * 67 + 31],
			):
				failures.append("height tile did not survive the shared region border")
			var height_before_rejection := float(
				_terrain.call(&"get_height_by_pixel", 128, 128)
			)
			var invalid_heights := _make_height_tile()
			invalid_heights[0] = NAN
			var invalid: Dictionary = _terrain.call(
				&"apply_height_tile",
				97,
				97,
				67,
				67,
				invalid_heights,
				false,
			)
			if invalid.get(&"code") != "non_finite_height":
				failures.append("non-finite height tile did not fail closed")
			elif not is_equal_approx(
				float(_terrain.call(&"get_height_by_pixel", 128, 128)),
				height_before_rejection,
			):
				failures.append("rejected height tile partially mutated terrain")
			var scheduler_error := _verify_bounded_runtime()
			if not scheduler_error.is_empty():
				failures.append(scheduler_error)
			if extended:
				var extended_error: String = await _verify_extended_runtime()
				if not extended_error.is_empty():
					failures.append(extended_error)

	await get_tree().process_frame
	await get_tree().process_frame
	await get_tree().physics_frame
	await get_tree().physics_frame
	if failures.is_empty():
		var collision_error := _verify_collision_alignment()
		if not collision_error.is_empty():
			failures.append(collision_error)
	if failures.is_empty():
		var recovery_error := _verify_lod_and_recreate()
		if not recovery_error.is_empty():
			failures.append(recovery_error)
	if failures.is_empty():
		status.text = "MTerrain %s · bounded terrain and collision" % expected_profile
		if extended:
			status.text += "\nTiered grass · joined navigation · path collision · HLOD fade"
		status.text += "\nGodot 4.7 · WebGL2 · wasm32 · no threads"
		print(
			"MTERRAIN_WEB_SMOKE_OK initialized_tile_samples=4489 rejected_non_finite=1 ",
			"rejected_border=1 lod_transitions=1 recreate=1 phase_timings=1 ",
			"bounded_scheduler=1 bounded_collision=1 scheduler_visual=1 ",
			"extended=%d " % int(extended),
			JSON.stringify(capabilities),
		)
	else:
		status.text = "MTerrain Web smoke failed\n" + "\n".join(failures)
		push_error("MTERRAIN_WEB_SMOKE_FAILED " + JSON.stringify(failures))


func _make_height_tile() -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(67 * 67)
	for local_y in range(67):
		for local_x in range(67):
			var dx := float(local_x - 33)
			var dz := float(local_y - 33)
			var radial := exp(-(dx * dx + dz * dz) / 520.0)
			heights[local_y * 67 + local_x] = 72.0 * radial
	return heights


func _verify_bounded_runtime() -> String:
	var configured: Dictionary = _terrain.call(&"configure_runtime_limits", {
		"max_pending_work": 8,
		"max_resident_tiles": 4,
		"max_resident_regions": 4,
		"max_collision_regions": 2,
		"max_estimated_region_bytes": 8 * 1024 * 1024,
	})
	if not bool(configured.get("ok", false)):
		return "bounded Web limits failed: %s" % JSON.stringify(configured)
	var material: Dictionary = _terrain.call(&"configure_runtime_material", {
		"low_color": Color(0.10, 0.25, 0.16),
		"high_color": Color(0.60, 0.48, 0.28),
		"steep_color": Color(0.30, 0.29, 0.27),
		"readable_emission": 0.42,
	})
	if not bool(material.get("ok", false)):
		return "Compatibility material configuration failed: %s" % JSON.stringify(material)
	var low_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	low_image.fill(Color(0.10, 0.34, 0.15, 1.0))
	var high_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	high_image.fill(Color(0.58, 0.48, 0.25, 1.0))
	var surface_layers := Texture2DArray.new()
	var layer_images: Array[Image] = [low_image, high_image]
	if surface_layers.create_from_images(layer_images) != OK:
		return "Web texture-array fixture could not be created"
	var splat_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	splat_image.fill(Color(0.7, 0.3, 0.0, 0.0))
	var textured: Dictionary = _terrain.call(&"configure_runtime_material", {
		"surface_layer_count": 2,
		"surface_layers": surface_layers,
		"splatmap": ImageTexture.create_from_image(splat_image),
		"readable_emission": 0.25,
	})
	if not bool(textured.get("ok", false)):
		return "Web texture-array material failed: %s" % JSON.stringify(textured)
	var heights := PackedFloat32Array()
	heights.resize(17 * 17)
	for local_y in 17:
		for local_x in 17:
			heights[local_y * 17 + local_x] = 4.0 + float(local_x + local_y) * 0.25
	var queued: Dictionary = _terrain.call(
		&"queue_height_tile",
		"web-bounded-tile",
		1,
		20,
		20,
		20,
		17,
		17,
		heights,
		true,
	)
	if not bool(queued.get("ok", false)):
		return "bounded Web height work failed to queue: %s" % JSON.stringify(queued)
	var steps := _drain_runtime(128, 1)
	if steps < 5:
		return "bounded Web work did not span multiple budgeted steps"
	var state: Dictionary = _terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready) or int(state.collision.revision) < 0:
		return "update_collision did not establish Web collision residency"

	var collision: Dictionary = _terrain.call(
		&"request_runtime_collision_focus",
		128,
		64,
		1,
		2,
		1,
	)
	if not bool(collision.get("ok", false)):
		return "bounded Web collision failed to queue: %s" % JSON.stringify(collision)
	var seam_left := _make_global_plane_tile(62, 30, 67, 67)
	var seam_right := _make_global_plane_tile(128, 30, 67, 67)
	queued = _terrain.call(
		&"queue_height_tile",
		"web-seam-left",
		1,
		20,
		62,
		30,
		67,
		67,
		seam_left,
		true,
	)
	if not bool(queued.get("ok", false)):
		return "left Web seam tile failed to queue: %s" % JSON.stringify(queued)
	_drain_runtime(128, 1)
	var mismatch := seam_right.duplicate()
	for local_y in 67:
		mismatch[local_y * 67] += 1.0
	var seam_before_mismatch := float(_terrain.call(&"get_height_by_pixel", 128, 64))
	var rejected_mismatch: Dictionary = _terrain.call(
		&"queue_height_tile",
		"web-seam-right-mismatch",
		1,
		20,
		128,
		30,
		67,
		67,
		mismatch,
		true,
	)
	if rejected_mismatch.get("code") != "shared_sample_mismatch":
		return "mismatched Web shared border did not fail closed"
	if not is_equal_approx(
		float(_terrain.call(&"get_height_by_pixel", 128, 64)),
		seam_before_mismatch,
	):
		return "rejected Web shared border partially mutated terrain"
	queued = _terrain.call(
		&"queue_height_tile",
		"web-seam-right",
		1,
		20,
		128,
		30,
		67,
		67,
		seam_right,
		true,
	)
	if not bool(queued.get("ok", false)):
		return "matching right Web seam tile failed to queue: %s" % JSON.stringify(queued)
	_drain_runtime(128, 1)
	var seam_height := float(_terrain.call(&"get_height_by_pixel", 128, 64))
	if not is_equal_approx(seam_height, 128.0 * 0.0625 + 64.0 * 0.03125):
		return "Web adjacent tiles did not retain their exact shared border"
	var left_normal: Vector3 = _terrain.call(&"get_normal_by_pixel", 127, 64)
	var right_normal: Vector3 = _terrain.call(&"get_normal_by_pixel", 129, 64)
	if left_normal.distance_to(right_normal) > 0.015:
		return "Web adjacent tile normals were discontinuous"
	state = _terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready):
		return "bounded Web collision did not become ready"
	if int(state.metrics.texture_uploads) < 1 or int(state.metrics.collision_applies) < 1:
		return "bounded Web instrumentation was incomplete"
	if state.metrics.get("phase_timing_contract") != "mterrain-runtime-phase-timings/v1":
		return "bounded Web phase timing contract was missing"
	for phase in [
		"region_load",
		"preflight",
		"write_heights",
		"generate_normals",
		"texture_apply",
		"collision",
	]:
		if not state.metrics.phase_timings.has(phase) \
		or int(state.metrics.phase_timings[phase].invocations) < 1:
			return "bounded Web timing was not recorded for %s" % phase
	return ""


func _drain_runtime(sample_budget: int, region_budget: int) -> int:
	var expected_phase_keys := [
		"region_load",
		"preflight",
		"write_heights",
		"generate_normals",
		"texture_apply",
		"collision",
		"eviction",
		"rollback_heights",
		"rollback_normals",
		"rollback_apply",
	]
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
		if not stepped.has("phase_usec") \
		or stepped.phase_usec.size() != expected_phase_keys.size():
			return -1
		for phase in expected_phase_keys:
			if not stepped.phase_usec.has(phase) \
			or int(stepped.phase_usec[phase]) < 0:
				return -1
		if stepped.get("status") == "idle":
			return step_index + 1
	return 256


func _verify_collision_alignment() -> String:
	var space_state := _terrain.get_world_3d().direct_space_state
	for x in [127.25, 127.75, 128.25, 128.75]:
		var query := PhysicsRayQueryParameters3D.create(
			Vector3(x, 200.0, 64.0),
			Vector3(x, -200.0, 64.0),
		)
		var hit := space_state.intersect_ray(query)
		if hit.is_empty():
			return "Web collision ray missed the tile seam at x=%.2f" % x
		var expected := float(_terrain.call(&"get_height", Vector3(x, 0.0, 64.0)))
		if abs(float(hit.position.y) - expected) > 0.2:
			return "Web collision and visual heightfields diverged at x=%.2f" % x
	return ""


func _verify_lod_and_recreate() -> String:
	var expected_signatures: Array[PackedInt32Array] = []
	var previous_revision := int(_terrain.call(&"get_runtime_state").visual_lod.revision)
	for cycle in 2:
		for position_index in 2:
			camera.position = (
				Vector3(32.0, 80.0, 32.0)
				if position_index == 0
				else Vector3(224.0, 80.0, 224.0)
			)
			camera.look_at(Vector3(128.0, 0.0, 128.0))
			_terrain.call(&"update")
			var lod: Dictionary = _terrain.call(&"get_runtime_state").visual_lod
			if lod.get("kind") != "mterrain-runtime-visual-lod/v1":
				return "Web visual LOD state contract was missing"
			if int(lod.revision) <= previous_revision:
				return "Web visual LOD revision did not advance"
			previous_revision = int(lod.revision)
			if int(lod.visible_points) < 1 or int(lod.maximum_neighbor_delta) > 1:
				return "Web visual LOD transition was invalid"
			var signature: PackedInt32Array = lod.lod_counts
			if cycle == 0:
				expected_signatures.append(signature.duplicate())
			elif signature != expected_signatures[position_index]:
				return "Web LOD promotion/demotion was not deterministic"
	camera.position = Vector3(-256.0, 80.0, -256.0)
	camera.look_at(Vector3.ZERO)
	_terrain.call(&"update")
	var maximum_lod: Dictionary = _terrain.call(&"get_runtime_state").visual_lod
	if int(maximum_lod.maximum_lod) != int(maximum_lod.maximum_supported_lod) \
	or int(maximum_lod.maximum_neighbor_delta) > 1:
		return "Web maximum LOD transition fixture did not pass"

	_terrain.call(&"set_grid_create", false)
	var cleared: Dictionary = _terrain.call(&"get_runtime_state")
	if not cleared.pending.is_empty() \
	or int(cleared.resident_tile_count) != 0 \
	or int(cleared.loaded_region_count) != 0:
		return "Web destroy retained runtime ownership"
	var negative_offset := Vector3(-512.0, 0.0, -384.0)
	_terrain.call(&"set_offset", negative_offset)
	camera.position = negative_offset + Vector3(128.0, 96.0, 196.0)
	camera.look_at(negative_offset + Vector3(128.0, 0.0, 128.0))
	_terrain.call(&"set_grid_create", true)
	if not bool(_terrain.call(&"is_grid_created")):
		return "Web terrain did not recreate"
	var heights := _make_global_plane_tile(20, 20, 17, 17)
	var applied: Dictionary = _terrain.call(
		&"apply_height_tile",
		20,
		20,
		17,
		17,
		heights,
		false,
	)
	if not bool(applied.get("ok", false)):
		return "Web recreated terrain rejected its tile"
	var world_position: Vector3 = _terrain.call(&"get_pixel_world_pos", 28, 28)
	if world_position.x >= 0.0 or world_position.z >= 0.0 \
	or _terrain.call(&"get_closest_pixel", world_position) != Vector2i(28, 28) \
	or not is_equal_approx(
		float(_terrain.call(&"get_height", world_position)),
		float(heights[8 * 17 + 8]),
	):
		return "Web negative offset did not round-trip terrain data"
	var recreated: Dictionary = _terrain.call(&"get_runtime_state")
	if recreated.visual_lod.terrain_offset != negative_offset:
		return "Web recreated LOD state omitted the negative offset"
	return ""


func _make_global_plane_tile(
	start_x: int,
	start_y: int,
	width: int,
	height: int
) -> PackedFloat32Array:
	var heights := PackedFloat32Array()
	heights.resize(width * height)
	for local_y in height:
		for local_x in width:
			var global_x := start_x + local_x
			var global_y := start_y + local_y
			heights[local_y * width + local_x] = (
				float(global_x) * 0.0625 + float(global_y) * 0.03125
			)
	return heights


func _verify_extended_runtime() -> String:
	var runtime_script := load("res://runtime/web_extended_runtime.gd")
	if runtime_script == null:
		return "web_extended companion script did not load"
	var runtime := runtime_script.new() as Node3D
	if runtime == null:
		return "web_extended companion could not be instantiated"
	add_child(runtime)
	var companion_capabilities: Dictionary = runtime.call(&"get_runtime_capabilities")
	if companion_capabilities.get("api_version") != 1 \
	or companion_capabilities.get("runtime_navigation_baking") != false \
	or companion_capabilities.get("runtime_curve_deformation") != false \
	or companion_capabilities.get("prebaked_path_collision") != true \
	or companion_capabilities.get("runtime_path_collision_generation") != false \
	or companion_capabilities.get("hlod_cross_fade") != true \
	or not (companion_capabilities.get("foliage_quality_tiers", {}) as Dictionary).has("low"):
		runtime.queue_free()
		return "web_extended companion capability contract was inconsistent"
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
	var configured: Dictionary = runtime.call(
		&"configure_limits",
		{
			"allowed_resource_paths": allowed_paths,
			"allow_path_collision": true,
			"max_path_collision_projections": 2,
			"hlod_cross_fade_steps": 3,
		},
	)
	if not bool(configured.get("ok", false)):
		runtime.queue_free()
		return "web_extended exported-resource policy failed closed"
	var mesh := load("res://fixtures/grass_cluster.obj") as Mesh
	var grass_material := load("res://fixtures/grass_material.tres") as Material
	var road_mesh := load("res://fixtures/road_strip.obj") as Mesh
	var road_material := load("res://fixtures/road_material.tres") as Material
	var road_collision := load("res://fixtures/road_collision.tres") as Shape3D
	var near_mesh := load("res://fixtures/rock_near.obj") as Mesh
	var farther_mesh := load("res://fixtures/rock_far.obj") as Mesh
	var navigation_mesh := load("res://fixtures/walkable_nav.tres") as NavigationMesh
	if mesh == null or grass_material == null or road_mesh == null \
	or road_material == null or near_mesh == null or farther_mesh == null \
	or road_collision == null or navigation_mesh == null:
		runtime.queue_free()
		return "web_extended exported fixture resource failed to load"
	var grass_basis := Basis.IDENTITY.scaled(Vector3(3.0, 4.0, 3.0))
	var transforms: Array = [
		Transform3D(grass_basis, Vector3(118.0, _fixture_height(118.0, 120.0) + 0.2, 120.0)),
		Transform3D(grass_basis, Vector3(122.0, _fixture_height(122.0, 120.0) + 0.2, 120.0)),
		Transform3D(grass_basis, Vector3(126.0, _fixture_height(126.0, 120.0) + 0.2, 120.0)),
	]
	var queued := [
		runtime.call(
			&"queue_foliage",
			"browser-grove",
			1,
			4,
			mesh,
				transforms,
				grass_material,
				&"low",
				16.0,
			),
		runtime.call(
			&"queue_navigation",
			"browser-nav-left",
			1,
			3,
			navigation_mesh,
			Transform3D(Basis.IDENTITY, Vector3(128.0, 72.0, 128.0)),
		),
		runtime.call(
			&"queue_navigation",
			"browser-nav-right",
			1,
			3,
			navigation_mesh,
			Transform3D(Basis.IDENTITY, Vector3(144.0, 72.0, 128.0)),
		),
		runtime.call(
			&"queue_path",
			"browser-road",
			1,
			2,
			road_mesh,
			Transform3D(Basis.IDENTITY, Vector3(128.0, 72.0, 128.0)),
			road_material,
			road_collision,
		),
		runtime.call(
			&"queue_mesh_hlod",
			"browser-hlod",
			1,
			1,
			[near_mesh, farther_mesh],
			PackedFloat32Array([10.0, 100.0]),
			Transform3D(
				Basis.IDENTITY.scaled(Vector3(3.0, 3.0, 3.0)),
				Vector3(136.0, _fixture_height(136.0, 128.0) + 0.2, 128.0),
			),
			road_material,
		),
	]
	for result in queued:
		if not bool(result.get("ok", false)):
			runtime.queue_free()
			return "web_extended projection failed to queue: %s" % JSON.stringify(result)
	var hlod_near := Vector3(136.0, _fixture_height(136.0, 128.0) + 0.2, 128.0)
	for _step in 32:
		var stepped: Dictionary = runtime.call(
			&"step_runtime_work",
			1,
			1,
			hlod_near,
		)
		if stepped.get("status") == "idle":
			break
	var state: Dictionary = runtime.call(&"get_runtime_state")
	for capability in [&"foliage", &"paths", &"mesh_hlod"]:
		if int(state.installed_counts.get(capability, 0)) != 1:
			runtime.queue_free()
			return "web_extended did not install %s" % capability
	if int(state.installed_counts.navigation) != 2 \
	or int(state.installed_collision_shapes.paths) != 1 \
	or str(state.installed.foliage[0].quality_tier) != "low" \
	or state.installed.mesh_hlod[0].lod_index != 0:
		runtime.queue_free()
		return "web_extended installed-state maturation contract was incomplete"
	var navigation_map := runtime.get_world_3d().navigation_map
	var navigation_path := PackedVector3Array()
	for _iteration in 30:
		await get_tree().physics_frame
		NavigationServer3D.map_force_update(navigation_map)
		navigation_path = NavigationServer3D.map_get_path(
			navigation_map,
			Vector3(124.0, 72.0, 124.0),
			Vector3(148.0, 72.0, 132.0),
			true,
		)
		if navigation_path.size() >= 2:
			break
	if navigation_path.size() < 2:
		runtime.queue_free()
		return "web_extended navigation projection did not answer a browser path query"
	var collision_hit := runtime.get_world_3d().direct_space_state.intersect_ray(
		PhysicsRayQueryParameters3D.create(
			Vector3(128.0, 75.0, 128.0),
			Vector3(128.0, 69.0, 128.0),
		),
	)
	if collision_hit.is_empty():
		runtime.queue_free()
		return "web_extended pre-baked path collision did not answer a browser ray query"
	var moved_transforms := transforms.duplicate(true)
	for index in moved_transforms.size():
		var moved_transform: Transform3D = moved_transforms[index]
		moved_transform.origin.x += 1.0
		moved_transforms[index] = moved_transform
	var replacements := [
		runtime.call(
			&"queue_foliage", "browser-grove", 2, 4, mesh, moved_transforms,
			grass_material, &"low", 16.0,
		),
		runtime.call(
			&"queue_navigation", "browser-nav-left", 2, 3, navigation_mesh,
			Transform3D(Basis.IDENTITY, Vector3(129.0, 72.0, 128.0)),
		),
		runtime.call(
			&"queue_navigation", "browser-nav-right", 2, 3, navigation_mesh,
			Transform3D(Basis.IDENTITY, Vector3(145.0, 72.0, 128.0)),
		),
		runtime.call(
			&"queue_path", "browser-road", 2, 2, road_mesh,
			Transform3D(Basis.IDENTITY, Vector3(129.0, 72.0, 128.0)), road_material,
			road_collision,
		),
		runtime.call(
			&"queue_mesh_hlod", "browser-hlod", 2, 1, [near_mesh, farther_mesh],
			PackedFloat32Array([10.0, 100.0]),
			Transform3D(
				Basis.IDENTITY.scaled(Vector3(3.0, 3.0, 3.0)),
				Vector3(137.0, _fixture_height(137.0, 128.0) + 0.2, 128.0),
			),
			road_material,
		),
	]
	for replacement in replacements:
		if not bool(replacement.get("ok", false)):
			runtime.queue_free()
			return "web_extended moving replacement failed: %s" % JSON.stringify(replacement)
	var hlod_far := Vector3(500.0, 72.0, 500.0)
	for _step in 32:
		var stepped: Dictionary = runtime.call(
			&"step_runtime_work", 1, 1, hlod_far,
		)
		if stepped.get("status") == "idle":
			break
	state = runtime.call(&"get_runtime_state")
	for capability in [&"foliage", &"paths", &"mesh_hlod"]:
		if int(state.installed[capability][0].revision) != 2:
			runtime.queue_free()
			return "web_extended moving replacement did not install %s revision 2" % capability
	if int(state.installed.navigation[0].revision) != 2 \
	or int(state.installed.navigation[1].revision) != 2:
		runtime.queue_free()
		return "web_extended moving replacement did not install both navigation revisions"
	if int(state.metrics.get("hlod_swaps", 0)) < 1 \
	or int(state.metrics.get("hlod_transition_steps", 0)) < 3 \
	or int(state.metrics.get("path_collision_installs", 0)) < 2:
		runtime.queue_free()
		return "web_extended bounded HLOD fade or path-collision replacement did not finish"
	return ""


func _fixture_height(x: float, z: float) -> float:
	var dx := x - 130.0
	var dz := z - 130.0
	return 72.0 * exp(-(dx * dx + dz * dz) / 520.0)


func _triangle_mesh(scale: float) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3.ZERO,
		Vector3(scale, 0.0, 0.0),
		Vector3(0.0, scale, 0.0),
	])
	arrays[Mesh.ARRAY_NORMAL] = PackedVector3Array([
		Vector3.BACK,
		Vector3.BACK,
		Vector3.BACK,
	])
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh
