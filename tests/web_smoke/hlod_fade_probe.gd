extends RefCounted

## Render the public HLOD API in a tiny isolated world. The disjoint red/blue
## patches make an ignored opacity property observable without depth ambiguity.


static func verify(host: Node) -> String:
	var viewport := SubViewport.new()
	viewport.size = Vector2i(256, 128)
	viewport.own_world_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	host.add_child(viewport)
	var environment := WorldEnvironment.new()
	environment.environment = Environment.new()
	environment.environment.background_mode = Environment.BG_COLOR
	environment.environment.background_color = Color.BLACK
	viewport.add_child(environment)
	var camera := Camera3D.new()
	camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	camera.keep_aspect = Camera3D.KEEP_WIDTH
	camera.size = 4.0
	camera.position = Vector3(0.0, 0.0, 4.0)
	viewport.add_child(camera)
	camera.make_current()
	var runtime: Node3D = load("res://runtime/web_extended_runtime.gd").new()
	viewport.add_child(runtime)
	runtime.configure_limits({"allow_in_memory_resources": true, "hlod_cross_fade_steps": 4})
	var red := StandardMaterial3D.new()
	red.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	red.cull_mode = BaseMaterial3D.CULL_DISABLED
	red.albedo_color = Color.RED
	var blue := StandardMaterial3D.new()
	blue.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	blue.cull_mode = BaseMaterial3D.CULL_DISABLED
	blue.albedo_color = Color.BLUE
	var meshes := [_patch(-0.8, red), _patch(0.8, blue)]
	var queued: Dictionary = runtime.queue_mesh_hlod(
		"render-probe", 1, 0, meshes, PackedFloat32Array([10.0, 100.0]),
	)
	if not bool(queued.get("ok", false)):
		viewport.queue_free()
		return "HLOD render probe queue failed: %s" % JSON.stringify(queued)
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	var frames: Array[Image] = []
	var samples: Array[Dictionary] = []
	await _capture(viewport, "near", frames, samples)
	runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
	await _capture(viewport, "start", frames, samples)
	for index in 4:
		runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
		await _capture(viewport, "step_%d" % (index + 1), frames, samples)
	# Cancel a return transition after its first visible step.
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
	await _capture(viewport, "cancelled", frames, samples)
	# Replacing and releasing an in-flight projection must retire its materials.
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	runtime.queue_mesh_hlod("render-probe", 2, 0, meshes, PackedFloat32Array([10.0, 100.0]))
	runtime.step_runtime_work(1, 1, Vector3.ZERO)
	await _capture(viewport, "replaced", frames, samples)
	runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
	runtime.step_runtime_work(1, 1, Vector3(500.0, 0.0, 0.0))
	runtime.release_projection(&"mesh_hlod", "render-probe")
	await _capture(viewport, "released", frames, samples)
	var failure := ""
	if float(samples[0].near) < 0.9 or float(samples[0].far) > 0.03:
		failure = "HLOD initial frame did not show only its near level"
	elif absf(float(samples[1].near) - float(samples[0].near)) > 0.03 \
	or float(samples[1].far) > 0.03:
		failure = "HLOD incoming level became visible before its first fade step"
	for index in range(2, 5):
		if float(samples[index].near) >= float(samples[index - 1].near) - 0.04 \
		or float(samples[index].far) <= float(samples[index - 1].far) + 0.04 \
		or float(samples[index].near) < 0.04 or float(samples[index].far) > 0.96:
			failure = "HLOD intermediate frames did not interpolate both visible levels"
	if float(samples[5].near) > 0.03 or float(samples[5].far) < 0.9 \
	or float(samples[6].near) > 0.03 or float(samples[6].far) < 0.9:
		failure = "HLOD finish/cancellation did not restore the complete far level"
	if float(samples[7].near) < 0.9 or float(samples[7].far) > 0.03 \
	or float(samples[8].near) > 0.03 or float(samples[8].far) > 0.03:
		failure = "HLOD replacement/release left a stale rendered level"
	if red.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED \
	or blue.transparency != BaseMaterial3D.TRANSPARENCY_DISABLED \
	or red.albedo_color != Color.RED or blue.albedo_color != Color.BLUE:
		failure = "HLOD fade mutated caller-owned materials"
	var contact := Image.create(768, 384, false, Image.FORMAT_RGBA8)
	for index in frames.size():
		contact.blit_rect(frames[index], Rect2i(Vector2i.ZERO, viewport.size),
			Vector2i((index % 3) * 256, (index / 3) * 128))
	if OS.has_feature("web"):
		JavaScriptBridge.eval("window.__mterrainHlodFadeProbe = %s;" % JSON.stringify({
			"schema": "mterrain-hlod-render-probe-v1",
			"samples": samples,
			"failure": failure,
			"contact_sheet_png": Marshalls.raw_to_base64(contact.save_png_to_buffer()),
		}))
	print("MTERRAIN_HLOD_RENDER_PROBE ", JSON.stringify({"samples": samples, "failure": failure}))
	viewport.queue_free()
	return failure


static func _capture(
	viewport: SubViewport, label: String, frames: Array[Image], samples: Array[Dictionary],
) -> void:
	await viewport.get_tree().process_frame
	await RenderingServer.frame_post_draw
	var frame := viewport.get_texture().get_image()
	frames.append(frame)
	# Orthographic size is the viewport width: patch centres are x=77 and 179.
	samples.append({"label": label, "near": frame.get_pixel(77, 64).r,
		"far": frame.get_pixel(179, 64).b})


static func _patch(offset: float, material: Material) -> ArrayMesh:
	var arrays := []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = PackedVector3Array([
		Vector3(offset - 0.5, -0.5, 0.0), Vector3(offset + 0.5, -0.5, 0.0),
		Vector3(offset + 0.5, 0.5, 0.0), Vector3(offset - 0.5, 0.5, 0.0),
	])
	arrays[Mesh.ARRAY_INDEX] = PackedInt32Array([0, 1, 2, 0, 2, 3])
	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	mesh.surface_set_material(0, material)
	return mesh
