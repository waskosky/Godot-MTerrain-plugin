extends Node3D


@onready var status: Label = $Overlay/Panel/Status
@onready var camera: Camera3D = $Camera3D

var _terrain: Node3D


func _ready() -> void:
	RenderingServer.set_default_clear_color(Color(0.025, 0.045, 0.075))
	camera.look_at(Vector3(128.0, 0.0, 128.0))
	var failures: Array[String] = []
	if not ClassDB.class_exists(&"MTerrain"):
		failures.append("MTerrain did not register")
	for excluded_class in [&"MGrass", &"MNavigationRegion3D", &"MPath", &"MHlod"]:
		if ClassDB.class_exists(excluded_class):
			failures.append("web_core unexpectedly registered %s" % excluded_class)

	var capabilities: Dictionary = {}
	_terrain = ClassDB.instantiate(&"MTerrain") as Node3D
	if _terrain == null:
		failures.append("MTerrain could not be instantiated")
	else:
		capabilities = _terrain.call(&"get_runtime_capabilities")
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
		for core_capability in [
			&"heightfield_terrain",
			&"visual_lod",
			&"heightfield_collision",
			&"compatibility_materials",
			&"height_tile_apply",
		]:
			if capabilities.get(core_capability) != true:
				failures.append("web_core omitted %s" % core_capability)
		if capabilities.get(&"bounded_update_scheduler") != false:
			failures.append("web_core over-reported bounded scheduling")
		if capabilities.get(&"bounded_collision") != false:
			failures.append("web_core over-reported bounded collision")
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
		_terrain.call(&"set_grid_create", true)
		if not bool(_terrain.call(&"is_grid_created")):
			failures.append("memory-only terrain grid was not created")
		else:
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

	await get_tree().process_frame
	await get_tree().process_frame
	if failures.is_empty():
		status.text = "MTerrain Web core · terrain tile applied\nGodot 4.7 · WebGL2 · wasm32 · no threads"
		print(
			"MTERRAIN_WEB_SMOKE_OK initialized_tile_samples=4489 rejected_non_finite=1 ",
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
