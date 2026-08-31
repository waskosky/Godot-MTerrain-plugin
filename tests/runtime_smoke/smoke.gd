extends SceneTree


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var failures: Array[String] = []
	var expected_profile := OS.get_environment("MTERRAIN_EXPECTED_PROFILE")
	if expected_profile.is_empty():
		expected_profile = "web_core"
	var extended := expected_profile == "web_extended"
	if not ClassDB.class_exists(&"MTerrain"):
		failures.append("MTerrain did not register")
	for excluded_class in [&"MGrass", &"MNavigationRegion3D", &"MPath", &"MHlod"]:
		if ClassDB.class_exists(excluded_class):
			failures.append("%s unexpectedly registered %s" % [expected_profile, excluded_class])

	var terrain := ClassDB.instantiate(&"MTerrain") as Node3D
	if terrain == null:
		failures.append("MTerrain could not be instantiated")
	else:
		var capabilities: Dictionary = terrain.call(&"get_runtime_capabilities")
		if capabilities.get(&"api_version") != 2:
			failures.append("runtime API version is not 2")
		if capabilities.get(&"api_stability") != "experimental":
			failures.append("runtime API stability is not experimental")
		if capabilities.get(&"build_profile") != expected_profile:
			failures.append("build profile is not %s" % expected_profile)
		if capabilities.get(&"single_threaded") != true:
			failures.append("web_core did not report single_threaded")
		if capabilities.get(&"runtime_memory_only") != true:
			failures.append("web_core did not default to runtime_memory_only")
		if capabilities.get(&"heightfield_terrain") != true:
			failures.append("heightfield terrain capability was not reported")
		if capabilities.get(&"bounded_update_scheduler") != true:
			failures.append("bounded scheduler capability was not reported")
		if capabilities.get(&"bounded_collision") != true:
			failures.append("bounded collision capability was not reported")
		if capabilities.get(&"height_tile_release") != true:
			failures.append("height tile release capability was not reported")
		if capabilities.get(&"phase_timing_metrics") != true:
			failures.append("runtime phase timing capability was not reported")
		if capabilities.get(&"scheduler_owned_visual_residency") != true:
			failures.append("scheduler-owned visual residency was not reported")
		var topology_limits: Dictionary = capabilities.get(&"topology_limits", {})
		if topology_limits.get(&"maximum_terrain_topology_points") != 65536 \
		or topology_limits.get(&"maximum_terrain_regions") != 1024 \
		or topology_limits.get(&"maximum_visual_range_quads") != 128:
			failures.append("bounded topology capability contract was inconsistent")
		for extended_capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
			if capabilities.get(extended_capability) != extended:
				failures.append(
					"%s reported the wrong %s capability" \
					% [expected_profile, extended_capability]
				)
		if extended and capabilities.get(&"extended_runtime_api_version") != 1:
			failures.append("web_extended companion API version is not 1")
		for unsupported_capability in [
			&"foliage_collision",
			&"runtime_navigation_baking",
			&"runtime_curve_deformation",
			&"path_collision",
			&"runtime_mesh_generation",
		]:
			if capabilities.get(unsupported_capability) != false:
				failures.append("Web profile over-reported %s" % unsupported_capability)
		var rejected: Dictionary = terrain.call(
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

		var world := Node3D.new()
		root.add_child(world)
		var camera := Camera3D.new()
		camera.position = Vector3(128.0, 96.0, 196.0)
		world.add_child(camera)
		camera.look_at(Vector3(128.0, 0.0, 128.0))
		world.add_child(terrain)
		terrain.call(&"set_custom_camera", camera)
		# Four 128-metre regions. The 97..163 tile crosses both shared
		# region borders at pixel 128 while remaining bounded to 67x67.
		terrain.call(&"set_terrain_size", Vector2i(8, 8))
		terrain.call(&"set_region_size", 4)
		terrain.call(&"set_lod_distance", PackedInt32Array([1, 2, 3, 4, 5]))
		terrain.call(&"set_grid_create", true)
		if not bool(terrain.call(&"is_grid_created")):
			failures.append("memory-only terrain grid was not created")
		else:
			var initial_state: Dictionary = terrain.call(&"get_runtime_state")
			if int(initial_state.get("loaded_region_count", -1)) != 0 \
			or int(initial_state.get("resident_tile_count", -1)) != 0 \
			or int(initial_state.visual_lod.get("visible_points", -1)) != 0:
				failures.append("grid creation bypassed scheduler-owned visual residency")
			var heights := PackedFloat32Array()
			heights.resize(67 * 67)
			for local_y in range(67):
				for local_x in range(67):
					heights[local_y * 67 + local_x] = (
						float(local_x) * 0.125 + float(local_y) * 0.25
					)
			var applied: Dictionary = terrain.call(
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
			else:
				var sample := float(terrain.call(&"get_height_by_pixel", 128, 128))
				var expected := float((128 - 97) * 0.125 + (128 - 97) * 0.25)
				if not is_equal_approx(sample, expected):
					failures.append("height tile did not survive the shared region border")
			var height_before_rejection := float(
				terrain.call(&"get_height_by_pixel", 128, 128)
			)
			var invalid_heights := heights.duplicate()
			invalid_heights[0] = NAN
			var invalid: Dictionary = terrain.call(
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
				float(terrain.call(&"get_height_by_pixel", 128, 128)),
				height_before_rejection,
			):
				failures.append("rejected height tile partially mutated terrain")
			var scheduler_error := _verify_bounded_runtime(terrain)
			if not scheduler_error.is_empty():
				failures.append(scheduler_error)
			else:
				var collision_error := await _verify_collision_alignment(terrain)
				if not collision_error.is_empty():
					failures.append(collision_error)
				else:
					var release_error := _verify_release_and_eviction(terrain)
					if not release_error.is_empty():
						failures.append(release_error)
					else:
						var lod_error := _verify_lod_transitions(terrain, camera)
						if not lod_error.is_empty():
							failures.append(lod_error)
						else:
							var recreate_error := _verify_recreate_with_negative_offset(
								terrain,
								camera,
							)
							if not recreate_error.is_empty():
								failures.append(recreate_error)
		terrain.call(&"set_grid_create", false)
		world.queue_free()

	if failures.is_empty():
		print(
			"MTERRAIN_RUNTIME_SMOKE_OK initialized_tile_samples=4489 ",
			"rejected_non_finite=1 bounded_scheduler=1 bounded_collision=1 ",
			"rejected_border=1 lod_transitions=1 recreate=1 phase_timings=1 ",
			"scheduler_visual=1 ",
			"profile=%s" % expected_profile,
		)
		quit(0)
	else:
		for failure in failures:
			push_error(failure)
		quit(1)


func _verify_bounded_runtime(terrain: Node3D) -> String:
	var unknown_limit: Dictionary = terrain.call(
		&"configure_runtime_limits",
		{"max_pending_work_typo": 8},
	)
	if unknown_limit.get("code") != "unknown_limit_key":
		return "unknown runtime limit did not fail closed"
	var wrong_limit_type: Dictionary = terrain.call(
		&"configure_runtime_limits",
		{"max_pending_work": 8.0},
	)
	if wrong_limit_type.get("code") != "invalid_limit_type":
		return "non-integer runtime limit did not fail closed"
	var configured: Dictionary = terrain.call(&"configure_runtime_limits", {
		"max_pending_work": 8,
		"max_resident_tiles": 4,
		"max_resident_regions": 4,
		"max_collision_regions": 2,
		"max_estimated_region_bytes": 8 * 1024 * 1024,
	})
	if not bool(configured.get("ok", false)):
		return "bounded runtime limits failed: %s" % JSON.stringify(configured)
	var material: Dictionary = terrain.call(&"configure_runtime_material", {
		"low_color": Color(0.12, 0.22, 0.14),
		"high_color": Color(0.52, 0.46, 0.31),
		"steep_color": Color(0.24, 0.23, 0.22),
		"readable_emission": 0.4,
	})
	if not bool(material.get("ok", false)) or not bool(material.get("missing_texture_readable", false)):
		return "bounded Compatibility material failed: %s" % JSON.stringify(material)
	var unknown_material: Dictionary = terrain.call(
		&"configure_runtime_material",
		{"readable_emision": 0.4},
	)
	if unknown_material.get("code") != "unknown_material_key":
		return "unknown Compatibility material key did not fail closed"
	var wrong_material_type: Dictionary = terrain.call(
		&"configure_runtime_material",
		{"low_color": "green"},
	)
	if wrong_material_type.get("code") != "invalid_material_color_type":
		return "wrong Compatibility material type did not fail closed"
	var rejected_material: Dictionary = terrain.call(
		&"configure_runtime_material",
		{"surface_layer_count": 5},
	)
	if rejected_material.get("code") != "surface_sample_limit":
		return "Compatibility material sample limit did not fail closed"
	var low_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	low_image.fill(Color(0.12, 0.32, 0.14, 1.0))
	var high_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	high_image.fill(Color(0.56, 0.48, 0.24, 1.0))
	var surface_layers := Texture2DArray.new()
	var layer_images: Array[Image] = [low_image, high_image]
	if surface_layers.create_from_images(layer_images) != OK:
		return "Compatibility texture array fixture could not be created"
	var splat_image := Image.create(2, 2, false, Image.FORMAT_RGBA8)
	splat_image.fill(Color(0.65, 0.35, 0.0, 0.0))
	var splatmap := ImageTexture.create_from_image(splat_image)
	var textured_material: Dictionary = terrain.call(&"configure_runtime_material", {
		"surface_layer_count": 2,
		"surface_layers": surface_layers,
		"splatmap": splatmap,
		"readable_emission": 0.25,
	})
	if not bool(textured_material.get("ok", false)) \
	or int(textured_material.get("surface_layer_count", 0)) != 2:
		return "Compatibility texture-array material failed: %s" % JSON.stringify(textured_material)

	var heights := PackedFloat32Array()
	heights.resize(17 * 17)
	for local_y in 17:
		for local_x in 17:
			heights[local_y * 17 + local_x] = float(local_x + local_y)
	var queued: Dictionary = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		1,
		10,
		20,
		20,
		17,
		17,
		heights,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "bounded height work failed to queue: %s" % JSON.stringify(queued)
	var busy_immediate: Dictionary = terrain.call(
		&"apply_height_tile",
		20,
		20,
		1,
		1,
		PackedFloat32Array([99.0]),
		false,
	)
	if busy_immediate.get("code") != "work_in_progress":
		return "immediate compatibility apply did not preserve queued work isolation"
	var steps := _drain_runtime(terrain, 128, 1)
	if steps < 5:
		return "height work did not expose bounded multi-step progress"
	if not is_equal_approx(float(terrain.call(&"get_height_by_pixel", 28, 28)), 16.0):
		return "bounded height work installed the wrong samples"

	var replacement := heights.duplicate()
	for index in replacement.size():
		replacement[index] += 100.0
	queued = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		2,
		10,
		20,
		20,
		17,
		17,
		replacement,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "replacement work failed to queue"
	var observed_partial_write := false
	for _iteration in 32:
		var stepped: Dictionary = terrain.call(&"step_runtime_work", 128, 1)
		if int(stepped.get("sample_ops", 0)) > 128 \
		or int(stepped.get("region_ops", 0)) > 1:
			return "runtime step exceeded its declared operation budget"
		var state: Dictionary = terrain.call(&"get_runtime_state")
		if not state.pending.is_empty() \
		and state.pending[0].phase == "write_heights" \
		and int(state.pending[0].write_cursor) > 0:
			observed_partial_write = true
			break
	if not observed_partial_write:
		return "replacement work never exposed a cancellable write phase"
	terrain.call(&"cancel_runtime_work", "bounded-tile", 2)
	var cancelling_revision: Dictionary = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		2,
		10,
		20,
		20,
		17,
		17,
		replacement,
		false,
	)
	if cancelling_revision.get("code") != "revision_cancelling":
		return "a cancelling revision was incorrectly reported as already queued"
	_drain_runtime(terrain, 128, 1)
	if not is_equal_approx(float(terrain.call(&"get_height_by_pixel", 28, 28)), 16.0):
		return "cancelled replacement did not roll back staged height writes"
	var cancelled: Dictionary = terrain.call(&"take_runtime_work_result", "bounded-tile", 2)
	if cancelled.get("code") != "cancelled":
		return "cancelled replacement did not retain its bounded receipt"

	terrain.call(&"queue_height_tile", "bounded-tile", 3, 10, 20, 20, 17, 17, replacement, false)
	var final_heights := replacement.duplicate()
	for index in final_heights.size():
		final_heights[index] += 50.0
	queued = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		4,
		10,
		20,
		20,
		17,
		17,
		final_heights,
		true,
	)
	if not bool(queued.get("ok", false)):
		return "coalesced final revision failed to queue"
	_drain_runtime(terrain, 128, 1)
	var state: Dictionary = terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready) or int(state.collision.revision) < 0:
		return "update_collision did not establish bounded collision residency"
	var bounded_result: Dictionary = terrain.call(
		&"take_runtime_work_result",
		"bounded-tile",
		4,
	)
	if not bool(bounded_result.get("ok", false)):
		return "coalesced final revision did not retain its completion receipt"
	var superseded_result: Dictionary = terrain.call(
		&"take_runtime_work_result",
		"bounded-tile",
		3,
	)
	if superseded_result.get("code") != "coalesced":
		return "superseded revision did not retain its coalesced receipt"
	if int(bounded_result.get("texture_uploads", 0)) < 1 \
	or int(bounded_result.get("texture_uploads", 0)) \
	> int(bounded_result.get("affected_regions", 0)) * 2:
		return "per-region texture upload instrumentation exceeded its bounded contract"

	var postwrite := final_heights.duplicate()
	for index in postwrite.size():
		postwrite[index] += 25.0
	queued = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		5,
		10,
		20,
		20,
		17,
		17,
		postwrite,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "post-write replacement fixture failed to queue"
	observed_partial_write = false
	for _iteration in 32:
		var stepped: Dictionary = terrain.call(&"step_runtime_work", 128, 1)
		if int(stepped.get("sample_ops", 0)) > 128 \
		or int(stepped.get("region_ops", 0)) > 1:
			return "post-write step exceeded its declared operation budget"
		state = terrain.call(&"get_runtime_state")
		if not state.pending.is_empty() \
		and state.pending[0].phase == "write_heights" \
		and int(state.pending[0].write_cursor) > 0:
			observed_partial_write = true
			break
	if not observed_partial_write:
		return "post-write coalescing fixture never began mutation"
	var deferred := postwrite.duplicate()
	for index in deferred.size():
		deferred[index] += 25.0
	queued = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		6,
		10,
		20,
		20,
		17,
		17,
		deferred,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "post-write successor failed to stage"
	var final_successor := deferred.duplicate()
	for index in final_successor.size():
		final_successor[index] += 25.0
	queued = terrain.call(
		&"queue_height_tile",
		"bounded-tile",
		7,
		10,
		20,
		20,
		17,
		17,
		final_successor,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "newest post-write successor failed to replace its predecessor"
	state = terrain.call(&"get_runtime_state")
	if state.pending.size() != 1 \
	or not state.pending[0].has("replacement") \
	or int(state.pending[0].replacement.revision) != 7:
		return "post-write coalescing exceeded one logical pending slot"
	if _drain_runtime(terrain, 128, 1) < 1:
		return "post-write rollback/replacement exceeded its operation budget"
	for revision in [5, 6]:
		var result: Dictionary = terrain.call(
			&"take_runtime_work_result",
			"bounded-tile",
			revision,
		)
		if result.get("code") != "coalesced":
			return "post-write superseded revision %d omitted its receipt" % revision
	var final_successor_result: Dictionary = terrain.call(
		&"take_runtime_work_result",
		"bounded-tile",
		7,
	)
	if not bool(final_successor_result.get("ok", false)):
		return "post-write successor did not install"
	if not is_equal_approx(
		float(terrain.call(&"get_height_by_pixel", 28, 28)),
		float(final_successor[8 * 17 + 8]),
	):
		return "post-write successor did not win after bounded rollback"

	# Cancellation after the first region upload must restore both the CPU
	# heightfield and every potentially visible texture, one region operation at
	# a time. This catches a stale-GPU rollback that height-only assertions miss.
	var upload_baseline := float(terrain.call(&"get_height_by_pixel", 128, 128))
	var upload_rollback_heights := PackedFloat32Array()
	upload_rollback_heights.resize(67 * 67)
	upload_rollback_heights.fill(777.0)
	queued = terrain.call(
		&"queue_height_tile",
		"rollback-upload",
		1,
		30,
		97,
		97,
		67,
		67,
		upload_rollback_heights,
		false,
	)
	if not bool(queued.get("ok", false)):
		return "rollback-upload fixture failed to queue: %s" % JSON.stringify(queued)
	var observed_partial_apply := false
	for _iteration in 160:
		var stepped: Dictionary = terrain.call(&"step_runtime_work", 128, 1)
		if not bool(stepped.get("ok", false)) \
		or int(stepped.get("sample_ops", 0)) > 128 \
		or int(stepped.get("region_ops", 0)) > 1:
			return "rollback-upload step exceeded its declared operation budget"
		state = terrain.call(&"get_runtime_state")
		if not state.pending.is_empty() \
		and state.pending[0].phase == "apply" \
		and int(state.pending[0].get("apply_region_cursor", 0)) > 0:
			observed_partial_apply = true
			break
	if not observed_partial_apply:
		return "rollback-upload fixture never exposed a partial apply phase"
	terrain.call(&"cancel_runtime_work", "rollback-upload", 1)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "rollback-upload cancellation exceeded its operation budget"
	if not is_equal_approx(
		float(terrain.call(&"get_height_by_pixel", 128, 128)),
		upload_baseline,
	):
		return "partial apply cancellation did not restore its heightfield"
	var upload_cancelled: Dictionary = terrain.call(
		&"take_runtime_work_result",
		"rollback-upload",
		1,
	)
	if upload_cancelled.get("code") != "cancelled" \
	or int(upload_cancelled.get("rollback_texture_uploads", 0)) < 1:
		return "partial apply cancellation omitted bounded texture rollback"

	var collision_request: Dictionary = terrain.call(
		&"request_runtime_collision_focus",
		128,
		64,
		1,
		2,
		1,
	)
	if not bool(collision_request.get("ok", false)):
		return "bounded collision focus failed: %s" % JSON.stringify(collision_request)

	var seam_left := _make_global_plane_tile(62, 30, 67, 67)
	var seam_right := _make_global_plane_tile(128, 30, 67, 67)
	queued = terrain.call(
		&"queue_height_tile",
		"seam-left",
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
		return "left seam tile failed to queue: %s" % JSON.stringify(queued)
	_drain_runtime(terrain, 128, 1)
	var mismatch := seam_right.duplicate()
	for local_y in 67:
		mismatch[local_y * 67] += 1.0
	var seam_before_mismatch := float(terrain.call(&"get_height_by_pixel", 128, 64))
	var rejected_mismatch: Dictionary = terrain.call(
		&"queue_height_tile",
		"seam-right-mismatch",
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
		return "mismatched shared border did not fail closed"
	if not is_equal_approx(
		float(terrain.call(&"get_height_by_pixel", 128, 64)),
		seam_before_mismatch,
	):
		return "rejected shared border partially mutated terrain"
	queued = terrain.call(
		&"queue_height_tile",
		"seam-right",
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
		return "matching adjacent seam tile failed to queue: %s" % JSON.stringify(queued)
	_drain_runtime(terrain, 128, 1)
	var seam_height := float(terrain.call(&"get_height_by_pixel", 128, 64))
	var expected_seam_height := 128.0 * 0.0625 + 64.0 * 0.03125
	if not is_equal_approx(seam_height, expected_seam_height):
		return "adjacent tiles did not preserve their exact shared height border"
	var left_normal: Vector3 = terrain.call(&"get_normal_by_pixel", 127, 64)
	var right_normal: Vector3 = terrain.call(&"get_normal_by_pixel", 129, 64)
	if left_normal.distance_to(right_normal) > 0.015:
		return "adjacent tile normals were discontinuous at the shared border"

	state = terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready):
		return "bounded collision did not become ready"
	if state.collision.regions.is_empty():
		return "bounded collision state omitted its owned region accounting"
	for collision_region in state.collision.regions:
		if not bool(collision_region.ready) \
		or int(collision_region.generation) < 1:
			return "bounded collision generation was not exposed after refresh"
	var active_region_id := int(state.collision.active_regions[0])
	var generation_before := -1
	for collision_region in state.collision.regions:
		if int(collision_region.region_id) == active_region_id:
			generation_before = int(collision_region.generation)
	var refresh_x: int = (active_region_id % 2) * 128 + 40
	var refresh_y: int = floori(float(active_region_id) / 2.0) * 128 + 40
	queued = terrain.call(
		&"queue_height_tile",
		"collision-refresh-without-admission",
		1,
		20,
		refresh_x,
		refresh_y,
		1,
		1,
		PackedFloat32Array([
			float(terrain.call(&"get_height_by_pixel", refresh_x, refresh_y)) + 0.25,
		]),
		false,
	)
	if not bool(queued.get("ok", false)):
		return "active-collision refresh fixture failed to queue"
	_drain_runtime(terrain, 128, 1)
	state = terrain.call(&"get_runtime_state")
	var generation_after := -1
	for collision_region in state.collision.regions:
		if int(collision_region.region_id) == active_region_id:
			generation_after = int(collision_region.generation)
	if generation_after <= generation_before:
		return "terrain edit left an already-active collision shape stale"
	if int(state.metrics.coalesced) < 1 or int(state.metrics.collision_applies) < 1:
		return "bounded coalescing/collision metrics were not recorded"
	if state.metrics.get("phase_timing_contract") != "mterrain-runtime-phase-timings/v1":
		return "runtime phase timing contract was not reported"
	for phase in [
		"region_load",
		"preflight",
		"write_heights",
		"generate_normals",
		"texture_apply",
		"collision",
		"rollback_heights",
		"rollback_normals",
		"rollback_apply",
	]:
		if not state.metrics.phase_timings.has(phase) \
		or int(state.metrics.phase_timings[phase].invocations) < 1:
			return "runtime phase timing was not recorded for %s" % phase
	return ""


func _verify_collision_alignment(terrain: Node3D) -> String:
	await physics_frame
	await physics_frame
	var space_state := terrain.get_world_3d().direct_space_state
	for x in [127.25, 127.75, 128.25, 128.75]:
		var query := PhysicsRayQueryParameters3D.create(
			Vector3(x, 200.0, 64.0),
			Vector3(x, -200.0, 64.0),
		)
		var hit := space_state.intersect_ray(query)
		if hit.is_empty():
			return "collision ray missed the adjacent-tile seam at x=%.2f" % x
		var expected := float(terrain.call(&"get_height", Vector3(x, 0.0, 64.0)))
		if abs(float(hit.position.y) - expected) > 0.2:
			return "collision and visual heightfields diverged at x=%.2f" % x
	return ""


func _verify_release_and_eviction(terrain: Node3D) -> String:
	# Replace an unstepped collision focus twice. The final active set must match
	# the final intent; superseded operations cannot strand old collision bodies.
	for request in [
		[20, 148, 2],
		[148, 148, 3],
	]:
		var moved: Dictionary = terrain.call(
			&"request_runtime_collision_focus",
			request[0],
			request[1],
			0,
			1,
			request[2],
		)
		if not bool(moved.get("ok", false)):
			return "rapid collision focus replacement failed: %s" % JSON.stringify(moved)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "rapid collision focus replacement exceeded its operation budget"
	var moved_state: Dictionary = terrain.call(&"get_runtime_state")
	if moved_state.collision.active_regions != moved_state.collision.desired_regions \
	or moved_state.collision.active_regions.size() != 1:
		return "rapid collision focus replacement stranded an old collision body"
	var in_use_limit: Dictionary = terrain.call(&"configure_runtime_limits", {
		"max_collision_regions": 0,
	})
	if in_use_limit.get("code") != "collision_limit_in_use":
		return "live collision ownership allowed its ceiling to shrink underneath it"
	for release in [
		terrain.call(&"release_runtime_tile", "bounded-tile", 7),
		terrain.call(&"release_runtime_tile", "seam-left", 1),
		terrain.call(&"release_runtime_tile", "seam-right", 1),
		terrain.call(&"release_runtime_tile", "collision-refresh-without-admission", 1),
		terrain.call(&"release_height_tile", 97, 97, 67, 67),
	]:
		if not bool(release.get("ok", false)):
			return "runtime tile release failed: %s" % JSON.stringify(release)
	var collision_release: Dictionary = terrain.call(
		&"request_runtime_collision_focus",
		128,
		64,
		0,
		0,
		4,
	)
	if not bool(collision_release.get("ok", false)):
		return "zero-region collision release failed: %s" % JSON.stringify(collision_release)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "collision/tile retirement exceeded its operation budget"
	var state: Dictionary = terrain.call(&"get_runtime_state")
	if int(state.resident_tile_count) != 0 or int(state.loaded_region_count) != 0:
		return "tile/collision release did not return residency to zero"
	var queued_after_clear: Dictionary = terrain.call(
		&"queue_height_tile",
		"collision-after-clear",
		1,
		0,
		20,
		20,
		1,
		1,
		PackedFloat32Array([4.0]),
		true,
	)
	if not bool(queued_after_clear.get("ok", false)):
		return "post-clear collision fixture failed to queue"
	if _drain_runtime(terrain, 128, 1) < 1:
		return "post-clear collision fixture exceeded its operation budget"
	state = terrain.call(&"get_runtime_state")
	if not bool(state.collision.ready) \
	or not state.collision.desired_regions.is_empty() \
	or not state.collision.regions.is_empty():
		return "explicit empty collision focus was repopulated by a tile update"
	terrain.call(&"release_runtime_tile", "collision-after-clear", 1)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "post-clear collision fixture did not retire within budget"

	var reconfigured: Dictionary = terrain.call(&"configure_runtime_limits", {
		"max_resident_tiles": 2,
		"max_resident_regions": 2,
		"max_collision_regions": 0,
	})
	if not bool(reconfigured.get("ok", false)):
		return "teleport eviction limits failed: %s" % JSON.stringify(reconfigured)
	var before_evictions := int(state.metrics.evicted_tiles)
	for request in [
		["teleport-a", 20, 20, 1.0],
		["teleport-b", 148, 20, 2.0],
		["teleport-c", 148, 148, 3.0],
	]:
		var queued: Dictionary = terrain.call(
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
		if not bool(queued.get("ok", false)):
			return "teleport tile failed to queue: %s" % JSON.stringify(queued)
		_drain_runtime(terrain, 128, 1)
	state = terrain.call(&"get_runtime_state")
	if int(state.resident_tile_count) != 2 or int(state.loaded_region_count) > 2:
		return "teleport traversal exceeded bounded tile/region residency"
	if int(state.metrics.evicted_tiles) <= before_evictions:
		return "teleport traversal did not record deterministic LRU eviction"
	var resident_keys: Array[String] = []
	for record in state.resident:
		resident_keys.append(str(record.work_key))
	if "teleport-a" in resident_keys or "teleport-b" not in resident_keys \
	or "teleport-c" not in resident_keys:
		return "teleport traversal evicted a non-LRU tile"
	terrain.call(&"release_runtime_tile", "teleport-b", 1)
	terrain.call(&"release_runtime_tile", "teleport-c", 1)
	_drain_runtime(terrain, 128, 1)
	state = terrain.call(&"get_runtime_state")
	if int(state.loaded_region_count) != 0:
		return "teleport fixture did not release its region buffers"
	if not state.metrics.phase_timings.has("eviction") \
	or int(state.metrics.phase_timings.eviction.invocations) < 1:
		return "runtime eviction timing was not recorded"
	return ""


func _verify_lod_transitions(terrain: Node3D, camera: Camera3D) -> String:
	var queued: Dictionary = terrain.call(
		&"queue_height_tile",
		"lod-visual",
		1,
		0,
		20,
		20,
		1,
		1,
		PackedFloat32Array([1.0]),
		false,
	)
	if not bool(queued.get("ok", false)) \
	or _drain_runtime(terrain, 128, 1) < 1:
		return "visual LOD fixture could not establish scheduler residency"
	var near_position := Vector3(32.0, 80.0, 32.0)
	var far_position := Vector3(224.0, 80.0, 224.0)
	var expected_signatures: Array[PackedInt32Array] = []
	var previous_revision := int(terrain.call(&"get_runtime_state").visual_lod.revision)
	for cycle in 3:
		for position_index in 2:
			camera.position = near_position if position_index == 0 else far_position
			camera.look_at(Vector3(128.0, 0.0, 128.0))
			terrain.call(&"update")
			var lod: Dictionary = terrain.call(&"get_runtime_state").visual_lod
			if lod.get("kind") != "mterrain-runtime-visual-lod/v1":
				return "visual LOD state contract was not reported"
			if int(lod.revision) <= previous_revision:
				return "visual LOD revision did not advance"
			previous_revision = int(lod.revision)
			if int(lod.visible_points) < 1:
				return "visual LOD update reported no visible points"
			if int(lod.maximum_neighbor_delta) > 1:
				return "visual LOD update skipped a transition level"
			if int(lod.maximum_lod) > int(lod.maximum_supported_lod):
				return "visual LOD update exceeded its supported maximum"
			var signature: PackedInt32Array = lod.lod_counts
			if cycle == 0:
				expected_signatures.append(signature.duplicate())
			elif signature != expected_signatures[position_index]:
				return "repeated LOD promotion/demotion was not deterministic"
	camera.position = Vector3(-256.0, 80.0, -256.0)
	camera.look_at(Vector3.ZERO)
	terrain.call(&"update")
	var maximum_lod: Dictionary = terrain.call(&"get_runtime_state").visual_lod
	if int(maximum_lod.maximum_lod) != int(maximum_lod.maximum_supported_lod):
		return "maximum visual LOD was not exercised"
	if int(maximum_lod.maximum_neighbor_delta) > 1:
		return "maximum visual LOD transition skipped a level"
	terrain.call(&"release_runtime_tile", "lod-visual", 1)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "visual LOD fixture did not release scheduler residency"
	return ""


func _verify_recreate_with_negative_offset(
	terrain: Node3D,
	camera: Camera3D
) -> String:
	terrain.call(&"set_grid_create", false)
	var cleared: Dictionary = terrain.call(&"get_runtime_state")
	if not cleared.pending.is_empty() \
	or int(cleared.resident_tile_count) != 0 \
	or int(cleared.loaded_region_count) != 0:
		return "destroyed terrain retained runtime ownership"
	var negative_offset := Vector3(-512.0, 0.0, -384.0)
	terrain.call(&"set_offset", negative_offset)
	camera.position = negative_offset + Vector3(128.0, 96.0, 196.0)
	camera.look_at(negative_offset + Vector3(128.0, 0.0, 128.0))
	terrain.call(&"set_grid_create", true)
	if not bool(terrain.call(&"is_grid_created")):
		return "terrain did not recreate after destruction"
	var heights := _make_global_plane_tile(20, 20, 17, 17)
	var applied: Dictionary = terrain.call(
		&"apply_height_tile",
		20,
		20,
		17,
		17,
		heights,
		false,
	)
	if not bool(applied.get("ok", false)):
		return "negative-offset recreated terrain rejected a bounded tile"
	var world_position: Vector3 = terrain.call(&"get_pixel_world_pos", 28, 28)
	if world_position.x >= 0.0 or world_position.z >= 0.0:
		return "negative terrain offset did not reach world-space projection"
	if terrain.call(&"get_closest_pixel", world_position) != Vector2i(28, 28):
		return "negative terrain offset did not round-trip pixel coordinates"
	if not is_equal_approx(
		float(terrain.call(&"get_height", world_position)),
		float(heights[8 * 17 + 8]),
	):
		return "negative terrain offset changed sampled height"
	var recreated: Dictionary = terrain.call(&"get_runtime_state")
	if recreated.visual_lod.terrain_offset != negative_offset:
		return "recreated visual LOD state omitted the negative offset"
	terrain.call(&"release_height_tile", 20, 20, 17, 17)
	if _drain_runtime(terrain, 128, 1) < 1:
		return "recreated terrain did not release within budget"
	if int(terrain.call(&"get_runtime_state").loaded_region_count) != 0:
		return "recreated terrain did not recover to zero residency"
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


func _drain_runtime(terrain: Node3D, sample_budget: int, region_budget: int) -> int:
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
		var stepped: Dictionary = terrain.call(
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
