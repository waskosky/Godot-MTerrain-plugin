# MTerrain Web Runtime API

- Status: experimental
- Terrain bridge version: 2
- Extended companion version: 1
- Primary target: Godot 4.7 stable, wasm32, WebGL2 Compatibility, single precision,
  no threads

This reference describes the bounded runtime contracts. It does not expose the
native editor, sculpting, baking, or project-mutation tools.

## Profiles

`web_core` contains heightfield rendering/LOD, the terrain work scheduler,
near-focus collision, and constrained Compatibility materials. `web_extended`
contains the same native closure and additionally packages
`runtime/web_extended_runtime.gd`. The companion realizes optional project data;
it does not link the native grass, navigation-authoring, path-deformation,
object-octree, HLOD-authoring, decal, or editor sources.

Call `MTerrain.get_runtime_capabilities()` before constructing a pipeline. A
caller must reject an unsuitable `api_version`, profile, format, limit, or
capability explicitly. Missing capabilities never silently succeed.

## Machine-readable contract

`runtime/web_runtime_contract.json` is the release-facing capability authority.
It records the exact Web target tuple, profile inheritance, public methods, API
and state versions, height formats, hard limits, required capabilities, and
explicitly unsupported behavior. Both profile archives contain the same bytes,
the release also publishes those bytes as a standalone asset, and the release
index binds their digest and size.

A consumer should verify the release index and contract digest before selecting
a profile, then compare the live capability dictionary with the selected
contract entry. The prose in this document explains semantics but does not
override that machine-readable profile boundary. Maintainers can check source
and contract drift with:

```sh
python3 scripts/verify_web_runtime_contract.py
```

## Terrain data contract

- Coordinates are integer height-sample coordinates in the configured terrain
  grid, not region indices or world metres.
- Heights are finite R32F metre values in row-major `PackedFloat32Array` order.
- A tile is at most 67 by 67 samples and 4,489 total samples.
- Tile rectangles must fit completely inside the grid.
- Normal generation uses the tile plus a clamped one-sample destination halo and
  an additional source halo. Every region touched by that plan must fit the
  configured resident-region ceiling.
- Shared region-border destinations are updated together. Adjacent caller tiles
  should overlap by their shared final/first sample and provide the same value.
  A one-row or one-column shared edge whose samples differ from a pending or
  resident tile with another stable key fails atomically with
  `shared_sample_mismatch`. Larger overlapping rectangles remain deliberate
  update/replacement operations and are not treated as adjacency declarations.
- Input is copied before queue success returns. Subsequent caller mutation cannot
  alter staged work.
- Visible texture installation happens only after all height writes and normals
  finish. Cancellation after partial CPU writes restores captured heights and
  normals; if any region texture was already installed, rollback uploads those
  restored images one region operation at a time before reporting `cancelled`.

## Terrain lifecycle

Configure the node, add it to a world, and create its grid before queueing work.
The Web profiles force `runtime_memory_only=true` and keep the legacy automatic
chunk/physics loops off. Call `update()` at an application-chosen bounded point
after moving the configured camera; the Web runtime performs only the visual LOD
plan/apply there, while runtime API v2 remains the sole region-residency owner.
Grid creation loads no terrain region and creates no terrain mesh instance;
queue/step admits the first region, and eviction releases its images, material,
collision, and mesh RIDs on the main thread.

Web topology is fail-closed before allocation: each terrain axis is at most 256
quads, their product is at most 65,536 topology points, the selected region size
may produce at most 1,024 regions, and visual range is at most 128 terrain
quads. These are topology ceilings, not permission to make every region
resident; the much smaller configured runtime residency and byte ceilings still
apply. The live values are reported in `topology_limits` and
`scheduler_owned_visual_residency=true`.

```gdscript
var terrain := ClassDB.instantiate(&"MTerrain") as Node3D
add_child(terrain)
terrain.set_custom_camera($Camera3D)
terrain.set_terrain_size(Vector2i(8, 8))
terrain.set_region_size(4)
terrain.set_grid_create(true)

var limits := terrain.configure_runtime_limits({
    "max_pending_work": 8,
    "max_resident_tiles": 4,
    "max_resident_regions": 4,
    "max_collision_regions": 2,
    "max_estimated_region_bytes": 8 * 1024 * 1024,
})
assert(limits.ok)

var queued := terrain.queue_height_tile(
    "terrain:0:0",
    1,
    100,
    62,
    30,
    67,
    67,
    heights_m,
    true,
)
assert(queued.ok)

while terrain.get_runtime_state().pending.size() > 0:
    var stepped := terrain.step_runtime_work(512, 1)
    assert(stepped.ok)
    await get_tree().process_frame
```

