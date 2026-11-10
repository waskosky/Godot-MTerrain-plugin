extends SceneTree

const MeshImport = preload("res://asset_mesh_import.gd")

const REQUIRED_CLASSES: Array[StringName] = [
	&"MTerrain",
	&"MOctree",
	&"MGrass",
	&"MNavigationRegion3D",
	&"MPath",
	&"MHlod",
	&"MMeshJoiner",
	&"MAssetMeshUpdater",
	&"MAssetMesh",
	&"MAssetMeshData",
	&"MAssetTable",
]


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var failures: Array[String] = []
	_check_material_sets(failures)
	for required_class in REQUIRED_CLASSES:
		if not ClassDB.class_exists(required_class):
			failures.append("full profile omitted %s" % required_class)
	if not ClassDB.class_has_method(&"MHlod", &"get_joined_mesh"):
		failures.append("full profile omitted HLOD authoring methods")
	if not ClassDB.class_has_method(&"MHlodScene", &"get_triangle_mesh"):
		failures.append("full profile omitted HLOD editor geometry")

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


func _check_material_sets(failures: Array[String]) -> void:
	# Deliberately unequal counts detect transposing [variant][surface].
	for dimensions in [Vector2i(3, 2), Vector2i(2, 3), Vector2i(1, 2)]:
		var source := ImporterMesh.new()
		for surface in dimensions.y:
			var arrays: Array = []
			arrays.resize(Mesh.ARRAY_MAX)
			arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([Vector3.ZERO, Vector3.RIGHT, Vector3.UP])
			source.add_surface(Mesh.PRIMITIVE_TRIANGLES, arrays)
		var sets: Array = []
		for variant in dimensions.x:
			var row: Array = []
			for surface in dimensions.y:
				row.append("variant_%d_surface_%d" % [variant, surface])
			sets.append(row)
		var result := MeshImport.create(source, sets)
		if not result.ok or result.mesh.material_set_get_count() != dimensions.x or result.mesh.get_surface_count() != dimensions.y or result.material_sets != sets:
			failures.append("material variant/surface counts changed: %s" % dimensions)
		for invalid in [[], null, "materials", [sets[0], []], [[42]], ["surface"]]:
			if MeshImport.create(source, invalid).ok:
				failures.append("invalid material-set metadata was accepted")
		# Empty names intentionally preserve an unassigned material slot.
		var empty_names: Array = []
		for surface in dimensions.y:
			empty_names.append("")
		if not MeshImport.create(source, [empty_names]).ok:
			failures.append("unassigned material slots were rejected")
	if MeshImport.create(null, [["material"]]).ok:
		failures.append("missing import mesh was accepted")
