extends SceneTree


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var failures: Array[String] = []
	if not ClassDB.class_exists(&"MTerrain"):
		failures.append("MTerrain did not register")
	for excluded_class in [&"MGrass", &"MNavigationRegion3D", &"MPath", &"MHlod"]:
		if ClassDB.class_exists(excluded_class):
			failures.append("web_core unexpectedly registered %s" % excluded_class)

	var terrain := ClassDB.instantiate(&"MTerrain") as Node3D
	if terrain == null:
		failures.append("MTerrain could not be instantiated")
	else:
		var capabilities: Dictionary = terrain.call(&"get_runtime_capabilities")
		if capabilities.get(&"api_version") != 1:
			failures.append("runtime API version is not 1")
		if capabilities.get(&"api_stability") != "experimental":
			failures.append("runtime API stability is not experimental")
		if capabilities.get(&"build_profile") != "web_core":
			failures.append("build profile is not web_core")
		if capabilities.get(&"single_threaded") != true:
			failures.append("web_core did not report single_threaded")
		if capabilities.get(&"runtime_memory_only") != true:
			failures.append("web_core did not default to runtime_memory_only")
		if capabilities.get(&"heightfield_terrain") != true:
			failures.append("heightfield terrain capability was not reported")
		if capabilities.get(&"bounded_update_scheduler") != false:
			failures.append("bounded scheduler was over-reported")
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
		terrain.call(&"set_grid_create", true)
		if not bool(terrain.call(&"is_grid_created")):
			failures.append("memory-only terrain grid was not created")
		else:
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
		terrain.call(&"set_grid_create", false)
		world.queue_free()

	if failures.is_empty():
		print(
			"MTERRAIN_RUNTIME_SMOKE_OK initialized_tile_samples=4489 ",
			"rejected_non_finite=1",
		)
		quit(0)
	else:
		for failure in failures:
			push_error(failure)
		quit(1)