Production code should stop stepping when its own frame budget is exhausted. The
operation counts are deterministic bounds, while `elapsed_usec`, the closed
`phase_usec` dictionary, and `metrics.longest_step_usec` are diagnostics rather
than cross-device deadlines.

## Terrain methods

### `configure_runtime_limits(limits)`

Accepted keys and hard ranges:

| Key | Default | Range |
|---|---:|---:|
| `max_pending_work` | 32 | 1–128 |
| `max_resident_tiles` | 16 | 1–64 |
| `max_resident_regions` | 16 | 1–64 |
| `max_collision_regions` | 4 | 0–16 and no greater than resident regions |
| `max_estimated_region_bytes` | 64 MiB | 1 MiB–1 GiB |

Limits cannot change while tile or collision work is pending and cannot be
lowered below live tile, collision, or byte residency. The byte count is an
explicit estimate of runtime-owned region image storage, not a browser-process
heap measurement. Keys must be recognized strings and values must be integers;
unknown keys and implicit float/string coercion fail closed.

### `queue_height_tile(...)`

`work_key` contains 1–128 characters, `revision` is non-negative, and `priority`
is between -1000 and 1000. Higher priority runs first; equal priority preserves
queue order. Keys are stable tile ownership identifiers:

- the same revision already pending/resident is idempotent;
- a lower revision fails with `stale_revision`;
- a newer pre-write revision returns a retained `coalesced` receipt for the old
  staged item and replaces it;
- a newer revision arriving after writes begin occupies one staged successor
  slot on the same logical work item; rollback is sample-budgeted before that
  successor runs. Further revisions replace only that successor and retain a
  `coalesced` receipt for each displaced revision.

If `update_collision=true`, every affected region must also fit
`max_collision_regions`. With no explicit focus, the tile establishes a bounded
collision desired set, preserving the compatibility meaning of that flag.
Shared-edge comparison completes during request validation, before region load,
height mutation, normal work, texture upload, or collision refresh.

### `step_runtime_work(max_sample_ops, max_region_ops)`

`max_sample_ops` is 128–16,384 and bounds preflight, height writes, and normal
samples. `max_region_ops` is 1–16 and bounds region load/unload, texture apply,
and collision operations. One call returns `pending` or `idle`, work receipts
completed in that call, operation counts, elapsed microseconds, and queue sizes.

Region eviction and collision operations run before tile work. Texture apply is
stepped one region at a time. Collision shape creation/update is one region
operation; it remains a synchronous main-thread operation and therefore needs
representative-device stall evidence. Every step returns
`mterrain-runtime-phase-timings/v1` delta values for `region_load`, `preflight`,
`write_heights`, `generate_normals`, `texture_apply`, `collision`, `eviction`,
`rollback_heights`, `rollback_normals`, and `rollback_apply`. Cancellation
restores both heights and normals through the same sample budget, then restores
dirty GPU textures through the region budget rather than performing synchronous
whole-tile rollback.

### Cancellation, results, and release

- `cancel_runtime_work(work_key, revision)` marks matching pending work for
  bounded rollback/removal on the next step.
- `take_runtime_work_result(work_key, revision)` removes and returns a retained
  completion/cancellation/error receipt. At most 256 recent receipts are
  retained.
- `release_runtime_tile(work_key, revision)` releases stable-key ownership and
  queues regions no longer owned by another tile or collision focus for eviction.
- `release_height_tile(start_x, start_y, width, height)` is the coordinate-based
  compatibility release.

Release is idempotent. Call `step_runtime_work()` until idle to finish queued RID,
image, region-material, and collision retirement.

### Collision focus

`request_runtime_collision_focus(focus_x, focus_y, radius_regions, max_regions,
revision)` accepts an in-grid focus, radius 0–4, a region count no greater than
the configured collision ceiling, and a monotonically increasing revision.
Regions are chosen by Manhattan distance and stable region ID. Creation,
refresh, and removal are stepped independently. `max_regions=0` clears collision
ownership and remains an explicit empty focus: later tile updates cannot
silently repopulate it. Continue stepping until `state.collision.ready` is true.
Any later terrain edit intersecting an already-active collision region queues a
refresh even when that edit sets `update_collision=false`; that flag controls new
automatic admission, not permission to leave an existing shape stale.
If region loading or shape creation fails, readiness remains false and
`state.collision.error` supplies the bounded failure receipt; a newer focus
revision clears that error and retries.

Heightfield collision represents only the height lattice. Caves, bridges,
tunnels, overhangs, and foliage/path collision require separately authored mesh
or volume geometry.

### Immediate compatibility apply

