extends SceneTree


func _init() -> void:
	var failures: Array[String] = []
	for name in [&"MTerrain", &"MGrass", &"MPath", &"MNavigationRegion3D", &"MHlod", &"MOctree"]:
		if not ClassDB.class_exists(name):
			failures.append("embedded runtime omitted %s" % name)
	for name in [&"MMeshJoiner", &"MAssetMesh", &"MAssetMeshData", &"MAssetMeshUpdater", &"MAssetTable"]:
		if ClassDB.class_exists(name):
			failures.append("embedded runtime included editor class %s" % name)
	if ClassDB.class_exists(&"MHlod") and ClassDB.class_has_method(&"MHlod", &"get_joined_mesh"):
		failures.append("embedded runtime included HLOD authoring helpers")
	if ClassDB.class_exists(&"MHlodScene") and ClassDB.class_has_method(&"MHlodScene", &"get_triangle_mesh"):
		failures.append("embedded runtime included HLOD editor geometry")
	if ClassDB.class_exists(&"MTerrain"):
		var terrain = ClassDB.instantiate(&"MTerrain")
		var capabilities: Dictionary = terrain.get_runtime_capabilities()
		if capabilities.get(&"build_profile") != "runtime":
			failures.append("embedded runtime reported the wrong profile")
		for capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
			if capabilities.get(capability) != true:
				failures.append("embedded runtime omitted %s capability" % capability)
		terrain.free()
	if failures.is_empty():
		print("MTERRAIN_EMBEDDED_RUNTIME_OK static=1 native_subsystems=1 editor_classes=0")
		quit(0)
	else:
		for failure in failures:
			push_error(failure)
		quit(1)
