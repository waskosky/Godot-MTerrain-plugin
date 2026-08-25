extends SceneTree


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var failures: Array[String] = []
	var runtime_script := load("res://runtime/web_extended_runtime.gd")
	if runtime_script == null:
		failures.append("extended runtime script did not load")
		_finish(failures)
		return
	var runtime: Node3D = runtime_script.new()
	root.add_child(runtime)
	var capabilities: Dictionary = runtime.get_runtime_capabilities()
	for capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
		if capabilities.get(capability) != true:
			failures.append("extended runtime omitted %s" % capability)
	if capabilities.get(&"runtime_navigation_baking") != false:
		failures.append("extended runtime over-reported navigation baking")

	var configured: Dictionary = runtime.configure_limits({
		"max_foliage_instances": 16,
		"max_installed_per_capability": 4,
		"max_mesh_vertices": 8,
		"allow_in_memory_resources": true,
	})
	if not bool(configured.get("ok", false)):
		failures.append("extended runtime limits failed: %s" % JSON.stringify(configured))
	var rejected_limit: Dictionary = runtime.configure_limits({"max_foliage_instances": 9000})
	if rejected_limit.get("code") != "invalid_foliage_limit":
		failures.append("oversized foliage limit was accepted")
	var wrong_limit_type: Dictionary = runtime.configure_limits({"max_foliage_instances": 16.0})
	if wrong_limit_type.get("code") != "invalid_limit_type":
		failures.append("non-integer extended limit was accepted")

	var mesh := _triangle_mesh(1.0)
	var farther_mesh := _triangle_mesh(2.0)
	var locked_runtime: Node3D = runtime_script.new()
	root.add_child(locked_runtime)
	var locked_resource: Dictionary = locked_runtime.queue_path(
		"locked-road",
		1,
		0,
		mesh,
	)
	if locked_resource.get("code") != "in_memory_resource_rejected":
		failures.append("in-memory resources were not rejected by default")
	locked_runtime.queue_free()
	var transforms: Array = []
	for index in 9:
		transforms.append(Transform3D(Basis.IDENTITY, Vector3(float(index), 0.0, 0.0)))
	var foliage_v1: Dictionary = runtime.queue_foliage(
		"grove",
		1,
		10,
		mesh,
		transforms,
	)
	var foliage_v2: Dictionary = runtime.queue_foliage(
		"grove",
		2,
		10,
		mesh,
		transforms,
	)
	if not bool(foliage_v1.get("ok", false)) or not bool(foliage_v2.get("ok", false)):
		failures.append("foliage queue failed")
	var coalesced_foliage: Dictionary = runtime.take_runtime_work_result("grove", 1)
	if coalesced_foliage.get("code") != "coalesced":
		failures.append("foliage replacement omitted its coalesced receipt")
	var step_count := _drain(runtime, Vector3.ZERO, 2, 1)
	if step_count < 5:
		failures.append("foliage upload was not observably bounded")
	var state: Dictionary = runtime.get_runtime_state()
	if int(state.installed_counts.foliage) != 1 \
	or int(state.metrics.foliage_instance_writes) != transforms.size() \
	or int(state.installed_instances.foliage) != transforms.size() \
	or int(state.installed_vertices.foliage) != 3:
		failures.append("foliage projection receipt was inconsistent")
	var idempotent_foliage: Dictionary = runtime.queue_foliage(
		"grove",
		2,
		10,
		mesh,
		transforms,
	)
	if idempotent_foliage.get("status") != "already_installed":
		failures.append("equal installed foliage revision was not idempotent")
	var staged_foliage: Dictionary = runtime.queue_foliage(
		"grove",
		3,
		10,
		mesh,
		transforms,
	)
	if not bool(staged_foliage.get("ok", false)):
		failures.append("installed foliage replacement did not stage")
	var released_pending: Dictionary = runtime.release_projection(&"foliage", "grove", 3)
	if released_pending.get("status") != "pending_released":
		failures.append("revision-scoped pending release affected the installed foliage")
	var released_pending_result: Dictionary = runtime.take_runtime_work_result("grove", 3)
	if released_pending_result.get("code") != "cancelled" \
	or int(runtime.get_runtime_state().installed_counts.foliage) != 1:
		failures.append("pending foliage release did not preserve the prior install")
	var conflicting_key: Dictionary = runtime.queue_path("grove", 3, 0, mesh)
	if conflicting_key.get("code") != "work_key_conflict":
		failures.append("cross-capability work key conflict was accepted")
	var stale_foliage: Dictionary = runtime.queue_foliage(
		"grove",
		1,
		10,
		mesh,
		transforms,
	)
	if stale_foliage.get("code") != "stale_revision":
		failures.append("stale foliage revision was accepted")

	var cancelled_transforms := transforms.duplicate(true)
	cancelled_transforms.append(Transform3D.IDENTITY)
	var queued_cancel: Dictionary = runtime.queue_foliage(
		"cancelled-grove",
		1,
		20,
		mesh,
		cancelled_transforms,
	)
	if not bool(queued_cancel.get("ok", false)):
		failures.append("cancel fixture failed to queue")
	runtime.step_runtime_work(2, 1, Vector3.ZERO)
	runtime.cancel_runtime_work("cancelled-grove", 1)
	_drain(runtime, Vector3.ZERO, 2, 1)
	var cancelled_result: Dictionary = runtime.take_runtime_work_result("cancelled-grove", 1)
	if cancelled_result.get("code") != "cancelled":
		failures.append("partially staged foliage did not cancel")

	var navigation_mesh := NavigationMesh.new()
	navigation_mesh.set_vertices(PackedVector3Array([
		Vector3(0.0, 0.0, 0.0),
		Vector3(4.0, 0.0, 0.0),
		Vector3(0.0, 0.0, 4.0),
	]))
	navigation_mesh.add_polygon(PackedInt32Array([0, 2, 1]))
	var nav_result: Dictionary = runtime.queue_navigation(
		"walkable",
		1,
		8,
		navigation_mesh,
	)
	var path_result: Dictionary = runtime.queue_path("road", 1, 7, mesh)
	var invalid_navigation_mesh := NavigationMesh.new()
	invalid_navigation_mesh.set_vertices(PackedVector3Array([
		Vector3.ZERO,
		Vector3.RIGHT,
		Vector3.FORWARD,
	]))
	invalid_navigation_mesh.add_polygon(PackedInt32Array([0, 1, 9]))
	var invalid_navigation: Dictionary = runtime.queue_navigation(
		"invalid-navigation",
		1,
		0,
		invalid_navigation_mesh,
	)
	if invalid_navigation.get("code") != "navigation_index_out_of_bounds":
		failures.append("out-of-range navigation polygon index was accepted")
	var hlod_result: Dictionary = runtime.queue_mesh_hlod(
		"rocks",
		1,
		6,
		[mesh, farther_mesh],
		PackedFloat32Array([10.0, 100.0]),
	)
	var oversized_hlod: Dictionary = runtime.queue_mesh_hlod(
		"oversized-hlod",
		1,
		0,
		[mesh, farther_mesh, mesh],
		PackedFloat32Array([10.0, 100.0, 200.0]),
	)
	if oversized_hlod.get("code") != "hlod_total_vertex_limit":
		failures.append("combined HLOD vertex ceiling was not enforced")
	for result in [nav_result, path_result, hlod_result]:
		if not bool(result.get("ok", false)):
			failures.append("extended projection queue failed: %s" % JSON.stringify(result))
	_drain(runtime, Vector3.ZERO, 4, 4)
	state = runtime.get_runtime_state()
	if int(state.installed_counts.navigation) != 1 \
	or int(state.installed_counts.paths) != 1 \
	or int(state.installed_counts.mesh_hlod) != 1:
		failures.append("one or more extended projections failed to install")
	var navigation_map := runtime.get_world_3d().navigation_map
	var navigation_path := PackedVector3Array()
	for _iteration in 60:
		await physics_frame
		NavigationServer3D.map_force_update(navigation_map)
		navigation_path = NavigationServer3D.map_get_path(
			navigation_map,
			Vector3(0.25, 0.0, 0.25),
			Vector3(2.5, 0.0, 0.5),
			true,
		)
		if navigation_path.size() >= 2:
			break
	if navigation_path.size() < 2:
		failures.append(
			"installed navigation projection did not answer a path query "
			+ "iteration=%d closest=%s" % [
				NavigationServer3D.map_get_iteration_id(navigation_map),
				NavigationServer3D.map_get_closest_point(
					navigation_map,
					Vector3(0.25, 0.0, 0.25),
				),
			]
		)
	if int(state.installed_indices.navigation) != 3 \
	or int(state.installed_polygons.navigation) != 1 \
	or state.installed.mesh_hlod[0].lod_index != 0:
		failures.append("extended installed-state accounting was incomplete")
	for key in ["cancel-path-a", "cancel-path-b", "cancel-path-c"]:
		var queued_path: Dictionary = runtime.queue_path(key, 1, 0, mesh)
		if not bool(queued_path.get("ok", false)):
			failures.append("bounded cancellation fixture failed to queue")
		runtime.cancel_runtime_work(key, 1)
	var one_cancel: Dictionary = runtime.step_runtime_work(1, 1, Vector3.ZERO)
	if int(one_cancel.get("apply_ops", 0)) != 1 \
	or int(one_cancel.get("pending_work", 0)) != 2:
		failures.append("extended cancellation exceeded max_apply_ops")
	_drain(runtime, Vector3.ZERO, 1, 1)
	for key in ["cancel-path-a", "cancel-path-b", "cancel-path-c"]:
		if runtime.take_runtime_work_result(key, 1).get("code") != "cancelled":
			failures.append("bounded cancellation omitted a retained receipt")
	var policy_in_use: Dictionary = runtime.configure_limits({"allow_in_memory_resources": false})
	if policy_in_use.get("code") != "resource_policy_in_use":
		failures.append("installed projections allowed their resource policy to change")
	var mesh_limit_in_use: Dictionary = runtime.configure_limits({"max_mesh_vertices": 3})
	if mesh_limit_in_use.get("code") != "mesh_limit_in_use":
		failures.append("installed HLOD allowed its mesh limit to shrink underneath it")
	var invalid_focus: Dictionary = runtime.step_runtime_work(1, 1, Vector3(NAN, 0.0, 0.0))
	if invalid_focus.get("code") != "invalid_focus_position":
		failures.append("non-finite HLOD focus was accepted")
	runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
	state = runtime.get_runtime_state()
	if int(state.metrics.hlod_swaps) < 1:
		failures.append("mesh HLOD did not respond to bounded focus update")
	var swaps_after_far := int(state.metrics.hlod_swaps)
	runtime.step_runtime_work(1, 1, Vector3(11.0, 0.0, 0.0))
	if int(runtime.get_runtime_state().metrics.hlod_swaps) != swaps_after_far:
		failures.append("mesh HLOD ignored its transition hysteresis")
	runtime.step_runtime_work(1, 1, Vector3(7.0, 0.0, 0.0))
	if int(runtime.get_runtime_state().metrics.hlod_swaps) != swaps_after_far + 1:
		failures.append("mesh HLOD did not return after clearing hysteresis")

	var oversized_transforms: Array = []
	oversized_transforms.resize(17)
	oversized_transforms.fill(Transform3D.IDENTITY)
	var oversized: Dictionary = runtime.queue_foliage(
		"too-many",
		1,
		0,
		mesh,
		oversized_transforms,
	)
	if oversized.get("code") != "foliage_instance_limit":
		failures.append("oversized foliage request was accepted")

	var capacity_runtime: Node3D = runtime_script.new()
	root.add_child(capacity_runtime)
	capacity_runtime.configure_limits({
		"allow_in_memory_resources": true,
		"max_installed_per_capability": 1,
	})
	var capacity_first: Dictionary = capacity_runtime.queue_path("capacity-a", 1, 0, mesh)
	var capacity_second: Dictionary = capacity_runtime.queue_path("capacity-b", 1, 0, mesh)
	if not bool(capacity_first.get("ok", false)) \
	or capacity_second.get("code") != "installed_projection_limit":
		failures.append("extended projection ownership was not reserved fail-closed")
	capacity_runtime.queue_free()

	for release in [
		runtime.release_projection(&"foliage", "grove", 2),
		runtime.release_projection(&"navigation", "walkable", 1),
		runtime.release_projection(&"paths", "road", 1),
		runtime.release_projection(&"mesh_hlod", "rocks", 1),
	]:
		if not bool(release.get("ok", false)):
			failures.append("extended projection release failed")
	await process_frame
	state = runtime.get_runtime_state()
	for capability in [&"foliage", &"navigation", &"paths", &"mesh_hlod"]:
		if int(state.installed_counts[capability]) != 0:
			failures.append("%s projection survived release" % capability)
	_finish(failures)


func _drain(runtime: Node, focus: Vector3, instance_budget: int, apply_budget: int) -> int:
	for step_index in 128:
		var stepped: Dictionary = runtime.step_runtime_work(
			instance_budget,
			apply_budget,
			focus,
		)
		if not bool(stepped.get("ok", false)) \
		or int(stepped.get("instance_ops", 0)) > instance_budget \
		or int(stepped.get("apply_ops", 0)) > apply_budget:
			return -1
		if stepped.get("status") == "idle":
			return step_index + 1
	return 128


func _triangle_mesh(scale: float) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3(0.0, 0.0, 0.0),
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


func _finish(failures: Array[String]) -> void:
	if failures.is_empty():
		print(
			"MTERRAIN_WEB_EXTENDED_SMOKE_OK foliage=1 navigation=1 paths=1 hlod=1",
		)
		quit(0)
		return
	for failure in failures:
		push_error(failure)
	quit(1)