`apply_height_tile(start_x, start_y, width, height, heights_m,
update_collision)` validates the same bounds and drains the same scheduler with
maximum operation budgets. It is useful for bounded compatibility calls, but a
streaming client should use queue/step so work can span frames. Immediate apply
requires an otherwise idle tile queue, so it never drains or reorders unrelated
queued work.

### Runtime state

`get_runtime_state()` returns `mterrain-runtime-state/v2` with:

- configured limits;
- pending key/revision/priority/phase/preflight/write/apply/rollback cursors and
  at most one staged successor;
- resident tile keys, revisions, rectangles, and affected-region counts;
- runtime-owned and loaded region counts plus estimated bytes;
- pending eviction count;
- `mterrain-runtime-visual-lod/v1` camera/offset, LOD counts and range, transition
  edge count, and maximum adjacent-point LOD delta from the latest bounded visual
  update;
- collision revision, desired and actually active region IDs, per-region
  readiness/generation, pending operations, and the latest bounded collision
  error;
- queued/completed/cancelled/coalesced/evicted counts, region load/unload counts,
  dirty image uploads, collision applies, step count, longest step time, and
  cumulative/longest/invocation records for every fixed timing phase.

Do not log height arrays or treat diagnostic timings as authority.

## Compatibility material

`configure_runtime_material(configuration)` accepts:

- `low_color`, `high_color`, and `steep_color`: finite colors;
- `height_scale`: finite `(0, 100000]`;
- `texture_world_scale`: finite `[0.25, 4096]`;
- `readable_emission`: finite `[0, 1]`;
- `surface_layer_count`: 0–4 fragment samples;
- `surface_layers`: a `Texture2DArray` with at most 16 layers;
- `splatmap`: a `Texture2D` supplying four normalized weights.

When layer count is nonzero, both textures are mandatory, must have dimensions
between 1 and 2,048 pixels per side, and the array must contain every sampled
layer. Only weights for enabled layers participate in normalization; an all-zero
active weight set retains semantic albedo. A zero-layer configuration uses
deterministic height/slope semantic albedo; optional textures multiply that
readable base. Settings persist as material defaults across region eviction and
reload. A custom terrain shader must expose the complete named runtime uniform
contract or configuration fails. Unknown keys and wrong value types fail closed.
The shader uses no RenderingDevice, compute, decals, GI, or volumetric features.

## Extended companion

Instantiate `MTerrainWebExtendedRuntime` only after packaging selects
`web_extended`. Its API is version 1 and separately reports `foliage`,
`navigation`, `paths`, and `mesh_hlod`.

### Resource policy

In-memory resources are rejected by default. Exported resources require exact
membership in `allowed_resource_paths`, which accepts at most 256 unique
`res://` paths of at most 256 characters. A trusted test or generator may set
`allow_in_memory_resources=true` deliberately. Filesystem paths outside
`res://`, URLs, scripts, scenes, and arbitrary executable entry points are not
accepted by the projection methods.

### Extended limits

| Key | Default | Hard maximum |
|---|---:|---:|
| `max_pending_work` | 32 | 128 |
| `max_foliage_instances` | 2,048 | 8,192 |
| `max_installed_per_capability` | 32 | 128 |
| `max_mesh_vertices` | 65,536 | 65,536 |
| `max_mesh_indices` | 196,608 | 262,144 |
| `max_navigation_vertices` | 4,096 | 8,192 |
| `max_navigation_polygons` | 4,096 | 8,192 |
| `max_navigation_indices` | 32,768 | 65,536 |
| `hlod_hysteresis_m` | 2.0 | finite 0–10,000 |
| `hlod_cross_fade_steps` | 0 (immediate) | 16 |
| `allow_path_collision` | `false` | explicit boolean opt-in |
| `max_path_collision_projections` | 8 | 64 |
| `max_path_collision_vertices` | 8,192 | 65,536 |
| `max_path_collision_extent_m` | 4,096 | finite positive 10,000 |
| `path_collision_layer` | 1 | unsigned 32-bit mask |
| `path_collision_mask` | 1 | unsigned 32-bit mask |

`configure_limits()` rejects unknown keys and cannot run while work is pending.
It cannot shrink below installed data, and resource allowlist/in-memory policy
cannot change while projections are installed. Work keys are globally unique
across extended capabilities, revisions are monotonic, and priority uses the
same -1000–1000 range as terrain work. An equal revision is idempotent; each
displaced revision retains a `coalesced` receipt. Installed-key capacity is
reserved at queue time and fails closed instead of silently evicting another key.
Installed pre-baked collision also locks its enable/layer/mask policy, and
installed HLOD locks its fade-step policy, until those projections are released.

### Foliage

