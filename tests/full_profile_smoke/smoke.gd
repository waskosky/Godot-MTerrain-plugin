extends SceneTree


const REQUIRED_CLASSES: Array[StringName] = [
	&"MTerrain",
	&"MOctree",
	&"MGrass",
	&"MNavigationRegion3D",
	&"MPath",
	&"MHlod",
]


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var failures: Array[String] = []
	for required_class in REQUIRED_CLASSES:
		if not ClassDB.class_exists(required_class):
			failures.append("full profile omitted %s" % required_class)

	var terrain := ClassDB.instantiate(&"MTerrain") as Node3D
	if terrain == null:
		failures.append("full-profile MTerrain could not be instantiated")
	else:
		var capabilities: Dictionary = terrain.call(&"get_runtime_capabilities")
		if capabilities.get(&"api_version") != 2:
			failures.append("full profile runtime API version is not 2")
		if capabilities.get(&"build_profile") != "full":
			failures.append("full profile reported the wrong build profile")
		if capabilities.get(&"single_threaded") != false:
			failures.append("full profile unexpectedly reported single-threaded")
		for capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
			if capabilities.get(capability) != true:
				failures.append("full profile omitted %s capability" % capability)
		terrain.free()

	if failures.is_empty():
		print(
			"MTERRAIN_FULL_PROFILE_SMOKE_OK octree=1 grass=1 navigation=1 ",
			"paths=1 hlod=1 runtime_api=2",
		)
		quit(0)
	else:
		for failure in failures:
			push_error(failure)
		quit(1)