`queue_foliage(work_key, revision, priority, mesh, transforms, material=null,
quality_tier=&"custom", projection_area_m2=0.0)`
accepts a bounded mesh (1–16 surfaces), finite `Transform3D` values, and an
optional allowed material. It creates a staged `MultiMesh`, writes at most
`max_instance_ops` transforms per `step_runtime_work()`, and retains the previous
projection until installation. Named quality tiers add immutable per-projection
instance and density ceilings: low is 256 and 0.25/m², medium is 1,024 and
1.0/m², and high is 2,048 and 2.0/m². Named tiers require a finite positive
area no larger than 16,777,216 m². `custom` preserves the API v1 compatibility
path and remains bounded by `max_foliage_instances`. Foliage collision is not
supported.

### Navigation

`queue_navigation(work_key, revision, priority, navigation_mesh,
transform=Transform3D.IDENTITY)` installs already baked `NavigationMesh` data
after vertex/polygon/resource/transform validation. It never calls runtime
navigation baking. Validation includes finite vertices, polygon cardinality,
total polygon indices, index bounds, and finite bounded agent radius, height,
and maximum slope metadata. Native and exported fixtures install two adjacent
regions and require an actual `NavigationServer3D` query across their join, not
only node creation.

### Paths

`queue_path(work_key, revision, priority, baked_mesh,
transform=Transform3D.IDENTITY, material=null, collision_shape=null)` installs
an already baked mesh. When `allow_path_collision=true`, one separately authored,
allowlisted `BoxShape3D`, `CapsuleShape3D`, `CylinderShape3D`,
`ConvexPolygonShape3D`, or `ConcavePolygonShape3D` may be installed under the
projection-count, point-count, extent, layer, and mask limits. The entire shape
is validated before the visual/collision node is staged. The runtime does not
receive a curve, deform vertices, cut terrain, or generate collision; generated
road/river collision remains unsupported.

### Mesh HLOD

`queue_mesh_hlod(work_key, revision, priority, meshes, distances,
transform=Transform3D.IDENTITY, material=null)` accepts one to four meshes.
Distances are finite, non-negative, strictly increasing, and correspond to the
maximum focus distance for each level. Both each mesh and the sum of all level
vertices/indices must fit their limits. One call changes at most one installed
HLOD projection, retaining the last complete mesh between calls. Transitions use
`hlod_hysteresis_m` around each outward threshold to avoid boundary thrash. A
nonzero `hlod_cross_fade_steps` stages a second mesh instance and advances at
most one fade step per apply operation. A changed desired level cancels the
in-flight fade in one bounded operation; zero keeps the API v1 immediate-swap
behavior.

### Extended stepping and ownership

`step_runtime_work(max_instance_ops, max_apply_ops, focus_position)` accepts an
instance budget of 1–8,192 and apply budget of 1–64. It stages foliage, installs
completed projections atomically, then uses remaining apply operations for HLOD
focus changes. Cancellation/disposal consumes one apply operation, `focus_position`
must be finite, and `pending` remains reported while HLOD swaps still exceed the
current apply budget.

`cancel_runtime_work()`, `take_runtime_work_result()`, and
`release_projection(capability, work_key, revision)` are idempotent ownership
operations. A revision-scoped release may cancel a staged replacement while
retaining the older installed projection; wildcard release retires both. At most
256 recent results are retained. State reports pending cursors, sorted installed
key/revision/LOD records, per-capability vertex/index/polygon/instance counts,
queue/cancel/coalesce/release metrics, foliage transform writes, HLOD swaps, and
longest step time. It also reports tiered foliage ownership, navigation agent
profiles, path collision shapes/vertices, and HLOD fade target/progress plus
start/step/cancellation metrics. The caller owns when a terrain tile's dependent foliage,
navigation, path, or HLOD projection is released; the companion deliberately
does not infer a second spatial grid.

## Release status

Native and local headed virtual-display Chromium/Firefox fixtures validate these
contracts. A local software-rendered 256-stop extended diagnostic additionally
completed moving 1/2/1/1 foliage/navigation/path/HLOD ownership with all three
foliage tiers, joined navigation queries, pre-baked collision rays, bounded
cross-fades, and zero final residency. Its hardware frame/startup thresholds did
not pass and it is not release evidence. Pinned Playwright WebKit reaches the runtime marker and a nonblank
frame but currently fails the strict WebGL error gate, so it remains diagnostic
and is not Safari evidence. These runs are correctness evidence, not
representative hardware or physical-mobile performance evidence. See
`WEB_RUNTIME_ROADMAP.md` for the open clean-CI, traversal, timing, Safari,
Android, iOS, and feature-specific release gates.
